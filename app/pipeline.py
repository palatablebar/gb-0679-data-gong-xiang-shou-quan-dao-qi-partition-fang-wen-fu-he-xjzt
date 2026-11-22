import time
from app.config import ROOT,MODULES
from app.errors import DomainError
from app.values import scalar
from app.manifest import digest,manifest
from app import store,locks
from app.modules.m1_accesses.rules import evaluate as stage1
from app.modules.m2_resources.rules import evaluate as stage2
from app.modules.m3_grants.rules import evaluate as stage3
from app.modules.m4_conflicts.rules import evaluate as stage4
from app.modules.m5_partitions.rules import evaluate as stage5
from app.modules.m6_audit.rules import evaluate as stage6
from app.modules.m7_seals.rules import evaluate as stage7
STAGES=[stage1,stage2,stage3,stage4,stage5,stage6,stage7]
# 归属锁登记发生在资源映射之后、授权复核之前，M3-M7 只读锁。
LOCK_STAGE=1
def load_sample(name):
    if name not in {"dirty.csv","clean.csv","legacy.csv","tenants.csv"}: raise DomainError("BAD_SAMPLE","样例不存在",404)
    return (ROOT/"sample_data"/name).read_bytes()
def sample_parameters(name,params=None):
    """仓内多租户样例自带场景参数；调用方显式给出的参数优先。"""
    from app.scenario import parameters_for
    merged=parameters_for(name) if name else {}
    merged.update(params or {})
    return merged
def calculate(raw,params=None,stop=6,persist_locks=False):
    params=params or {};started=time.monotonic();context={"parameters":params,"raw":raw,"quarantine":[]};stages=[];rows=[];lock_summary=None;lock_fingerprint=None
    for index,stage in enumerate(STAGES[:stop+1]):
        result=stage(raw if index==0 else rows,context)
        result=scalar(result);rows=result["rows"]
        context["quarantine"].extend(result.get("quarantine",[]))
        if index==0: context["intake"]=result["metrics"]
        if index==LOCK_STAGE:
            rows,stored=locks.register(rows,persist=persist_locks)
            result={**result,"rows":rows,"metrics":{**result["metrics"],**locks.summary([r["tenant_lock"] for r in rows])}}
            lock_summary=locks.summary([r["tenant_lock"] for r in rows]);lock_fingerprint=lock_summary["fingerprint"]
            lock_summary=locks.summary(stored);lock_fingerprint=lock_summary["fingerprint"]
        result["cumulative_quarantine"]=list(context["quarantine"])
        context[MODULES[index][0]]=result
        stages.append(result)
    return {"run_id":digest(raw,params,lock_fingerprint)[:20],"stages":stages,"manifest":manifest(raw,params,started,lock_summary),"parameters":params}
def execute(raw,params=None):
    result=calculate(raw,params,persist_locks=True);return store.save(result["run_id"],result)
def stage_preview(index,payload):
    if "rows" in payload and index>0:
        if not isinstance(payload["rows"],list) or any(not isinstance(row,dict) for row in payload["rows"]): raise DomainError("BAD_ROWS","记录需要对象列表")
        if not isinstance(payload.get("context",{}),dict): raise DomainError("BAD_CONTEXT","上下文需要对象")
        return scalar(STAGES[index](payload["rows"],payload.get("context",{"parameters":{},"quarantine":[]})))
    raw=payload.get("csv");sample=payload.get("sample","dirty.csv");params=payload.get("parameters",{})
    if raw is None: params=sample_parameters(sample,params)
    raw=raw.encode() if isinstance(raw,str) else load_sample(sample)
    return calculate(raw,params,index)["stages"][-1]
