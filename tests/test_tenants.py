import pytest
from app import store,tenants
from app.pipeline import calculate,execute,load_sample
from app.scenario import parameters_for
from app.errors import DomainError
from app.modules.m3_grants.rules import evaluate as grant_review
from app.modules.m7_seals.rules import evaluate as seal


def run(sample="tenants.csv"):
    return calculate(load_sample(sample),parameters_for(sample))

@pytest.fixture
def tenant_run(): return run()

def rows_by_event(result,stage=1):
    return {row["event_id"]:row for row in result["stages"][stage]["rows"]}


# ---- 裁决：声明优先 ----
def test_declared_tenant_wins_without_waiting_for_archive(tenant_run):
    rows=rows_by_event(tenant_run)
    assert rows["T002"]["tenant"]=="B" and rows["T002"]["tenant_status"]==tenants.LOCKED
    assert rows["T007"]["tenant"]=="B"  # 档案缺失也照样当天锁定

def test_archive_mismatch_keeps_declaration_and_marks_evidence(tenant_run):
    row=rows_by_event(tenant_run)["T008"]
    assert row["tenant"]=="B" and row["tenant_status"]==tenants.LOCKED
    assert row["tenant_reason"]=="TENANT_DECLARED_ARCHIVE_CONFLICT"
    assert row["tenant_lock"]["evidence"]["archive_mismatch"] is True
    assert row["tenant_lock"]["evidence"]["archive_tenants"]==["A"]

def test_shared_resource_is_judged_per_tenant(tenant_run):
    "租户A授权失效、租户B仍有效：同名资源同一分区必须得出不同结论。"
    partition_rows={row["event_id"]:row for row in tenant_run["stages"][4]["rows"]}
    assert (partition_rows["T001"]["resource"],partition_rows["T001"]["partition"])==(partition_rows["T002"]["resource"],partition_rows["T002"]["partition"])
    assert partition_rows["T001"]["effect"]=="deny" and partition_rows["T002"]["effect"]=="allow"

def test_archive_tenant_grant_is_not_borrowable(tenant_run):
    "档案把 B 记到 A 名下，也不能借用 A 的授权。"
    row=rows_by_event(tenant_run)["T008"]
    assert row["tenant"]=="B"
    matched={r["event_id"]:r for r in tenant_run["stages"][3]["rows"]}["T008"]["matched_rules"]
    assert "GA-01" not in matched and matched==["GB-01"]


# ---- 凭据缺失先待核 ----
def test_missing_credential_waits_for_review(tenant_run):
    row=rows_by_event(tenant_run)["T004"]
    assert row["tenant"]=="A" and row["tenant_status"]==tenants.PENDING
    assert row["tenant_reason"]=="TENANT_CREDENTIAL_MISSING"
    pending=[q["event_id"] for q in tenant_run["stages"][5]["cumulative_quarantine"]]
    assert "T004" in pending

def test_declaration_missing_waits_instead_of_guessing():
    lock=tenants.resolve({"event_id":"X1","principal":"analyst","resource":"orders","partition":"2026-10"},{"tenant_declarations":[]})
    assert lock["status"]==tenants.PENDING and lock["tenant"] is None
    assert lock["reason"]=="TENANT_DECLARATION_MISSING"

def test_conflicting_declarations_wait(tenant_run):
    row=rows_by_event(tenant_run)["T003"]
    assert row["tenant_status"]==tenants.PENDING and row["tenant_reason"]=="TENANT_DECLARATION_CONFLICT"

def test_pending_rows_never_reach_grant_review(tenant_run):
    reviewed={row["event_id"] for row in tenant_run["stages"][2]["rows"]}
    assert reviewed=={"T001","T002","T006","T007","T008"}
    quarantined={q["event_id"] for q in tenant_run["stages"][2]["quarantine"]}
    assert quarantined=={"T003","T004","T005"}

