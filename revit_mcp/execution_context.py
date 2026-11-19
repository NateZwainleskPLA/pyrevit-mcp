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


ROLLED_BACK_PREFIX = "Revit failure rolled back the commit: "
CAPTURE_FAILED = "; failure capture failed: "
NO_REASON_HELP = (u"To find the reason, run that edit alone, without try/except, and read failures; "
                  u"a failures preprocessor set on the transaction keeps Revit's message from the connector.")
MAX_HEADLINE_ERROR_CHARS = 200


def collapse_errors(errors):
    """Identical cleanup errors once each, first-seen order, with count when repeated."""
    collapsed, seen = [], {}
    for item in errors:
        key = repr(sorted(item.items())) if isinstance(item, dict) else repr(item)
        if key in seen:
            entry = seen[key]
            entry["count"] = entry.get("count", 1) + 1
            continue
        entry = dict(item) if isinstance(item, dict) else item
        seen[key] = entry
        collapsed.append(entry)
    return collapsed


def _quoted(names):
    return u", ".join(u"'{0}'".format(safe_text(name)) for name in names)


def _times(count):
    return u" ({0} times)".format(count) if count > 1 else u""


def _clip(text):
    text = safe_text(text)
    return text if len(text) <= MAX_HEADLINE_ERROR_CHARS else text[:MAX_HEADLINE_ERROR_CHARS - 3] + u"..."


def _rollback_reason(entry):
    """(Revit's reason or None, capture error or None) for a rolled-back commit entry."""
    error = safe_text(entry.get("error", ""))
    if error.startswith(ROLLED_BACK_PREFIX):
        return error[len(ROLLED_BACK_PREFIX):], None
    if CAPTURE_FAILED in error:
        return None, error.split(CAPTURE_FAILED, 1)[1]
    return None, None


def describe_cleanup(errors, leaked=(), unresolved=(), unsafe=False, failures=()):
    """One short headline for owned-scope cleanup: what Revit or the script actually did.

    Order: unsafe cleanup, then scopes the script left open, then commits that
    Revit rolled back. Identical errors are counted, not repeated.
    """
    errors = collapse_errors(errors)
    rollbacks = [item for item in errors if item.get("rolled_back")]
    others = [item for item in errors if not item.get("rolled_back")]
    parts = []
    if others:
        first = others[0]
        if first.get("scope"):
            where = u"of '{0}' ({1})".format(safe_text(first["scope"]), first.get("stage"))
        else:
            where = u"({0})".format(first.get("stage"))
        text = u"{0} {1}: {2}{3}".format(u"Unsafe cleanup" if unsafe else u"Cleanup failed", where,
                                        _clip(first.get("error", "")).rstrip(u"."),
                                        _times(first.get("count", 1)))
        more = sum(item.get("count", 1) for item in others[1:])
        text += u"; {0} more in cleanup_errors.".format(more) if more else u"."
        if unsafe:
            text += u" The connector will block model changes until Revit is restarted."
        parts.append(text)
    closed = [name for name in leaked if name not in unresolved]
    if closed:
        noun = u"scope" if len(closed) == 1 else u"scopes"
        parts.append(u"The script left owned {0} {1} open; the connector rolled {2} back.".format(
            noun, _quoted(closed), u"it" if len(closed) == 1 else u"them"))
    if unresolved:
        parts.append(u"Owned scope {0} could not be closed and is retained for recovery.".format(
            _quoted(unresolved)))
    if rollbacks:
        # Per scope: how many commits Revit rolled back and the distinct reasons.
        scopes = []
        for item in rollbacks:
            name = safe_text(item.get("scope"))
            entry = next((scope for scope in scopes if scope[0] == name), None)
            if entry is None:
                entry = [name, 0, [], []]
                scopes.append(entry)
            entry[1] += item.get("count", 1)
            reason, capture_error = _rollback_reason(item)
            if reason and reason not in entry[2]:
                entry[2].append(reason)
            if capture_error and capture_error not in entry[3]:
                entry[3].append(capture_error)
        segments, unknown, capture_errors = [], False, []
        for name, count, reasons, scope_capture_errors in scopes:
            if reasons:
                shown = u" / ".join(_clip(reason) for reason in reasons[:2])
                if len(reasons) > 2:
                    shown += u" / {0} more".format(len(reasons) - 2)
                segments.append(u"'{0}'{1}: {2}".format(name, _times(count), shown.rstrip(u".")))
            else:
                unknown = True
                capture_errors.extend(scope_capture_errors)
                segments.append(u"'{0}'{1} without reporting a reason".format(name, _times(count)))
        noun = u"commit" if len(rollbacks) == 1 and rollbacks[0].get("count", 1) == 1 else u"commits"
        text = u"Revit rolled back the {0} of {1}.".format(noun, u"; ".join(segments))
        if unknown:
            unavailable = [item.get("error") for item in failures
                           if item.get("action") == "capture_unavailable"]
            if capture_errors or unavailable:
                text += u" Revit failure capture did not work in this call: {0}.".format(
                    _clip((capture_errors + unavailable)[0]).rstrip(u"."))
            else:
                text += u" " + NO_REASON_HELP
        parts.append(text)
    if not parts:
        parts.append(u"Execution ended with unsafe cleanup; see cleanup_errors.")
    return u" ".join(parts)


