from app.reasons import reject
from app import tenants
def evaluate(rows,context):
    good=[];bad=[]
    for row in rows:
        lock=row.get("tenant_lock") or {}
        if tenants.pending(lock):bad.append(tenants.reject_pending(row));continue
        if row.get("observed") not in {"allowed","blocked"}:bad.append(reject(row,"BAD_ACCESS_OUTCOME","访问结果必须为allowed或blocked"));continue
        effect=row["effect"];expected="1" if effect=="allow" else "0";actual="1" if row["observed"]=="allowed" else "0"
        good.append({**row,"tenant":lock.get("tenant"),"tenant_status":lock.get("status"),"expected":expected,"reported":actual,"upstream_decision":row["reported"],"partition_result":"授权内" if row["matched_rules"] else "未授权分区","violation":"越权放行" if expected=="0" and actual=="1" else "误拦截" if expected=="1" and actual=="0" else "一致"})
    by_tenant={}
    for row in good:
        bucket=by_tenant.setdefault(row.get("tenant") or "—",{"allowed":0,"blocked":0,"violations":0,"false_blocks":0})
        bucket["allowed"]+=row["expected"]=="1";bucket["blocked"]+=row["expected"]=="0"
        bucket["violations"]+=row["violation"]=="越权放行";bucket["false_blocks"]+=row["violation"]=="误拦截"
    return {"rows":good,"quarantine":bad,"metrics":{"allowed":sum(r["expected"]=="1" for r in good),"blocked":sum(r["expected"]=="0" for r in good),"violations":sum(r["violation"]=="越权放行" for r in good),"false_blocks":sum(r["violation"]=="误拦截" for r in good),"by_tenant":by_tenant}}
