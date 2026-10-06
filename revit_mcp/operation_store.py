# -*- coding: utf-8 -*-
"""Primitive-only, generation-scoped operation receipts (IronPython compatible)."""
import copy
import hashlib
import json
import threading
import time
import os
import tempfile
from collections import deque
from .execution_output import safe_text


TERMINAL = frozenset(("succeeded", "failed", "canceled", "unknown_after_restart"))
EFFECTS = frozenset(("none", "committed", "rolled_back", "unknown"))


class OperationError(Exception):
    def __init__(self, code, message, status=409):
        Exception.__init__(self, message)
        self.code, self.status = code, status


def primitive_copy(value):
    """Reject live wrappers and non-finite values rather than storing them."""
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))


def payload_hash(payload):
    # Hash ALL supplied fields; new behavior-affecting fields cannot be omitted.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class OperationStore(object):
    def __init__(self, runtime_id, max_queue=32, max_operations=4096,
                 retention_seconds=14400, max_payload_bytes=1048576,
                 max_receipt_bytes=262144, clock=None, journal=None):
        if not runtime_id or min(max_queue, max_operations, max_payload_bytes,
                                 max_receipt_bytes, retention_seconds) <= 0:
            raise ValueError("runtime and positive bounds required")
        if max_receipt_bytes < 128:
            raise ValueError("Receipt bound must hold at least 128 bytes of diagnostics")
        self.runtime_id = runtime_id
        self.max_queue, self.max_operations = max_queue, max_operations
        self.retention_seconds = retention_seconds
        self.max_payload_bytes, self.max_receipt_bytes = max_payload_bytes, max_receipt_bytes
        self.clock = clock or time.time
        self.lock = threading.RLock()
        self.records, self.queue = {}, deque()
        self.expired = False
        self.journal = journal
        self.durability_failed = False
        if journal is not None:
            for receipt in journal.load(runtime_id):
                self.records[receipt["operation_id"]] = {"payload": None, "receipt": receipt}
            if len(self.records) > self.max_operations:
                raise OperationError("registry_full", "Recovered receipt capacity exceeded", 503)

    def _persist(self, kind, receipt, admission=False):
        if self.journal is None:
            return
        receipt["durability"] = "journal"
        try:
            self.journal.write(kind, receipt)
        except Exception as error:
            self.durability_failed = True
            receipt["durability"] = "uncertain"
            receipt["journal_error"] = safe_text(error)[:2048]
            if admission:
                raise OperationError("journal_unavailable", "Admission receipt could not be persisted; no execution admitted", 503)

    def _ensure_live(self):
        if self.expired:
            raise OperationError("expired_runtime", "Runtime generation expired", 410)

    def _prune(self):
        # Keep bounded tombstones, never reuse an expired operation ID.
        now = self.clock()
        for record in self.records.values():
            end = record["receipt"].get("completed_at")
            if (end is not None and now - end >= self.retention_seconds
                    and not record["receipt"].get("receipt_expired")):
                record["payload"] = None
                record["receipt"].pop("result", None)
                record["receipt"]["receipt_expired"] = True
                self._persist("retention", record["receipt"])

    def admit(self, payload):
        payload = primitive_copy(payload)
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, type(u"")) or not operation_id or len(operation_id) > 128:
            raise OperationError("invalid_operation_id", "Nonempty operation ID of at most 128 characters required", 400)
        if len(json.dumps(payload).encode("utf-8")) > self.max_payload_bytes:
            raise OperationError("payload_too_large", "Execution payload exceeds limit", 413)
        digest = payload_hash(payload)
        with self.lock:
            self._ensure_live()
            self._prune()
            existing = self.records.get(operation_id)
            if existing:
                if existing["receipt"]["payload_hash"] != digest:
                    raise OperationError("operation_conflict", "Operation ID already has a different payload")
                return copy.deepcopy(existing["receipt"]), False
            if self.durability_failed:
                raise OperationError("journal_unavailable", "Journal uncertainty blocks new admission", 503)
            if len(self.queue) >= self.max_queue:
                raise OperationError("queue_full", "Execution queue is full", 503)
            if len(self.records) >= self.max_operations:
                raise OperationError("registry_full", "Generation receipt capacity reached", 503)
            receipt = {"operation_id": operation_id, "runtime_id": self.runtime_id,
                       "payload_hash": digest, "state": "queued", "effects": "none",
                       "admitted_at": self.clock(), "durability": "memory"}
            # Preserve the routing owner's full identity envelope verbatim.
            for key in ("target", "document", "identity", "instance_id", "document_id"):
                if key in payload:
                    receipt[key] = primitive_copy(payload[key])
            if "instance_id" in payload:
                receipt["actual_target"] = dict((key, payload[key]) for key in
                                                 ("instance_id", "runtime_id", "document_id") if key in payload)
            # Durable admission MUST precede queue visibility and event wakeup.
            self._persist("admission", receipt, admission=True)
            self.records[operation_id] = {"payload": payload, "receipt": receipt}
            self.queue.append(operation_id)
            return copy.deepcopy(receipt), True

    def inspect(self, operation_id):
        with self.lock:
            self._ensure_live()
            self._prune()
            if operation_id not in self.records:
                raise OperationError("operation_not_found", "Operation is not retained in this generation", 404)
            return copy.deepcopy(self.records[operation_id]["receipt"])

    def take_next(self):
        with self.lock:
            self._ensure_live()
            if not self.queue:
                return None
            while self.queue:
                operation_id = self.queue.popleft()
                record = self.records[operation_id]
                record["receipt"].update(state="running", started_at=self.clock(), effects="unknown")
                if self.durability_failed:
                    record["receipt"].update(state="failed", effects="none", completed_at=self.clock(),
                                              durability="uncertain", result={"error": "Journal unavailable before execution"})
                    record["payload"] = None
                    continue
                self._persist("start", record["receipt"])
                if self.durability_failed:
                    record["receipt"].update(state="failed", effects="none", completed_at=self.clock(),
                                              result={"error": "Start receipt failed; executor was not entered"})
                    record["payload"] = None
                    continue
                return operation_id, copy.deepcopy(record["payload"])
            return None

    def complete(self, operation_id, state, effects, result):
        if state not in TERMINAL or effects not in EFFECTS:
            raise ValueError("Invalid terminal state/effects")
        result = primitive_copy(result)
        encoded = json.dumps(result, ensure_ascii=True)
        if len(encoded.encode("utf-8")) > self.max_receipt_bytes:
            # Keep structured diagnostics rather than returning an opaque JSON prefix.
            budget = self.max_receipt_bytes // 24
            def bounded(value, depth=0):
                if isinstance(value, type(u"")):
                    return value[:budget]
                if isinstance(value, list):
                    return [bounded(item, depth + 1) for item in value[:8]] if depth < 3 else []
                if isinstance(value, dict):
                    return dict((key, bounded(item, depth + 1)) for key, item in
                                list(value.items())[:32]) if depth < 3 else {}
                return value
            result = bounded(result)
            result.pop("code_executed", None)
            result.pop("code_attempted", None)
            result["receipt_truncated"] = True
            if len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > self.max_receipt_bytes:
                result = {"receipt_truncated": True, "error_type": safe_text(result.get("error_type", ""))[:32],
                          "error": safe_text(result.get("error", "Receipt diagnostics exceeded retention limit"))[:16]}
                if len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > self.max_receipt_bytes:
                    result = {"receipt_truncated": True, "error": "Diagnostic limit exceeded"}
        with self.lock:
            record = self.records[operation_id]
            if record["receipt"]["state"] not in ("running", "waiting_for_user"):
                raise OperationError("invalid_transition", "Only running operations can complete")
            record["receipt"].update(state=state, effects=effects, result=result,
                                      completed_at=self.clock())
            record["payload"] = None
            self._persist("completion", record["receipt"])
            return copy.deepcopy(record["receipt"])

    def cancel(self, operation_id):
        """Queued removal is atomic with take_next; running work only gets a flag."""
        with self.lock:
            self._ensure_live()
            if operation_id not in self.records:
                raise OperationError("operation_not_found", "Operation not retained", 404)
            record = self.records[operation_id]
            receipt = record["receipt"]
            if receipt["state"] in TERMINAL:
                return copy.deepcopy(receipt)
            if receipt.get("cancellation_requested"):
                return copy.deepcopy(receipt)
            receipt["cancellation_requested"] = True
            if receipt["state"] == "queued":
                self.queue.remove(operation_id)
                receipt.update(state="canceled", effects="none", completed_at=self.clock())
                record["payload"] = None
            self._persist("completion" if receipt["state"] == "canceled" else "cancellation", receipt)
            return copy.deepcopy(receipt)

    def cancellation_requested(self, operation_id):
        with self.lock:
            return self.expired or self.records[operation_id]["receipt"].get("cancellation_requested", False)

    def interaction(self, operation_id, active, description=None):
        """Only an adapter knowing a native interaction is active may call this."""
        with self.lock:
            receipt = self.records[operation_id]["receipt"]
            if receipt["state"] not in ("running", "waiting_for_user"):
                raise OperationError("invalid_transition", "Interaction requires running work")
            receipt["state"] = "waiting_for_user" if active else "running"
            receipt["interaction"] = safe_text(description or "Known native interaction")[:1024] if active else None

    def has_queued(self):
        with self.lock:
            return bool(self.queue) and not self.expired

    def expire(self):
        with self.lock:
            self.expired = True
            self.queue.clear()
            for record in self.records.values():
                if record["receipt"]["state"] not in TERMINAL:
                    record["receipt"].update(state="unknown_after_restart", effects="unknown")
                record["payload"] = None