def _same_document(first, second):
    """Compare native document wrappers without trusting Python identity alone."""
    if first is second:
        return True
    # Either wrapper may be a proxy or may already be invalid. An exception
    # never establishes equality; the identical-object case remains reliable.
    for left, right in ((first, second), (second, first)):
        try:
            if left.Equals(right):
                return True
        except Exception:
            pass
    return False


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
            unresolved = [scope.name for scope in self.context.active
                          if scope is self or self.context._descends_from(scope, self)]
            raise TransactionScopeError(describe_cleanup(
                self.context.cleanup_errors[before:], unresolved=unresolved,
                unsafe=self.context.unsafe, failures=self.context.failures))
        return False


class ExecutionContext(object):
    def __init__(self, db, selected_document, transaction_mode="script", cancellation_check=None,
                 document_provider=None, failures=None):
        if transaction_mode not in ("script", "managed"):
            raise ValueError("transaction_mode must be 'script' or 'managed'")
        self.db = db
        self.document = selected_document
        self.transaction_mode = transaction_mode
        self.cancellation_check = cancellation_check
        # Optional API-context callback for application execution only. It
        # enumerates document state, never foreign transaction objects.
        self.document_provider = document_provider
        # Shared with FailureCapture; names the failure behind a rolled-back commit.
        self.failures = failures if failures is not None else []
        self.scopes = []
        self.active = []
        self.documents = []
        if selected_document is not None:
            self.documents.append(selected_document)
        self.cleanup_errors = []
        self.document_notes = []
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
                             if _same_document(item.document, scope.document)), None)
        factory = self.db.TransactionGroup if scope.kind == "rollback" else self.db.Transaction
        scope.native = factory(scope.document, scope.name)
        self.scopes.append(scope)
        self.active.append(scope)  # register BEFORE Start; it may raise after starting
        if not any(_same_document(doc, scope.document) for doc in self.documents):
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

    def _error(self, scope, stage, error, unsafe=True, rolled_back=False):
        entry = {"scope": scope.name, "stage": stage, "error": safe_text(error)}
        if rolled_back:
            # Revit finished the commit RolledBack: a failed edit, not unsafe state.
            entry["rolled_back"] = True
        self.cleanup_errors.append(entry)
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
                reported = len(self.failures)
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
                    message = "Expected {0}, received {1}".format(expected, status)
                    reported_now = self.failures[reported:]
                    cause = "; ".join(safe_text(item.get("description", "")) for item in reported_now
                                      if item.get("action") == "rolled_back")
                    revit_rolled_back = not rollback and status == ts.RolledBack
                    if cause and not rollback:
                        message = ROLLED_BACK_PREFIX + cause
                    elif revit_rolled_back:
                        # The handler failed, so Revit's message was not recorded.
                        broken = [safe_text(item.get("error", "")) for item in reported_now
                                  if item.get("action") == "capture_error"]
                        if broken:
                            message += CAPTURE_FAILED + broken[0]
                    self._error(scope, "rollback" if rollback else "commit", message,
                                unsafe=status not in (ts.Committed, ts.RolledBack),
                                rolled_back=revit_rolled_back)
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
            if self.document_provider is not None:
                self._observe_documents()
                for document in self.documents:
                    self._guard_document(document)
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
            leaked = [scope.name for scope in self.active]
            self.close()
            if not failed and (leaked or self.cleanup_errors or self.unsafe):
                message = describe_cleanup(self.cleanup_errors, leaked,
                                           [scope.name for scope in self.active], self.unsafe, self.failures)
                if any(item.get("rolled_back") for item in self.cleanup_errors):
                    # Its scope raised, so the script caught that error and went on.
                    message += (u" The script caught the error and kept running, so anything else "
                                u"it committed is still in the model.")
                raise TransactionScopeError(message)

    def close(self):
        """Unwind owned scopes in reverse order; never recover raw transactions."""
        if self.closed:
            return
        for scope in list(reversed(self.active)):
            self._finish(scope, rollback=True)
        if self.document_provider is not None:
            try:
                self._observe_documents()
            except BaseException as error:
                self.cleanup_errors.append({"stage": "application_document_snapshot", "error": safe_text(error)})
                self.unsafe = True
        for document in self.documents:
            try:
                if not document.IsValidObject:
                    selected = _same_document(document, self.document)
                    unresolved = any(_same_document(scope.document, document) for scope in self.active)
                    if not selected and not unresolved:
                        # A family-edit workflow may close its secondary doc
                        # after every owned scope has settled. Keep its receipts.
                        self.document_notes.append({"stage": "document_closed"})
                        continue
                    raise UnsafeDocumentError("Selected document or document with an unresolved owned scope is invalid")
                if document.IsModifiable:
                    raise UnsafeDocumentError("Document postcondition is invalid or still modifiable")
            except BaseException as error:
                self.cleanup_errors.append({"stage": "document_postcondition", "error": safe_text(error)})
                self.unsafe = True
        self.closed = True
        if self.active and self not in _retained_contexts:
            _retained_contexts.append(self)

    def _observe_documents(self):
        for document in self.document_provider():
            if not any(_same_document(document, old) for old in self.documents):
                self.documents.append(document)

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
                "checks": list(self.checks), "cleanup_errors": collapse_errors(self.cleanup_errors),
                "document_notes": [dict(note) for note in self.document_notes]}