def test_pending_lock_cannot_be_switched_past():
    "待核记录不能被切换接口绕过，必须先补凭据。"
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO tenant_locks(access_key,tenant,status,reason,version,evidence,original_archive,updated_at) VALUES ('K','A',?,'TENANT_CREDENTIAL_MISSING',1,'{}','[]','now')",(tenants.PENDING,))
    with pytest.raises(DomainError) as error:
        store.switch_lock("K",1,"B")
    assert error.value.status==409


# ---- 锁定只认它：M6/M7 ----
def test_difference_reconciliation_uses_lock(tenant_run):
    metrics=tenant_run["stages"][5]["metrics"]
    assert metrics["by_tenant"]["A"]["differences"]==2
    assert metrics["by_tenant"]["B"]["differences"]==0
    for row in tenant_run["stages"][5]["rows"]:
        assert row["tenant"]==rows_by_event(tenant_run)[row["event_id"]]["tenant"]

def test_seal_records_lock_fingerprint(tenant_run):
    seal_metrics=tenant_run["stages"][6]["metrics"]
    assert seal_metrics["lock_fingerprint"]
    assert seal_metrics["tenants"]==2

def test_seal_refuses_rows_still_pending():
    "直接传入待核行时必须拒绝；流水线中这些行已先被 M3 隔离。"
    row={"event_id":"E","principal":"p","resource":"orders","partition":"2026-10","access_time":"t","observed":"allowed","reported":"1"}
    lock=tenants.resolve(row,{"tenant_declarations":[]})
    with pytest.raises(DomainError) as error: seal([{**row,"tenant_lock":lock}],{})
    assert error.value.code=="TENANT_PENDING"

def test_pending_rows_are_quarantined_not_sealed(tenant_run):
    sealed={row["event_id"] for row in tenant_run["stages"][6]["rows"]}
    pending={row["event_id"] for row in tenant_run["stages"][6]["cumulative_quarantine"]}
    assert pending=={"T003","T004","T005"} and not (sealed & pending)

def test_seal_rejects_same_key_across_tenants():
    "同名资源的两条记录若被压成同一访问键，封存必须拒绝。"
    row={"event_id":"E","principal":"p","resource":"orders","partition":"2026-10","access_time":"t","observed":"allowed","reported":"1"}
    lock=tenants.resolve({**row,"tenant":"A","tenant_credential":"c"},{"tenant_declarations":[]})
    with pytest.raises(DomainError): seal([{**row,"tenant_lock":lock},{**row,"tenant_lock":lock}],{})


# ---- 幂等与版本 ----
def test_rerun_does_not_add_duplicate_locks():
    raw=load_sample("tenants.csv");params=parameters_for("tenants.csv")
    first=execute(raw,params);count=len(store.locks_all())
    second=execute(raw,params)
    assert first["run_id"]==second["run_id"] and len(store.locks_all())==count==8
    for lock in store.locks_all(): assert lock["version"]==1

def test_switch_is_versioned_and_keeps_original_archive():
    raw=load_sample("tenants.csv");params=parameters_for("tenants.csv")
    execute(raw,params)
    key=tenants.access_key({"event_id":"T008","principal":"analyst","resource":"orders","partition":"2026-10","access_time":"2026-11-16T00:00:00Z","observed":"allowed","reported":"1"})
    before=store.get_lock(key);assert before["tenant"]=="B" and before["original_archive"]==["A"] and before["version"]==1
    switched=store.switch_lock(key,before["version"],"A")
    assert switched["tenant"]=="A" and switched["version"]==2 and switched["original_archive"]==["A"]
    assert switched["evidence"]["switched_from"]=="B"

def test_failed_switch_preserves_previous_version_and_archive():
    raw=load_sample("tenants.csv");execute(raw,parameters_for("tenants.csv"))
    key=tenants.access_key({"event_id":"T008","principal":"analyst","resource":"orders","partition":"2026-10","access_time":"2026-11-16T00:00:00Z","observed":"allowed","reported":"1"})
    store.switch_lock(key,1,"A")
    with pytest.raises(DomainError) as error: store.switch_lock(key,1,"B")
    assert error.value.status==409
    current=store.get_lock(key)
    assert current["tenant"]=="A" and current["version"]==2 and current["original_archive"]==["A"]
    assert [h["version"] for h in store.lock_history(key)]==[1,2]
    assert store.lock_history(key)[0]["tenant"]=="B"  # 上一版仍在历史中

