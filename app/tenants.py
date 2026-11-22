"""租户归属锁定。

多个租户共用同名资源与分区时，同名并不能证明同租户。每条访问在进入授权复核前
先在归属登记表锁定一个租户；后续授权复核、差异核对和封存都只读这个锁，不再回看
资源名或上游声明的旁路信息。

裁决：声明优先。
带凭据的上游租户声明是当天的可用事实，直接锁定，避免等待档案核齐拖住共享。
档案只作对照证据：不一致不改变锁定对象，但记入 archive_mismatch，且该访问只能
使用声明租户名下的授权——档案里另一租户的授权不得借用。
声明缺失、声明互相冲突或凭据缺失时一律待核，不猜、不默认、不继承相邻记录。

锁以“记录指纹”为键：事件号 + 主体/资源/分区/访问时刻/执行结果/申报判定的摘要。
同一记录重跑命中同一把锁，不新增重复归属；凭据后补时只允许 待核→锁定 的补锁，
已锁定的归属不会被重跑悄悄改写，必须走显式切换。
"""
import hashlib
from app.reasons import reject

LOCKED = "声明锁定"
PENDING = "待核"
LEGACY = "单租户"

# 这些原因表示“还不能锁定”，必须留在待核队列，不得进入授权复核。
PENDING_REASONS = {
    "TENANT_DECLARATION_MISSING": "租户声明缺失",
    "TENANT_CREDENTIAL_MISSING": "租户凭据缺失",
    "TENANT_DECLARATION_CONFLICT": "租户声明冲突",
}

_CONTENT_FIELDS = ("principal", "resource", "partition", "access_time", "observed", "reported")


def access_key(row):
    """记录指纹；重跑同一记录必须命中同一把锁。"""
    event = str(row.get("event_id", row.get("_line", "")))
    content = "\x1f".join(str(row.get(field, "")).strip() for field in _CONTENT_FIELDS)
    return event + "|" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _declarations(parameters):
    raw = (parameters or {}).get("tenant_declarations") or []
    if isinstance(raw, dict):
        items = []
        for key, value in raw.items():
            if isinstance(value, dict):
                items.append({"event_id": str(key), **value})
            else:
                items.append({"event_id": str(key), "tenant": value})
        return items
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _matching_declarations(row, parameters):
    key = access_key(row)
    found = []
    for item in _declarations(parameters):
        if str(item.get("event_id", "")) == key or str(item.get("event_id", "")) == str(row.get("event_id", "")):
            found.append(item)
    return found


def declared_tenants(row, parameters):
    """收集该记录的全部声明；同一记录出现多个不同租户即为冲突。"""
    values = []
    inline = (row.get("tenant") or "").strip()
    if inline:
        values.append(inline)
    for item in _matching_declarations(row, parameters):
        value = (item.get("tenant") or "").strip()
        if value:
            values.append(value)
    return sorted(set(values))


def credential_for(row, parameters):
    inline = (row.get("tenant_credential") or "").strip()
    if inline:
        return inline
    for item in _matching_declarations(row, parameters):
        value = (item.get("credential") or "").strip()
        if value:
            return value
    return ""


def archive_tenants(row, parameters):
    """档案对照证据。按事件号优先，其次主体+资源+分区。"""
    key = access_key(row)
    event = str(row.get("event_id", ""))
    found = []
    for item in (parameters or {}).get("tenant_archive") or []:
        if not isinstance(item, dict):
            continue
        tenant = (item.get("tenant") or "").strip()
        if not tenant:
            continue
        declared = item.get("event_id")
        if declared is not None:
            if str(declared) in {key, event}:
                found.append(tenant)
            continue
        if str(item.get("resource", "")) != str(row.get("resource", "")):
            continue
        if str(item.get("partition", "")) != str(row.get("partition", "")):
            continue
        principal = item.get("principal")
        if principal not in (None, "") and str(principal) != str(row.get("principal", "")):
            continue
        found.append(tenant)
    return sorted(set(found))


def tenant_mode(rows, parameters=None, grants=None):
    """整批是否启用租户归属模型。未启用时保持原单租户口径。"""
    parameters = parameters or {}
    if parameters.get("tenant_declarations") or parameters.get("tenant_archive"):
        return True
    if any(row.get("tenant") or row.get("tenant_credential") for row in rows):
        return True
    if any(isinstance(g, dict) and g.get("tenant") for g in (grants or [])):
        return True
    return False


def resolve(row, parameters=None):
    """为单条访问计算归属锁。返回可序列化字典，不写库。"""
    parameters = parameters or {}
    key = access_key(row)
    declarations = declared_tenants(row, parameters)
    credential = credential_for(row, parameters)
    archive = archive_tenants(row, parameters)
    evidence = {
        "access_key": key,
        "declarations": declarations,
        "credential_present": bool(credential),
        "archive_tenants": archive,
        "archive_mismatch": False,
    }
    if not declarations:
        return _lock(key, None, PENDING, "TENANT_DECLARATION_MISSING", evidence)
    if len(declarations) > 1:
        return _lock(key, None, PENDING, "TENANT_DECLARATION_CONFLICT", evidence)
    tenant = declarations[0]
    if not credential:
        return _lock(key, tenant, PENDING, "TENANT_CREDENTIAL_MISSING", evidence)
    # 声明优先：档案不一致不改变锁定对象，只留证。
    mismatch = bool(archive) and set(archive) != {tenant}
    evidence["archive_mismatch"] = mismatch
    reason = "TENANT_DECLARED_ARCHIVE_CONFLICT" if mismatch else "TENANT_DECLARED"
    return _lock(key, tenant, LOCKED, reason, evidence)


def legacy_lock(row):
    return _lock(access_key(row), None, LEGACY, "TENANT_SINGLE_TENANT", {"access_key": access_key(row)})


def _lock(key, tenant, status, reason, evidence):
    return {"access_key": key, "tenant": tenant, "status": status, "reason": reason, "evidence": evidence}


def attach(row, parameters=None, mode=None, stored=None):
    """把锁挂到记录上，并展开为便于工作台展示的标量字段。

    stored 为归属登记表中已存在的权威锁；只要存在就只认它。
    """
    if mode is None:
        mode = tenant_mode([row], parameters)
    if stored is not None:
        lock = {**stored}
    else:
        lock = resolve(row, parameters) if mode else legacy_lock(row)
    return {**row, "tenant_lock": lock, "tenant": lock["tenant"], "tenant_status": lock["status"], "tenant_reason": lock["reason"]}


def pending(lock):
    return lock is not None and lock.get("status") == PENDING


def grant_applies(lock, grant):
    """授权必须与锁同租户。单租户模式只接受未限定租户的授权。"""
    grant_tenant = (grant.get("tenant") or "").strip() or None
    if lock is None or lock.get("status") == LEGACY:
        return grant_tenant is None
    return lock.get("status") == LOCKED and grant_tenant == lock.get("tenant")


def reject_pending(row, detail=None):
    lock = row.get("tenant_lock") or {}
    code = lock.get("reason") or "TENANT_PENDING"
    return reject(row, code, detail or PENDING_REASONS.get(code, "租户归属待核"))


def fingerprint(locks):
    """锁集合的稳定指纹，用于判断重跑结果是否变化。"""
    items = sorted(
        (lock["access_key"], lock.get("tenant") or "", lock.get("status") or "", int(lock.get("version") or 0))
        for lock in locks
    )
    return hashlib.sha256("|".join("\x1e".join(map(str, item)) for item in items).encode("utf-8")).hexdigest()
