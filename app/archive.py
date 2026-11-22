import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","tenant","tenant_status","lock_version","evidence"])
    meta=run["manifest"]
    for row in run["stages"][-1]["rows"]:
        lock=row.get("tenant_lock") or {}
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),lock.get("tenant") or "",lock.get("status") or "",lock.get("version") or "",json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        lock=row.get("tenant_lock") or {}
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),lock.get("tenant") or "",lock.get("status") or "",lock.get("version") or "",json.dumps(row,ensure_ascii=False)])
    return "\ufeff"+stream.getvalue()
