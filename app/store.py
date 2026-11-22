import sqlite3,json
from datetime import datetime,timezone
from pathlib import Path
from app.config import DATA_DIR
from app.errors import DomainError
def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS tenant_locks (access_key TEXT PRIMARY KEY,tenant TEXT,status TEXT NOT NULL,reason TEXT,version INTEGER NOT NULL DEFAULT 1,evidence TEXT NOT NULL,original_archive TEXT,updated_at TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS tenant_lock_history (id INTEGER PRIMARY KEY AUTOINCREMENT,access_key TEXT NOT NULL,version INTEGER NOT NULL,tenant TEXT,status TEXT NOT NULL,reason TEXT,evidence TEXT,original_archive TEXT,changed_at TEXT NOT NULL)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS tenant_lock_history_version ON tenant_lock_history(access_key,version)")
    return db
def save(run_id,payload):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,json.dumps(payload,ensure_ascii=False)))
    return get(run_id)
def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}
def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None
def history():
    with connect() as db: return [{"run_id":i,"version":v,"decision":d} for i,v,d in db.execute("SELECT id,version,decision FROM runs ORDER BY rowid DESC")]
def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)

# ---------- 租户归属登记 ----------
_LOCK_COLUMNS="access_key,tenant,status,reason,version,evidence,original_archive"
def _now(): return datetime.now(timezone.utc).isoformat()
def _row_to_lock(row):
    if not row: return None
    return {"access_key":row[0],"tenant":row[1],"status":row[2],"reason":row[3],"version":row[4],"evidence":json.loads(row[5]),"original_archive":json.loads(row[6]) if row[6] else None}
def _record(db,lock,changed):
    db.execute("INSERT INTO tenant_lock_history(access_key,version,tenant,status,reason,evidence,original_archive,changed_at) VALUES (?,?,?,?,?,?,?,?)",
        (lock["access_key"],lock["version"],lock["tenant"],lock["status"],lock["reason"],json.dumps(lock["evidence"],ensure_ascii=False),json.dumps(lock.get("original_archive"),ensure_ascii=False) if lock.get("original_archive") is not None else None,_now()))
def get_lock(access_key):
    with connect() as db: return _row_to_lock(db.execute(f"SELECT {_LOCK_COLUMNS} FROM tenant_locks WHERE access_key=?",(access_key,)).fetchone())
def lock_map(access_keys):
    keys=list(dict.fromkeys(access_keys))
    if not keys: return {}
    with connect() as db:
        marks=",".join("?"*len(keys))
        found={}
        for raw in db.execute(f"SELECT {_LOCK_COLUMNS} FROM tenant_locks WHERE access_key IN ({marks})",keys):
            lock=_row_to_lock(raw)
            if lock: found[lock["access_key"]]=lock
        return found
def register_locks(computed):
    """把当次计算出的锁写进登记表，幂等。

    - 新记录：以当次计算结果建锁，original_archive 同时快照，version=1。
    - 已存在且为“声明锁定”：重跑不改写，沿用上一版归属（可能需要显式切换）。
    - 已存在且为“待核”：仅在当次已能锁定时补锁升级；仍待核则不重复登记。
    - original_archive 只在首次登记时写入，此后任何路径都不覆盖。
    """
    result=[]
    with connect() as db:
        for lock in computed:
            current=_row_to_lock(db.execute(f"SELECT {_LOCK_COLUMNS} FROM tenant_locks WHERE access_key=?",(lock["access_key"],)).fetchone())
            archive=list((lock.get("evidence") or {}).get("archive_tenants") or [])
            if current is None:
                stored={**lock,"version":1,"original_archive":archive}
                db.execute("INSERT INTO tenant_locks(access_key,tenant,status,reason,version,evidence,original_archive,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (stored["access_key"],stored["tenant"],stored["status"],stored["reason"],1,json.dumps(stored["evidence"],ensure_ascii=False),json.dumps(archive,ensure_ascii=False),_now()))
                _record(db,stored,True);result.append(stored);continue
            if current["status"]=="待核" and lock["status"]=="声明锁定":
                stored={**lock,"version":current["version"]+1,"original_archive":current["original_archive"]}
                db.execute("UPDATE tenant_locks SET tenant=?,status=?,reason=?,version=?,evidence=?,updated_at=? WHERE access_key=? AND version=?",
                    (stored["tenant"],stored["status"],stored["reason"],stored["version"],json.dumps(stored["evidence"],ensure_ascii=False),_now(),stored["access_key"],current["version"]))
                _record(db,stored,True);result.append(stored);continue
            # 其余情况保留上一版：重跑不新增、不覆盖。
            result.append(current)
    return result
def switch_lock(access_key,version,tenant,reason="TENANT_EXPLICIT_SWITCH"):
    """显式切换归属。带版本条件，失败时上一版与原档案原样保留。"""
    if not (tenant or "").strip(): raise DomainError("BAD_TENANT","租户不能为空")
    with connect() as db:
        current=_row_to_lock(db.execute(f"SELECT {_LOCK_COLUMNS} FROM tenant_locks WHERE access_key=?",(access_key,)).fetchone())
        if current is None: raise DomainError("NOT_FOUND","归属记录不存在",404)
        if current["version"]!=version: raise DomainError("STALE_LOCK","归属版本已更新，请刷新",409)
        if current["status"]=="待核": raise DomainError("LOCK_PENDING","凭据缺失的记录不能切换归属",409)
        if current["tenant"]==tenant.strip(): raise DomainError("LOCK_UNCHANGED","归属已是该租户，无需切换",409)
        evidence={**(current.get("evidence") or {}),"switched_from":current.get("tenant"),"switch_reason":reason}
        next_lock={"access_key":access_key,"tenant":tenant.strip(),"status":"声明锁定","reason":reason,"version":current["version"]+1,
            "evidence":evidence,"original_archive":current.get("original_archive")}
        cursor=db.execute("UPDATE tenant_locks SET tenant=?,status=?,reason=?,version=?,evidence=?,updated_at=? WHERE access_key=? AND version=?",
            (next_lock["tenant"],next_lock["status"],next_lock["reason"],next_lock["version"],json.dumps(evidence,ensure_ascii=False),_now(),access_key,version))
        if cursor.rowcount!=1: raise DomainError("STALE_LOCK","归属版本已更新，请刷新",409)
        _record(db,next_lock,True)
    return next_lock
def lock_history(access_key):
    with connect() as db:
        rows=db.execute("SELECT version,tenant,status,reason,changed_at FROM tenant_lock_history WHERE access_key=? ORDER BY version",(access_key,)).fetchall()
    return [{"version":v,"tenant":t,"status":s,"reason":r,"changed_at":c} for v,t,s,r,c in rows]
def locks_all():
    with connect() as db: return [_row_to_lock(r) for r in db.execute(f"SELECT {_LOCK_COLUMNS} FROM tenant_locks ORDER BY access_key")]
