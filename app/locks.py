"""归属流程装配。

M2 只做资源/分区归一，不落库；真正的锁在流水线入口（M1 之后）一次算齐并登记，
之后 M3–M7 全部从记录里的 tenant_lock 读取，不再重算、不回看声明。
这样的顺序保证：同一条访问在一次运行里只可能有一个归属，且这个归属先于授权复核。

每条记录同时带两份信息：
- tenant_lock：权威归属，登记表里已有记录时一律以登记表为准；
- _tenant_computed：当次按声明/档案算出的候选归属，只在登记阶段使用，
  或用于提示“声明已变化，是否切换”。对外输出前由 register/strip 移除。
"""
from app import store,tenants

COMPUTED = "_tenant_computed"


def lock_preview(rows, parameters, mode=None):
    """挂上权威归属，并暂存当次算出的候选归属（不写库）。"""
    mode = tenants.tenant_mode(rows, parameters) if mode is None else mode
    stored = store.lock_map([tenants.access_key(row) for row in rows])
    out = []
    for row in rows:
        computed = tenants.resolve(row, parameters) if mode else tenants.legacy_lock(row)
        authoritative = stored.get(computed["access_key"]) or computed
        out.append({**row, COMPUTED: computed, "tenant_lock": authoritative, "tenant": authoritative["tenant"],
                    "tenant_status": authoritative["status"], "tenant_reason": authoritative["reason"]})
    return out


def register(rows, persist=True):
    """把候选归属登记为权威归属（persist=False 时只在本批次内生效）。"""
    computed = [row[COMPUTED] for row in rows if row.get(COMPUTED) and row[COMPUTED].get("status") != tenants.LEGACY]
    stored = store.register_locks(computed) if (persist and computed) else []
    by_key = {lock["access_key"]: lock for lock in stored}
    out = []
    for row in rows:
        key = tenants.access_key(row)
        authoritative = by_key.get(key) or row["tenant_lock"]
        out.append(_present(row, authoritative))
    return out, stored


def _present(row, lock):
    entry = {k: v for k, v in row.items() if k != COMPUTED}
    entry.update({"tenant_lock": lock, "tenant": lock["tenant"], "tenant_status": lock["status"], "tenant_reason": lock["reason"]})
    proposal = row.get(COMPUTED)
    # 声明与已锁归属不一致时只提示，不自动改锁：切换必须显式进行。
    if proposal and (proposal.get("tenant") or None) != (lock.get("tenant") or None):
        entry["tenant_proposal"] = {"tenant": proposal.get("tenant"), "reason": proposal.get("reason"), "status": proposal.get("status")}
    else:
        entry.pop("tenant_proposal", None)
    return entry


def summary(locks):
    locks = list(locks)
    return {
        "locked": sum(lock["status"] == tenants.LOCKED for lock in locks),
        "pending": sum(lock["status"] == tenants.PENDING for lock in locks),
        "legacy": sum(lock["status"] == tenants.LEGACY for lock in locks),
        "archive_mismatch": sum(bool((lock.get("evidence") or {}).get("archive_mismatch")) for lock in locks),
        "fingerprint": tenants.fingerprint(locks),
    }
