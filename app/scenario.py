"""仓内多租户样例的场景参数。

同名资源 orders/2026-10 被 A、B 两个租户共用：
- A 的授权在访问当天已失效（默认拒绝）。
- B 的授权仍有效。
归属锁按上游声明锁定，因此同一资源、同一分区在两条记录上得到不同授权结论；
档案只作对照，不一致时留证但不改写锁，也不允许借用档案里另一租户的授权。
"""
TENANT_GRANTS=[
    {"id":"GA-01","tenant":"A","principal":"analyst","resource":"orders","start":"2026-11-01T00:00:00Z","end":"2026-11-10T00:00:00Z","from_partition":"2026-01","to_partition":"2026-12","effect":"allow"},
    {"id":"GB-01","tenant":"B","principal":"analyst","resource":"orders","start":"2026-11-01T00:00:00Z","end":"2026-12-01T00:00:00Z","from_partition":"2026-01","to_partition":"2026-12","effect":"allow"},
]
# T003 在 CSV 内联声明之外再收到一份不同租户的声明，构成声明冲突。
TENANT_DECLARATIONS=[{"event_id":"T003","tenant":"A","credential":"cred-a-003"}]
# 档案只作对照：T006 与声明一致；T008 档案记在 A 名下而声明为 B（不得借用 A 的授权）。
TENANT_ARCHIVE=[
    {"event_id":"T006","tenant":"A"},
    {"event_id":"T008","tenant":"A"},
]
SCENARIOS={"tenants.csv":{"grants":TENANT_GRANTS,"tenant_declarations":TENANT_DECLARATIONS,"tenant_archive":TENANT_ARCHIVE}}
def parameters_for(sample):
    return {key:value for key,value in (SCENARIOS.get(sample) or {}).items()}
