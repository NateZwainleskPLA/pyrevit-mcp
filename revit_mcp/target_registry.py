# -*- coding: utf-8 -*-
"""One runtime's identity and synchronized primitive document snapshots.

Only refresh_documents/resolve_document may touch document wrappers. Call them
from a Revit API callback. snapshot/validate_target are safe on HTTP workers.
"""
import copy
import threading
import time
import uuid
from .identity import IdentityError, full_uuid, validate_snapshot


_registry = None
_registry_lock = threading.RLock()


def get_registry():
    """Return this connector's registry; never synthesize a default target."""
    with _registry_lock:
        if _registry is None:
            raise IdentityError("runtime_unavailable", "connector identity has not initialized")
        return _registry


def set_registry(registry):
    """Startup-only installation seam for the runtime adapter and route owners."""
    global _registry
    with _registry_lock:
        if _registry is not None and _registry is not registry:
            _registry.expire()
        _registry = registry


def retained_instance_id(process_id, process_started_at, retained=None):
    """Recover a UUID only from reliable process-scoped primitive storage."""
    if isinstance(retained, dict) and retained.get("process_id") == process_id \
            and retained.get("process_started_at") == process_started_at:
        try:
            return full_uuid(retained.get("instance_id"), "instance_id")
        except IdentityError:
            pass
    return str(uuid.uuid4())


def same_document(left, right):
    # Equality is checked only after validity, never on a disposed wrapper.
    return bool(left.IsValidObject and right.IsValidObject and
                (left is right or left.Equals(right)))


class TargetRegistry(object):
    def __init__(self, process_id, process_started_at, revit_version, endpoint,
                 instance_id=None, clock=None, **provenance):
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._documents = []
        self._expired = False
        self._snapshot = validate_snapshot(dict(
            instance_id=instance_id or str(uuid.uuid4()), runtime_id=str(uuid.uuid4()),
            process_id=process_id, process_started_at=process_started_at,
            revit_version=revit_version, endpoint=endpoint,
            documents=[], documents_known=False, snapshot_at=None, **provenance))

    def snapshot(self):
        with self._lock:
            data = copy.deepcopy(self._snapshot)
            data["snapshot_age_seconds"] = (None if data["snapshot_at"] is None else
                                            max(0.0, self._clock() - data["snapshot_at"]))
            data["runtime_available"] = not self._expired
            return data

    def validate_target(self, instance_id, runtime_id):
        full_uuid(instance_id, "instance_id")
        full_uuid(runtime_id, "runtime_id")
        with self._lock:
            if self._expired or instance_id != self._snapshot["instance_id"] \
                    or runtime_id != self._snapshot["runtime_id"]:
                raise IdentityError("stale_target", "instance/runtime does not match this connector")
            return {k: self._snapshot[k] for k in ("instance_id", "runtime_id")}

    def refresh_documents(self, documents, active_document=None):
        """API context only. Publish an atomic snapshot after a complete read."""
        with self._lock:
            if self._expired:
                raise IdentityError("stale_target", "connector runtime has expired")
            previous = self._documents
            refs, descriptors = [], []
            for doc in documents:
                if not doc.IsValidObject:
                    continue
                token = next((token for old, token in previous if same_document(old, doc)), None)
                token = token or str(uuid.uuid4())
                refs.append((doc, token))
                descriptors.append(dict(document_id=token, title=doc.Title or "Untitled",
                                        path=doc.PathName or "",
                                        is_active=bool(active_document is not None and
                                                       same_document(doc, active_document))))
            self._documents = refs
            self._snapshot.update(documents=descriptors, documents_known=True,
                                  snapshot_at=self._clock())
            self._snapshot.pop("snapshot_error", None)
        return self.snapshot()

    def record_refresh_error(self, error):
        # A failed collection must not masquerade as a fresh/empty document list.
        with self._lock:
            self._snapshot["snapshot_error"] = str(error)

    def resolve_document(self, instance_id, runtime_id, document_id, documents,
                         active_document=None):
        """API context only; re-enumerate open documents immediately before use."""
        self.validate_target(instance_id, runtime_id)
        full_uuid(document_id, "document_id")
        self.refresh_documents(documents, active_document)
        with self._lock:
            for doc, token in self._documents:
                if token == document_id and doc.IsValidObject:
                    return doc
        raise IdentityError("stale_document", "document token is not open in this runtime")

    def expire(self):
        # No wrapper access, so reload can invalidate the old runtime promptly.
        with self._lock:
            self._expired = True
            self._documents = []
