from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app import store
def register_pages(app):
    def page(index):
        run=store.latest() or execute(load_sample("dirty.csv"))
        stage=run["stages"][index]
        rows=stage["rows"]
        columns=[['event_id','tenant','tenant_status','principal', 'resource', 'partition', 'access_time', 'observed'], ['event_id','tenant','tenant_status','principal', 'resource', 'partition'], ['event_id','tenant','tenant_status','principal', 'resource', 'partition', 'at', 'candidate_count'], ['event_id','tenant','tenant_status','principal', 'partition', 'rule_evidence', 'effect', 'conflict'], ['event_id','tenant','tenant_status','principal', 'resource', 'partition', 'effect', 'observed', 'partition_result', 'violation'], ['event_id','tenant','tenant_status','principal', 'expected', 'reported', 'difference', 'violation', 'status'], ['event_id','tenant','tenant_status','principal', 'resource', 'partition', 'rule_evidence', 'violation', 'status']][index]
        labels={'event_id': '事件号', 'tenant': '租户', 'tenant_status': '归属状态', 'principal': '主体', 'resource': '资源', 'partition': '分区', 'access_time': '访问时刻', 'observed': '执行结果', 'at': '事件 UTC', 'candidate_count': '生效授权数', 'rule_evidence': '命中规则', 'effect': '授权裁决', 'conflict': '规则冲突', 'partition_result': '分区裁决', 'violation': '执行差异', 'expected': '应允许', 'reported': '实允许', 'difference': '差异', 'status': '结论', 'resources': '资源数', 'accepted': '采纳行', 'active_hits': '生效命中', 'grant_versions': '授权数', 'conflicts': '冲突行', 'explicit_denies': '显式拒绝', 'default_denies': '默认拒绝', 'allowed': '应放行', 'blocked': '应拒绝', 'violations': '越权放行', 'false_blocks': '误拦截', 'records': '封存数', 'source_lines': '来源行', 'sha256': '摘要', 'ready': '可封存', 'differences': '差异数'}
        for key,label in {'accepted_inputs': '采纳来源行', 'quarantine_inputs': '隔离来源行', 'output_records': '结果记录', 'input': '输入行', 'excluded': '排除行', 'balanced': '行数平衡', 'expected_total': '预期合计', 'reported_total': '申报合计', 'differences': '差异项', 'blank': '空行', 'repeated_headers': '分段表头', 'encoding': '编码', 'duplicate': '重复行', 'quarantine': '隔离行', 'accepted': '采纳行', 'sha256': '校验摘要', 'ready': '可归档', 'tenants': '租户数', 'tenant_pending': '归属待核', 'locked': '已锁定', 'pending': '待核', 'legacy': '单租户口径', 'archive_mismatch': '档案不一致', 'lock_fingerprint': '归属指纹'}.items(): labels.setdefault(key,label)
        lock_view=stage["metrics"].get('by_tenant') or run['stages'][1]["metrics"].get('by_tenant') or {}
        tenant_rows=[row for row in run['stages'][1]["rows"] if row.get('tenant_status')]
        lock_summary={'locked':run['stages'][1]["metrics"].get('locked',0),'pending':run['stages'][1]["metrics"].get('pending',0),'legacy':run['stages'][1]["metrics"].get('legacy',0),'archive_mismatch':run['stages'][1]["metrics"].get('archive_mismatch',0)}
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=rows,columns=columns[:12],history=store.history(),labels=labels,lock_summary=lock_summary,tenant_rows=tenant_rows,lock_view=lock_view)
    app.add_url_rule("/",view_func=lambda:page(4))
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))
