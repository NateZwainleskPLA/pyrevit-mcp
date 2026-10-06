# -*- coding: UTF-8 -*-
"""Explicit ownership of connector-created transaction scopes.

No GC/global scans, disposal of foreign transactions, or host-wide quarantine.
The execution owner must enforce unsafe-state guards on every mutation path.
"""
from .execution_output import safe_text


class ExecutionCanceled(Exception):
    pass


class TransactionScopeError(Exception):
    pass


class UnsafeDocumentError(TransactionScopeError):
    pass


# Strong references to our unresolved scopes only. Pending native transactions
# must not fall out of scope and trigger implicit cleanup by a destructor.
_retained_contexts = []


def retained_contexts():
    """Inspect owned unresolved contexts for targeted, explicit recovery."""
    return tuple(_retained_contexts)


class OwnedScope(object):
    def __init__(self, context, document, name, kind, managed=False):
        self.context = context
        self.document = document
        self.name = name
        self.kind = kind
        self.managed = managed
        self.native = None
        self.parent = None
        self.uncertain = False
        self.receipt = {"name": name, "kind": kind, "status": "Uninitialized",
                        "returned_status": None, "effect": "none", "disposed": False}

    def __enter__(self):
        self.context._start(self)
        return self

    def __exit__(self, error_type, error, tb):
        before = len(self.context.cleanup_errors)
        self.context._unwind_children(self)
        self.context._finish(self, rollback=error_type is not None or self.kind == "rollback")
        if error_type is None and len(self.context.cleanup_errors) > before:
            raise TransactionScopeError("Owned scope did not finish cleanly: {0}".format(self.name))
        return False


