import hashlib,json
from app.errors import DomainError
from app.reasons import sources
from app import tenants
def evaluate(rows,context):
    context=context or {}
    stages=[v for v in context.values() if isinstance(v,dict) and "metrics" in v]
    balances=[s["metrics"]["balanced"] for s in stages if "balanced" in s["metrics"]]
    if balances and not all(balances): raise DomainError("UNBALANCED","来源行未对平，不能归档")
    # 封存只认锁：按归属键查重，防止同名资源跨租户被并成一条证据。
    keys=[tenants.access_key(row) for row in rows]
    if len(keys)!=len(set(keys)): raise DomainError("ARCHIVE_DUPLICATE","归档业务键重复")
    if any(tenants.pending(row.get("tenant_lock")) for row in rows): raise DomainError("TENANT_PENDING","仍有租户归属待核，不能封存")
    encoded=json.dumps(rows,ensure_ascii=False,sort_keys=True,default=str).encode()
    locks=[row.get("tenant_lock") for row in rows]
    return {"rows":rows,"quarantine":[],"metrics":{"records":len(rows),"source_lines":len(set(x for row in rows for x in sources(row))),"sha256":hashlib.sha256(encoded).hexdigest(),"ready":True,"differences":sum(r.get("status")=="差异" for r in rows),"tenants":len(set(row.get("tenant") for row in rows if row.get("tenant"))),"lock_fingerprint":tenants.fingerprint([lock for lock in locks if lock])}}
