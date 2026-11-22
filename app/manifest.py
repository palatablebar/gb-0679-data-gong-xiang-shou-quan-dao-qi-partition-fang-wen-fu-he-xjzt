import hashlib,json,time
from datetime import datetime,timezone
from app.config import RULE_VERSION
def digest(raw,params=None,lock_fingerprint=None):
    # 锁指纹进入批次身份：同源同声明且锁不变才复用批次，归属一变必然产生新批次。
    material=raw+json.dumps(params or {},sort_keys=True,ensure_ascii=False).encode()+RULE_VERSION.encode()+str(lock_fingerprint or "").encode()
    return hashlib.sha256(material).hexdigest()
def manifest(raw,params,started,lock_summary=None):
    return {"input_sha256":hashlib.sha256(raw).hexdigest(),"rule_version":RULE_VERSION,"parameters":params,"generated_at":datetime.now(timezone.utc).isoformat(),"elapsed_ms":round((time.monotonic()-started)*1000,2),"tenant_locks":lock_summary or {}}
