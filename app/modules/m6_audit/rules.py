from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError
from app import tenants
def evaluate(rows,context):
    context=context or {}
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    if accepted & rejected: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"output_records":len(rows)}
    if intake:
        excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"]
        m.update(input=intake["input"],excluded=excluded,balanced=intake["input"]==len(accepted)+len(rejected)+excluded)
    else:m.update(input=len(accepted)+len(rejected),excluded=0,balanced=True)
    output=[];by_tenant={}
    for row in rows:
        lock=row.get("tenant_lock") or {}
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        difference=expected-reported
        tenant=lock.get("tenant") or "—"
        bucket=by_tenant.setdefault(tenant,{"expected_total":Decimal(0),"reported_total":Decimal(0),"differences":0,"records":0})
        bucket["expected_total"]+=expected;bucket["reported_total"]+=reported;bucket["records"]+=1
        bucket["differences"]+=difference!=0
        output.append({**row,"tenant":lock.get("tenant"),"tenant_status":lock.get("status"),"lock_version":lock.get("version"),"difference":str(difference),"status":"通过" if expected==reported else "差异"})
    expected_total=sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))
    reported_total=sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))
    m.update(expected_total=str(expected_total),reported_total=str(reported_total),differences=sum(r["status"]=="差异" for r in output),
        by_tenant={name:{**values,"expected_total":str(values["expected_total"]),"reported_total":str(values["reported_total"])} for name,values in by_tenant.items()})
    # 差异核对只认锁：结果须能按租户拆开，且每个租户各自己对平，不允许跨租户抵消。
    if any(row.get("tenant_status")==tenants.PENDING for row in rows):
        m["pending_tenants"]=sorted({row.get("tenant_reason") or "TENANT_PENDING" for row in rows if row.get("tenant_status")==tenants.PENDING})
    return {"rows":output,"quarantine":[],"metrics":m}