class ReceiptJournal(object):
    """Atomic, fsynced bounded local receipts. No code/payload replay is stored.

    A deployment must provide a private directory and one owning runtime. This
    claims local receipt persistence only; disk/controller loss is outside it.
    Old generations are inspectable using load(old_runtime_id), never enqueued.
    """
    def __init__(self, directory, max_records=4096, max_record_bytes=524288):
        if max_records <= 0 or max_record_bytes <= 0:
            raise ValueError("Positive journal bounds required")
        self.directory = os.path.abspath(directory)
        self.max_records, self.max_record_bytes = max_records, max_record_bytes
        self.lock = threading.RLock()
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory)

    def _path(self, runtime_id, operation_id):
        digest = payload_hash([runtime_id, operation_id])
        return os.path.join(self.directory, digest + ".json")

    def _files(self):
        # Stop counting at the bound, rather than reading arbitrary directory size.
        names = []
        for name in os.listdir(self.directory):
            if name.endswith(".json"):
                names.append(name)
                if len(names) > self.max_records:
                    raise OperationError("journal_full", "Journal capacity exceeded", 503)
        return names

    def _read(self, path):
        with open(path, "rb") as source:
            raw = source.read(self.max_record_bytes + 1)
        if len(raw) > self.max_record_bytes:
            raise ValueError("Journal record exceeds bound")
        data = json.loads(raw.decode("utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("receipt"), dict):
            raise ValueError("Unsupported/corrupt journal receipt")
        receipt = data["receipt"]
        if os.path.abspath(path) != self._path(receipt["runtime_id"], receipt["operation_id"]):
            raise ValueError("Journal identity/filename mismatch")
        return data

    def write(self, kind, receipt):
        with self.lock:
            path = self._path(receipt["runtime_id"], receipt["operation_id"])
            exists = os.path.exists(path)
            if not exists and len(self._files()) >= self.max_records:
                raise OperationError("journal_full", "Journal receipt capacity reached", 503)
            events = self._read(path)["events"] if exists else []
            events.append({"kind": kind, "state": receipt["state"], "effects": receipt["effects"],
                           "at": receipt.get("completed_at", receipt.get("started_at", receipt["admitted_at"]))})
            content = {"version": 1, "receipt": primitive_copy(receipt), "events": events[-8:]}
            raw = json.dumps(content, ensure_ascii=True, allow_nan=False).encode("utf-8")
            if len(raw) > self.max_record_bytes:
                raise ValueError("Journal receipt exceeds bound")
            descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=self.directory)
            try:
                with os.fdopen(descriptor, "wb") as destination:
                    destination.write(raw)
                    destination.flush()
                    os.fsync(destination.fileno())
                self._replace(temporary, path)
                self._sync_directory()
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)

    def _replace(self, temporary, path):
        if hasattr(os, "replace"):
            os.replace(temporary, path)
        elif os.name == "nt":
            # IronPython 2.7 lacks os.replace; never delete the old receipt first.
            from System.IO import File
            if File.Exists(path):
                File.Replace(temporary, path, None)
            else:
                File.Move(temporary, path)
        else:
            os.rename(temporary, path)

    def _sync_directory(self):
        if os.name != "nt":
            descriptor = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def load(self, runtime_id):
        """Read receipts; EVERY unfinished admission is uncertain, never replayed."""
        with self.lock:
            receipts = []
            for name in self._files():
                receipt = self._read(os.path.join(self.directory, name))["receipt"]
                if receipt["runtime_id"] == runtime_id:
                    if receipt["state"] not in TERMINAL:
                        receipt.update(state="unknown_after_restart", effects="unknown",
                                       recovery_note="No automatic replay; reconcile saved/model state")
                    receipts.append(receipt)
            return receipts
