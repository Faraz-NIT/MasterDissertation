"""Content-addressed objects plus append-only, hash-chained audit events.

Local hashes detect accidental modification; this is NOT WORM storage or a signature system.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from .util import canonical, digest

class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root); (self.root / "objects").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "audit.sqlite", timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, decision_id TEXT, stage TEXT, payload TEXT, previous_hash TEXT, event_hash TEXT UNIQUE)")
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts (idempotency_key TEXT PRIMARY KEY, action_hash TEXT NOT NULL, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS memory (key TEXT PRIMARY KEY, value TEXT NOT NULL, approved_by TEXT NOT NULL, valid_until INTEGER NOT NULL)")
        self.db.commit()
    def put(self, obj) -> str:
        ref = digest(obj); path = self.root / "objects" / f"{ref}.json"
        try:
            with path.open("x", encoding="utf8") as f:
                f.write(canonical(obj))
        except FileExistsError:
            self.get(ref)  # Verify, never overwrite a corrupt object.
        return ref
    def get(self, ref: str) -> dict:
        if len(ref) != 64 or any(c not in "0123456789abcdef" for c in ref):
            raise ValueError("Invalid content reference")
        value = json.loads((self.root / "objects" / f"{ref}.json").read_text())
        if digest(value) != ref:
            raise ValueError(f"Artifact tampering detected: {ref}")
        return value
    def event(self, decision_id: str, stage: str, payload: dict) -> str:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row[0] if row else "0"*64
            event = {"decision_id": decision_id, "stage": stage, "payload": payload, "previous_hash": prev}
            h = digest(event)
            self.db.execute("INSERT INTO events(decision_id,stage,payload,previous_hash,event_hash) VALUES (?,?,?,?,?)", (decision_id, stage, canonical(payload), prev, h))
        return h
    def verify_chain(self) -> bool:
        prev = "0"*64
        for decision,stage,payload,previous,h in self.db.execute("SELECT decision_id,stage,payload,previous_hash,event_hash FROM events ORDER BY seq"):
            if previous != prev or digest({"decision_id":decision,"stage":stage,"payload":json.loads(payload),"previous_hash":previous}) != h:
                return False
            prev=h
        return True
    def record_receipt(self, receipt) -> dict:
        value = receipt.model_dump(mode="json")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row=self.db.execute("SELECT action_hash,payload FROM receipts WHERE idempotency_key=?",(receipt.idempotency_key,)).fetchone()
            if row:
                if row[0] != receipt.action_hash:
                    raise ValueError("Idempotency key collision with a different action")
                return json.loads(row[1])
            self.db.execute("INSERT INTO receipts VALUES (?,?,?)",(receipt.idempotency_key,receipt.action_hash,canonical(value)))
        return value
    def memory_write(self, key: str, value: dict, approved_by: str, valid_until: int):
        if not approved_by.strip():
            raise ValueError("Only explicitly approved resolutions may enter actionable memory")
        with self.db:
            self.db.execute("INSERT INTO memory VALUES (?,?,?,?)",(key,canonical(value),approved_by,valid_until))
    def memory_read(self, keys: list[str], day: int) -> list[dict]:
        result=[]
        for key in keys:
            row=self.db.execute("SELECT value,approved_by,valid_until FROM memory WHERE key=?",(key,)).fetchone()
            if row and row[2]>=day:
                result.append({"key":key,"resolution":json.loads(row[0]),"approved_by":row[1],"valid_until":row[2]})
        return result
    def close(self):
        self.db.close()
