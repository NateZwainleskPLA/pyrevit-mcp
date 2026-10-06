"""Immutable target/document handles with a transactionally allocated namespace.

Persisted state is evidence, never permission to address a Revit endpoint. Every
new directory object requires a live metadata handshake before resolve succeeds.
SQLite serializes allocations across threads and MCP processes sharing a file.
"""
import base64
import copy
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from revit_mcp.identity import IdentityError, endpoint_url, validate_snapshot


class TargetDirectory:
    def __init__(self, state_path=None, clock=time.time):
        self._clock = clock
        self._lock = threading.RLock()
        self._verified = set()
        if state_path is not None:
            Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(state_path) if state_path else ":memory:",
                                   timeout=10, check_same_thread=False,
                                   isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute("CREATE TABLE IF NOT EXISTS directory_state ("
                                 "key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                self._db.execute("CREATE TABLE IF NOT EXISTS targets (handle TEXT PRIMARY KEY, "
                                 "instance TEXT NOT NULL, runtime TEXT NOT NULL, "
                                 "snapshot TEXT NOT NULL, retired INTEGER NOT NULL DEFAULT 0, "
                                 "UNIQUE(instance, runtime))")
                self._db.execute("CREATE TABLE IF NOT EXISTS documents (handle TEXT PRIMARY KEY, "
                                 "target TEXT NOT NULL, token TEXT NOT NULL, "
                                 "retired INTEGER NOT NULL DEFAULT 0, UNIQUE(target, token))")
                row = self._db.execute("SELECT value FROM directory_state WHERE key='namespace'").fetchone()
                if row is None:
                    if self._db.execute("SELECT COUNT(*) FROM targets").fetchone()[0] or \
                            self._db.execute("SELECT COUNT(*) FROM directory_state").fetchone()[0]:
                        raise IdentityError("directory_unavailable", "partial directory state cannot reset its namespace")
                    self._db.executemany("INSERT INTO directory_state VALUES (?, ?)",
                                         [("namespace", str(uuid.uuid4())), ("counter", "0"), ("version", "1")])
                elif self._db.execute("SELECT value FROM directory_state WHERE key='version'").fetchone()[0] != "1":
                    raise IdentityError("directory_unavailable", "unsupported directory state version")
                self.namespace = self._db.execute("SELECT value FROM directory_state WHERE key='namespace'").fetchone()[0]
                self._prefix = base64.urlsafe_b64encode(uuid.UUID(self.namespace).bytes).decode().rstrip("=")
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def close(self):
        with self._lock:
            self._db.close()

    def _allocate(self, kind):
        counter = int(self._db.execute("SELECT value FROM directory_state WHERE key='counter'").fetchone()[0]) + 1
        self._db.execute("UPDATE directory_state SET value=? WHERE key='counter'", (str(counter),))
        return "%s%s.%s" % (kind, self._prefix, counter)

    def _retire(self, handle):
        self._db.execute("UPDATE targets SET retired=1 WHERE handle=?", (handle,))
        self._db.execute("UPDATE documents SET retired=1 WHERE target=?", (handle,))
        self._verified.discard(handle)

    def observe(self, snapshot, expected_endpoint=None, registration=None):
        """Record validated metadata; optional native/JSON evidence must agree.

        The caller obtains snapshot from a successful /metadata/ HTTP response.
        Evidence never substitutes for a metadata handshake.
        """
        data = validate_snapshot(snapshot)
        if snapshot.get("runtime_available") is False:
            raise IdentityError("stale_target", "endpoint's runtime has expired")
        if expected_endpoint is not None and data["endpoint"] != endpoint_url(expected_endpoint):
            raise IdentityError("endpoint_mismatch", "metadata endpoint does not own the probed address")
        if registration:
            for field in ("process_id", "process_started_at", "instance_id", "runtime_id", "endpoint"):
                if field in registration and registration[field] != data[field]:
                    raise IdentityError("stale_registration", "registration disagrees on %s" % field)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                rows = self._db.execute("SELECT * FROM targets WHERE retired=0").fetchall()
                for old in rows:
                    meta = json.loads(old["snapshot"])
                    same_identity = (old["instance"], old["runtime"]) == (data["instance_id"], data["runtime_id"])
                    if same_identity:
                        if any(meta[k] != data[k] for k in ("process_id", "process_started_at")):
                            self._verified.discard(old["handle"])
                            raise IdentityError("identity_conflict", "same UUIDs claim a different process lifetime")
                        continue
                    same_process = (urlsplit(meta["endpoint"]).hostname == urlsplit(data["endpoint"]).hostname
                                    and meta["process_id"] == data["process_id"])
                    if meta["endpoint"] == data["endpoint"] or old["instance"] == data["instance_id"] or same_process:
                        self._retire(old["handle"])
                old = self._db.execute("SELECT * FROM targets WHERE instance=? AND runtime=?",
                                       (data["instance_id"], data["runtime_id"])).fetchone()
                if old is None:
                    handle = self._allocate("r")
                    self._db.execute("INSERT INTO targets(handle, instance, runtime, snapshot) VALUES (?, ?, ?, ?)",
                                     (handle, data["instance_id"], data["runtime_id"], json.dumps(data)))
                else:
                    handle = old["handle"]
                    if old["retired"]:
                        raise IdentityError("expired_target", "retired runtime cannot be revived")
                    prior = json.loads(old["snapshot"])
                    # Concurrent replies can arrive out of order. Keep the most recent
                    # complete document snapshot, while permitting exact-identity relocation.
                    if prior["documents_known"] and (not data["documents_known"] or
                            data["snapshot_at"] < prior["snapshot_at"]):
                        for k in ("documents", "documents_known", "snapshot_at"):
                            data[k] = prior[k]
                    self._db.execute("UPDATE targets SET snapshot=? WHERE handle=?", (json.dumps(data), handle))
                if data["documents_known"]:
                    live = {d["document_id"] for d in data["documents"]}
                    for doc in self._db.execute("SELECT * FROM documents WHERE target=?", (handle,)).fetchall():
                        if doc["token"] not in live:
                            self._db.execute("UPDATE documents SET retired=1 WHERE handle=?", (doc["handle"],))
                    for token in live:
                        doc = self._db.execute("SELECT * FROM documents WHERE target=? AND token=?", (handle, token)).fetchone()
                        if doc is None:
                            self._db.execute("INSERT INTO documents(handle, target, token) VALUES (?, ?, ?)",
                                             (self._allocate("d"), handle, token))
                        elif doc["retired"]:
                            raise IdentityError("expired_document", "closed document token cannot be revived")
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._verified.add(handle)
            return self._describe(handle)

    def _target(self, handle):
        if not isinstance(handle, str) or not handle:
            raise IdentityError("missing_target", "an explicit target handle is required")
        row = self._db.execute("SELECT * FROM targets WHERE handle=?", (handle,)).fetchone()
        if row is None:
            raise IdentityError("unknown_target", "target handle is unknown in this namespace")
        if row["retired"]:
            raise IdentityError("expired_target", "target runtime has been retired")
        return row

    def resolve(self, target, document=None):
        """Return the exact destination and receiver identities; never a default."""
        with self._lock:
            row = self._target(target)
            if target not in self._verified:
                raise IdentityError("verification_required", "target needs a live handshake after restart/disconnect")
            data = json.loads(row["snapshot"])
            result = {k: data[k] for k in ("instance_id", "runtime_id", "process_id", "process_started_at", "endpoint")}
            result["target"] = target
            if document is not None:
                if not isinstance(document, str) or not document:
                    raise IdentityError("missing_document", "an explicit document handle is required")
                doc = self._db.execute("SELECT * FROM documents WHERE handle=?", (document,)).fetchone()
                if doc is None:
                    raise IdentityError("unknown_document", "document handle is unknown")
                if doc["target"] != target:
                    raise IdentityError("cross_target_document", "document belongs to another target")
                if doc["retired"]:
                    raise IdentityError("expired_document", "document is no longer open")
                result.update(document=document, document_id=doc["token"])
            return result

    async def revalidate(self, target, handshake):
        """Handshake(endpoint)->primitive metadata, including after MCP restart."""
        with self._lock:
            expected = json.loads(self._target(target)["snapshot"])
            self._verified.discard(target)
        actual = await handshake(expected["endpoint"])
        data = validate_snapshot(actual)
        if any(data[k] != expected[k] for k in ("instance_id", "runtime_id", "process_id", "process_started_at")):
            with self._lock:
                self._db.execute("BEGIN IMMEDIATE")
                try:
                    self._retire(target)
                    self._db.execute("COMMIT")
                except BaseException:
                    self._db.execute("ROLLBACK")
                    raise
            raise IdentityError("stale_target", "endpoint now belongs to another process/runtime")
        self.observe(actual, expected_endpoint=expected["endpoint"])
        return self.resolve(target)

    def _describe(self, handle):
        row = self._target(handle)
        data = json.loads(row["snapshot"])
        data.update(target=handle, verified=handle in self._verified,
                    snapshot_age_seconds=None if data["snapshot_at"] is None else max(0.0, self._clock() - data["snapshot_at"]))
        aliases = {r["token"]: r["handle"] for r in self._db.execute(
            "SELECT * FROM documents WHERE target=? AND retired=0", (handle,)).fetchall()}
        for doc in data["documents"]:
            doc["document"] = aliases[doc["document_id"]]
        return copy.deepcopy(data)

    def targets(self):
        """Read cached metadata, visibly marked unverified until a handshake."""
        with self._lock:
            return [self._describe(r["handle"]) for r in self._db.execute(
                "SELECT handle FROM targets WHERE retired=0 ORDER BY handle").fetchall()]
