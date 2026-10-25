from __future__ import annotations
import hashlib, json, os
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional
from .storage import SQLiteStateStore

class EvidenceStatus(str, Enum):
    PENDING="PENDING"
    VERIFIED="VERIFIED"
    REJECTED="REJECTED"

@dataclass
class EvidenceBundle:
    task_id: str
    title: str
    content: str
    source: str="runtime"
    status: EvidenceStatus=EvidenceStatus.PENDING
    tags: List[str]=field(default_factory=list)

EvidenceAuthorizer=Callable[[str,EvidenceBundle],bool]

class EvidenceRegistry:
    """Durable evidence with reviewer authorization and provenance checks."""
    def __init__(self,state_store:Optional[SQLiteStateStore]=None,*,db_path:Optional[str]=None,
                 evidence_authorizer:Optional[EvidenceAuthorizer]=None)->None:
        if state_store is not None and db_path is not None: raise ValueError("Pass state_store or db_path, not both")
        self.store=state_store or SQLiteStateStore(db_path)
        prod=os.environ.get("SWARM_ENV","").strip().lower() in {"prod","production"}
        if prod and not self.store.persistent: raise RuntimeError("A durable SWARM_STATE_DB is required for production evidence storage")
        if prod and evidence_authorizer is None: raise RuntimeError("A trusted evidence_authorizer is required for production evidence verification")
        self.evidence_authorizer=evidence_authorizer

    @staticmethod
    def _bundle(task_id:str,row:object)->EvidenceBundle:
        return EvidenceBundle(task_id,row["title"],row["content"],row["source"],EvidenceStatus(row["status"]),json.loads(row["tags_json"]))

    @staticmethod
    def _fingerprint(row:object)->tuple:
        return (row["id"],row["task_id"],row["title"],hashlib.sha256(row["content"].encode("utf-8")).hexdigest(),row["source"],row["status"],row["tags_json"])

    def add(self,bundle:EvidenceBundle)->None:
        if any(not isinstance(v,str) or not v.strip() for v in (bundle.task_id,bundle.title,bundle.content,bundle.source)):
            raise ValueError("Evidence requires non-empty task_id, title, content, and source")
        if bundle.status!=EvidenceStatus.PENDING: raise ValueError("New evidence must start as PENDING and be verified by the registry")
        if not isinstance(bundle.tags,list) or any(not isinstance(x,str) or not x.strip() for x in bundle.tags):
            raise ValueError("Evidence tags must be a list of non-empty strings")
        tags=list(bundle.tags); digest=hashlib.sha256(bundle.content.encode("utf-8")).hexdigest()
        with self.store.transaction() as c:
            if c.execute("SELECT 1 FROM evidence_bundles WHERE task_id=? AND title=? LIMIT 1",(bundle.task_id,bundle.title)).fetchone():
                raise ValueError("Evidence titles must be unique within a task")
            cur=c.execute("INSERT INTO evidence_bundles(task_id,title,content,source,status,tags_json) VALUES(?,?,?,?,?,?)",
                          (bundle.task_id,bundle.title,bundle.content,bundle.source,"PENDING",json.dumps(tags,sort_keys=True,separators=(",",":"),allow_nan=False)))
            self.store.append_event_in_transaction(c,"evidence.added",task_id=bundle.task_id,payload={"record_id":int(cur.lastrowid),"title":bundle.title,"source":bundle.source,"content_sha256":digest,"tags":tags,"initial_status":"PENDING"})

    def get(self,task_id:str)->List[EvidenceBundle]:
        with self.store.read_connection() as c:
            rows=c.execute("SELECT id,task_id,title,content,source,status,tags_json FROM evidence_bundles WHERE task_id=? ORDER BY id",(task_id,)).fetchall()
        return [self._bundle(task_id,r) for r in rows]

    def _change(self,task_id:str,title:Optional[str],target:EvidenceStatus,verifier:Optional[str])->bool:
        with self.store.read_connection() as c:
            rows=c.execute("SELECT id,task_id,title,content,source,status,tags_json FROM evidence_bundles WHERE task_id=? ORDER BY id",(task_id,)).fetchall()
        candidates=[r for r in rows if (title is None or r["title"]==title) and (r["status"]=="PENDING" if target==EvidenceStatus.VERIFIED else r["status"]!="REJECTED")]
        if not candidates:
            self.store.append_event("evidence.status_noop",task_id=task_id,actor=verifier,payload={"title":title,"target_status":target.value,"records_changed":0}); return False
        prod=os.environ.get("SWARM_ENV","").strip().lower() in {"prod","production"}
        if prod and (not verifier or self.evidence_authorizer is None):
            self.store.append_event("evidence.status_denied",task_id=task_id,actor=verifier,payload={"title":title,"target_status":target.value,"reason":"trusted_verifier_required"}); return False
        if self.evidence_authorizer is not None:
            if not verifier: return False
            try: allowed=all(bool(self.evidence_authorizer(verifier,self._bundle(task_id,r))) for r in candidates)
            except Exception: allowed=False
            if not allowed:
                self.store.append_event("evidence.status_denied",task_id=task_id,actor=verifier,payload={"title":title,"target_status":target.value,"reason":"identity_authorization_failed"}); return False
        ids=[r["id"] for r in candidates]; fingerprints=[self._fingerprint(r) for r in candidates]
        with self.store.transaction() as c:
            marks=",".join("?" for _ in ids)
            fresh=c.execute(f"SELECT id,task_id,title,content,source,status,tags_json FROM evidence_bundles WHERE id IN ({marks}) ORDER BY id",ids).fetchall()
            if [self._fingerprint(r) for r in fresh]!=fingerprints:
                self.store.append_event_in_transaction(c,"evidence.status_denied",task_id=task_id,actor=verifier,payload={"title":title,"target_status":target.value,"reason":"evidence_changed_during_review"}); return False
            expected="PENDING" if target==EvidenceStatus.VERIFIED else "REJECTED"
            cur=c.execute(f"UPDATE evidence_bundles SET status=? WHERE id IN ({marks}) AND status{'=' if target==EvidenceStatus.VERIFIED else '<>'}?",
                          [target.value,*ids,expected])
            changed=cur.rowcount
            self.store.append_event_in_transaction(c,"evidence.verified" if target==EvidenceStatus.VERIFIED else "evidence.rejected",task_id=task_id,actor=verifier,payload={"title":title,"record_ids":ids,"records_changed":changed,"target_status":target.value})
            return changed==len(ids)

    def mark_verified(self,task_id:str,title:Optional[str]=None,*,verifier:Optional[str]=None)->bool:
        return self._change(task_id,title,EvidenceStatus.VERIFIED,verifier)
    def mark_rejected(self,task_id:str,title:Optional[str]=None,*,verifier:Optional[str]=None)->bool:
        return self._change(task_id,title,EvidenceStatus.REJECTED,verifier)
    def is_verified(self,task_id:str)->bool:
        return self.store.verify_evidence_state(task_id)
    def has_evidence(self,task_id:str)->bool:
        with self.store.read_connection() as c:
            return c.execute("SELECT 1 FROM evidence_bundles WHERE task_id=? LIMIT 1",(task_id,)).fetchone() is not None
