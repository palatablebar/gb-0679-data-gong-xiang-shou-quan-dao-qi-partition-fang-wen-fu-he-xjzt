from flask import Blueprint,request,jsonify
from app.errors import DomainError
from app import store,tenants
bp=Blueprint("tenants",__name__)
@bp.get("/api/tenants/locks")
def locks():
    items=store.locks_all()
    selected=[lock for lock in items if not request.args.get("status") or lock["status"]==request.args.get("status")]
    return jsonify({"locks":selected,"summary":{"total":len(items),"locked":sum(l["status"]==tenants.LOCKED for l in items),"pending":sum(l["status"]==tenants.PENDING for l in items),"legacy":sum(l["status"]==tenants.LEGACY for l in items),"archive_mismatch":sum(bool((l.get("evidence") or {}).get("archive_mismatch")) for l in items)}})
@bp.get("/api/tenants/locks/<path:access_key>")
def lock_detail(access_key):
    lock=store.get_lock(access_key)
    if not lock: raise DomainError("NOT_FOUND","归属记录不存在",404)
    return jsonify({**lock,"history":store.lock_history(access_key)})
@bp.post("/api/tenants/locks/<path:access_key>/switch")
def lock_switch(access_key):
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise DomainError("BAD_BODY","请求需要对象")
    version=payload.get("version")
    if not isinstance(version,int): raise DomainError("BAD_VERSION","请提供归属版本号")
    tenant=payload.get("tenant")
    if not isinstance(tenant,str): raise DomainError("BAD_TENANT","租户不能为空")
    return jsonify(store.switch_lock(access_key,version,tenant,payload.get("reason") or "TENANT_EXPLICIT_SWITCH"))