class ExecutionContext(object):
    def __init__(self, db, selected_document, transaction_mode="script", cancellation_check=None):
        if transaction_mode not in ("script", "managed"):
            raise ValueError("transaction_mode must be 'script' or 'managed'")
        self.db = db
        self.document = selected_document
        self.transaction_mode = transaction_mode
        self.cancellation_check = cancellation_check
        self.scopes = []
        self.active = []
        self.documents = []
        if selected_document is not None:
            self.documents.append(selected_document)
        self.cleanup_errors = []
        self.checks = []
        self.unsafe = False
        self.script_started = False
        self.closed = False

    def checkpoint(self):
        if self.cancellation_check is not None and self.cancellation_check():
            raise ExecutionCanceled("Execution canceled at checkpoint")

    def check(self, name, expected, actual):
        passed = expected == actual
        self.checks.append({"name": name, "expected": expected, "actual": actual, "passed": passed})
        if not passed:
            raise AssertionError("Check failed: {0}".format(name))
        return True

    def transaction(self, document, name):
        if self.transaction_mode == "managed":
            raise TransactionScopeError("Managed mode already owns one transaction; use script mode for additional scopes")
        return OwnedScope(self, document, name, "transaction")

    def rollback_scope(self, document, name):
        if self.transaction_mode == "managed":
            raise TransactionScopeError("Rollback groups require script mode")
        return OwnedScope(self, document, name, "rollback")

    def _guard_document(self, document):
        if document is None:
            raise UnsafeDocumentError("A document is required for a transaction")
        if not document.IsValidObject:
            raise UnsafeDocumentError("Document is no longer valid")
        if document.IsModifiable:
            raise UnsafeDocumentError("Document is already modifiable; no foreign transaction will be cleaned")

    def _start(self, scope):
        if self.closed or scope.native is not None:
            raise TransactionScopeError("Scope/context cannot be reused")
        self.checkpoint()
        self._guard_document(scope.document)
        # Native transactions cannot nest. Nested rollback groups can contain
        # ordinary transactions; group rollback undoes their committed changes.
        scope.parent = next((item for item in reversed(self.active)
                             if item.document is scope.document), None)
        factory = self.db.TransactionGroup if scope.kind == "rollback" else self.db.Transaction
        scope.native = factory(scope.document, scope.name)
        self.scopes.append(scope)
        self.active.append(scope)  # register BEFORE Start; it may raise after starting
        if not any(doc is scope.document for doc in self.documents):
            self.documents.append(scope.document)
        try:
            returned = scope.native.Start()
            status = self._status(scope)
            scope.receipt["returned_status"] = safe_text(returned)
            if returned != self.db.TransactionStatus.Started or status != self.db.TransactionStatus.Started:
                scope.uncertain = returned == self.db.TransactionStatus.Pending or status == self.db.TransactionStatus.Pending
                raise TransactionScopeError("Start did not return and confirm Started: {0}".format(scope.name))
        except BaseException:
            # __exit__ is not called when __enter__ raises.
            self._finish(scope, rollback=True)
            raise

    def _status(self, scope):
        status = scope.native.GetStatus()
        scope.receipt["status"] = safe_text(status)
        return status

    def _error(self, scope, stage, error, unsafe=True):
        self.cleanup_errors.append({"scope": scope.name, "stage": stage, "error": safe_text(error)})
        self.unsafe = self.unsafe or unsafe

    def _descends_from(self, child, parent):
        ancestor = child.parent
        while ancestor is not None:
            if ancestor is parent:
                return True
            ancestor = ancestor.parent
        return False

    def _unwind_children(self, scope):
        for child in list(reversed(self.active)):
            if self._descends_from(child, scope):
                self._finish(child, rollback=True)

    def _finish(self, scope, rollback):
        if scope not in self.active:
            return
        ts = self.db.TransactionStatus
        try:
            status = self._status(scope)
            if scope.uncertain or status == ts.Pending:
                scope.uncertain = True
                raise TransactionScopeError("Pending/unconfirmed failure processing; cleanup is not proven")
            if any(self._descends_from(child, scope) for child in self.active if child is not scope):
                raise TransactionScopeError("An owned child scope is unresolved; parent cannot finish")
            if status == ts.Started:
                action = scope.native.RollBack if rollback else scope.native.Commit
                returned = action()
                scope.receipt["returned_status"] = safe_text(returned)
                observed = self._status(scope)
                expected = ts.RolledBack if rollback else ts.Committed
                if returned == ts.Pending or observed == ts.Pending or returned != observed:
                    scope.uncertain = True
                    raise TransactionScopeError("Unconfirmed transaction status: returned {0}, observed {1}".format(returned, observed))
                status = observed
                if status != expected:
                    # A failed Commit can finish RolledBack; record it, but the
                    # requested edit still failed. Started is unwound by close.
                    self._error(scope, "rollback" if rollback else "commit",
                                "Expected {0}, received {1}".format(expected, status),
                                unsafe=status not in (ts.Committed, ts.RolledBack))
            if status == ts.Committed:
                scope.receipt["effect"] = "committed"
            elif status == ts.RolledBack:
                scope.receipt["effect"] = "rolled_back"
                if scope.kind == "rollback":
                    for child in self.scopes:
                        if self._descends_from(child, scope):
                            child.receipt["effect"] = "rolled_back"
            elif status != ts.Uninitialized:
                raise TransactionScopeError("Scope is not terminal: {0}".format(status))
            scope.native.Dispose()  # only our terminal/unstarted scopes
            scope.receipt["disposed"] = True
            self.active.remove(scope)
        except BaseException as error:
            self._error(scope, "rollback" if rollback else "commit", error)

    def run(self, compiled, namespace):
        """Execution callback for execute_script; captures start/cleanup errors."""
        failed = True
        try:
            self.checkpoint()
            if self.document is not None:
                self._guard_document(self.document)
            if self.transaction_mode == "managed":
                with OwnedScope(self, self.document, "Managed execution", "transaction", managed=True):
                    self.script_started = True
                    eval(compiled, namespace, namespace)
                    self.checkpoint()  # cancellation before commit still rolls back
            else:
                self.script_started = True
                eval(compiled, namespace, namespace)
                self.checkpoint()
            failed = False
        finally:
            leaked = bool(self.active)
            self.close()
            if not failed and (leaked or self.cleanup_errors or self.unsafe):
                raise TransactionScopeError("Execution ended with leaked scopes or unsafe cleanup")

    def close(self):
        """Unwind owned scopes in reverse order; never recover raw transactions."""
        if self.closed:
            return
        for scope in list(reversed(self.active)):
            self._finish(scope, rollback=True)
        for document in self.documents:
            try:
                if not document.IsValidObject or document.IsModifiable:
                    raise UnsafeDocumentError("Document postcondition is invalid or still modifiable")
            except BaseException as error:
                self.cleanup_errors.append({"stage": "document_postcondition", "error": safe_text(error)})
                self.unsafe = True
        self.closed = True
        if self.active and self not in _retained_contexts:
            _retained_contexts.append(self)

    def summary(self):
        """Primitive receipt fields; caller supplies validated target identities."""
        owned = "none"
        effects = [scope.receipt["effect"] for scope in self.scopes]
        if self.unsafe or self.active:
            owned = "unknown"
        elif "committed" in effects:
            owned = "committed"
        elif "rolled_back" in effects:
            owned = "rolled_back"
        # Script code can commit raw transactions then roll back an owned trial.
        # Only a known surviving commit proves overall model effects here.
        overall = owned
        if self.transaction_mode == "script" and self.script_started and owned != "committed":
            overall = "unknown"
        return {"effects": overall, "owned_effects": owned, "unsafe": self.unsafe,
                "transaction_receipts": [dict(scope.receipt) for scope in self.scopes],
                "checks": list(self.checks), "cleanup_errors": list(self.cleanup_errors)}