def test_rerun_after_switch_keeps_locked_tenant():
    "切换后重跑不能把归属改回声明值；只能提示建议。"
    raw=load_sample("tenants.csv");params=parameters_for("tenants.csv")
    execute(raw,params)
    key=tenants.access_key({"event_id":"T008","principal":"analyst","resource":"orders","partition":"2026-10","access_time":"2026-11-16T00:00:00Z","observed":"allowed","reported":"1"})
    store.switch_lock(key,1,"A")
    rerun=calculate(raw,params)
    row={r["event_id"]:r for r in rerun["stages"][1]["rows"]}["T008"]
    assert row["tenant"]=="A" and row["tenant_status"]==tenants.LOCKED
    assert row["tenant_proposal"]["tenant"]=="B"

def test_pending_lock_upgrades_once_credential_arrives():
    text=load_sample("tenants.csv").decode("utf-8-sig")
    params=parameters_for("tenants.csv")
    execute(text.encode(),params)
    key=tenants.access_key({"event_id":"T004","principal":"analyst","resource":"orders","partition":"2026-10","access_time":"2026-11-16T00:00:00Z","observed":"allowed","reported":"1"})
    assert store.get_lock(key)["status"]==tenants.PENDING
    fixed=text.replace("无凭据不得据声明放行,A,\n","无凭据不得据声明放行,A,cred-a-004\n")
    execute(fixed.encode(),params)
    assert store.get_lock(key)["status"]==tenants.LOCKED
    assert [h["version"] for h in store.lock_history(key)]==[1,2]


# ---- 兼容：未声明租户的批次保持原口径 ----
def test_single_tenant_batches_are_unchanged():
    result=calculate(load_sample("dirty.csv"))
    assert all(row["tenant_status"]==tenants.LEGACY for row in result["stages"][1]["rows"])
    assert result["stages"][4]["metrics"]["violations"]==16
    assert result["stages"][5]["metrics"]["balanced"] is True


# ---- 接口 ----
def test_lock_api_lists_and_filters(client):
    client.post("/api/runs",json={"sample":"tenants.csv"})
    payload=client.get("/api/tenants/locks").get_json()
    assert payload["summary"]["total"]==8 and payload["summary"]["pending"]==3
    pending=client.get("/api/tenants/locks?status=待核").get_json()["locks"]
    assert len(pending)==3

def test_switch_to_same_tenant_is_rejected():
    raw=load_sample("tenants.csv");execute(raw,parameters_for("tenants.csv"))
    key=tenants.access_key({"event_id":"T001","principal":"analyst","resource":"orders","partition":"2026-10","access_time":"2026-11-16T00:00:00Z","observed":"allowed","reported":"1"})
    with pytest.raises(DomainError) as error: store.switch_lock(key,1,"A")
    assert error.value.status==409 and store.get_lock(key)["version"]==1

def test_lock_api_switch_conflict(client):
    client.post("/api/runs",json={"sample":"tenants.csv"})
    lock=client.get("/api/tenants/locks").get_json()["locks"][0]
    url="/api/tenants/locks/"+lock["access_key"].replace("/","%2F")+"/switch"
    ok=client.post(url,json={"version":lock["version"],"tenant":"Z"})
    assert ok.status_code==200 and ok.get_json()["version"]==lock["version"]+1
    stale=client.post(url,json={"version":lock["version"],"tenant":"Y"})
    assert stale.status_code==409

def test_runs_api_accepts_tenant_sample_with_scenario(client):
    response=client.post("/api/runs",json={"sample":"tenants.csv"})
    assert response.status_code==200
    stages=response.get_json()["stages"]
    assert stages[1]["metrics"]["tenants"]==2 and stages[6]["metrics"]["ready"] is True
