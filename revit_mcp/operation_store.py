# -*- coding: utf-8 -*-
"""Primitive-only, generation-scoped operation receipts (IronPython compatible)."""
import copy
import hashlib
import json
import threading
import time
from collections import deque


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
                 max_receipt_bytes=262144, clock=None):
        if not runtime_id or min(max_queue, max_operations, max_payload_bytes,
                                 max_receipt_bytes, retention_seconds) <= 0:
            raise ValueError("runtime and positive bounds required")
        self.runtime_id = runtime_id
        self.max_queue, self.max_operations = max_queue, max_operations
        self.retention_seconds = retention_seconds
        self.max_payload_bytes, self.max_receipt_bytes = max_payload_bytes, max_receipt_bytes
        self.clock = clock or time.time
        self.lock = threading.RLock()
        self.records, self.queue = {}, deque()
        self.expired = False

    def _ensure_live(self):
        if self.expired:
            raise OperationError("expired_runtime", "Runtime generation expired", 410)

    def _prune(self):
        # Keep bounded tombstones, never reuse an expired operation ID.
        now = self.clock()
        for record in self.records.values():
            end = record["receipt"].get("completed_at")
            if end is not None and now - end >= self.retention_seconds:
                record["payload"] = None
                record["receipt"].pop("result", None)
                record["receipt"]["receipt_expired"] = True

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
            operation_id = self.queue.popleft()
            record = self.records[operation_id]
            record["receipt"].update(state="running", started_at=self.clock(), effects="unknown")
            return operation_id, copy.deepcopy(record["payload"])

    def complete(self, operation_id, state, effects, result):
        if state not in TERMINAL or effects not in EFFECTS:
            raise ValueError("Invalid terminal state/effects")
        result = primitive_copy(result)
        encoded = json.dumps(result, ensure_ascii=True)
        if len(encoded.encode("utf-8")) > self.max_receipt_bytes:
            result = {"receipt_truncated": True, "preview": encoded[:self.max_receipt_bytes // 6]}
        with self.lock:
            record = self.records[operation_id]
            if record["receipt"]["state"] not in ("running", "waiting_for_user"):
                raise OperationError("invalid_transition", "Only running operations can complete")
            record["receipt"].update(state=state, effects=effects, result=result,
                                      completed_at=self.clock())
            record["payload"] = None
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
            receipt["cancellation_requested"] = True
            if receipt["state"] == "queued":
                self.queue.remove(operation_id)
                receipt.update(state="canceled", effects="none", completed_at=self.clock())
                record["payload"] = None
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
            receipt["interaction"] = str(description or "Known native interaction")[:1024] if active else None

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
