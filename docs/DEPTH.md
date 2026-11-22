# 深度登记 数据共享授权到期与分区访问复核

规模：中型。使用者：企业数据共享审计专员。核心规则：拒绝规则优先于允许，授权必须同时命中资源、分区和生效窗；显式拒绝不得被宽授权覆盖。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 访问采信 | 查看并运行访问采信 | `/api/accesses` | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py` |
| M2 资源映射 | 查看并运行资源映射 | `/api/resources` | `app/modules/m2_resources/rules.py` | `tests/test_m2.py` |
| M3 授权定版 | 查看并运行授权定版 | `/api/grants` | `app/modules/m3_grants/rules.py` | `tests/test_m3.py` |
| M4 冲突裁决 | 查看并运行冲突裁决 | `/api/conflicts` | `app/modules/m4_conflicts/rules.py` | `tests/test_m4.py` |
| M5 分区判定 | 查看并运行分区判定 | `/api/partitions` | `app/modules/m5_partitions/rules.py` | `tests/test_m5.py` |
| M6 访问对账 | 查看并运行访问对账 | `/api/audit` | `app/modules/m6_audit/rules.py` | `tests/test_m6.py` |
| M7 审计归档 | 查看并运行审计归档 | `/api/seals` | `app/modules/m7_seals/rules.py` | `tests/test_m7.py` |
| M8 租户归属 | 查看、筛选并切换访问归属锁 | `/api/tenants/locks` | `app/tenants.py`、`app/locks.py`、`app/store.py` | `tests/test_tenants.py` |

## 租户归属锁定

多租户共用同名资源与分区时，资源名和分区不能证明同租户。每条访问在资源映射之后、
授权复核之前锁定一个租户归属；M3 授权复核、M6 差异核对和 M7 封存都只读这个锁。

- **裁决：声明优先。** 带凭据的上游租户声明当天即可锁定，不因档案未核齐而阻塞共享。
  档案只作对照证据：不一致时锁不变，记 `TENANT_DECLARED_ARCHIVE_CONFLICT`、
  `evidence.archive_mismatch=true`，且该访问只能用声明租户名下的授权，
  档案中另一租户的宽授权不得借用。
- **凭据缺失先待核。** 无声明、声明互相冲突、有声明无凭据三种情况分别记为
  `TENANT_DECLARATION_MISSING`、`TENANT_DECLARATION_CONFLICT`、
  `TENANT_CREDENTIAL_MISSING`，停在 M3 隔离队列，不进入授权复核，也不封存。
- **只认锁。** 授权必须 `grant.tenant` 与锁的租户一致；单租户口径只接受未限定租户的授权。
  M6 按租户分别给出预期/申报合计与差异数，不允许跨租户抵消。
- **重跑幂等。** 锁以“事件号+内容摘要”为键：同一记录重跑命中同一把锁，不新增重复归属；
  锁指纹进入批次身份，归属一变即产生新批次。
- **切换安全。** 归属切换需要显式调用并带版本号；版本不符返回 409，
  上一版与首次登记的 `original_archive` 原样保留，历史表逐版可查。
  重跑不会把已锁归属改回声明值，只在 `tenant_proposal` 中提示待显式切换。
  待核记录不能直接切换，必须先补凭据。


## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码 | 默认解码失败 | 回退GB18030 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_legacy_encoding_real_sample` |
| TRAP-02 | BOM | 首列名多字符 | utf-8-sig | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_bom_real_sample` |
| TRAP-03 | 带引号换行 | 拆成两条 | csv逻辑行 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_quoted_newline_is_one_record` |
| TRAP-05 | 列数不匹配 | 静默错列 | 隔离原行 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_bad_columns_real_sample` |
| TRAP-08 | 前导零ID | 编码变形 | 全程字符串 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_identifier_preserved_real_sample` |
| TRAP-14 | 重复键冲突 | 后写覆盖 | 保留首条并隔离冲突行 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_duplicate_conflict_real_sample` |
| TRAP-18 | 空态三态 | 一律成功 | 分别错误码 | `app/modules/m1_accesses/rules.py` | `tests/test_m1.py::test_three_empty_states` |
| TRAP-26 | 旧版本提交 | 覆盖新结果 | 版本条件更新 | `app/store.py` | `tests/test_e2e.py::test_stale_review_409` |
| TRAP-07 | 上游结果空值 | 误报拒绝 | 隔离缺失 | `app/values.py` | `tests/test_m3.py::test_real_missing_decision_not_zero` |
| TRAP-19 | 允许与拒绝重叠 | 后写覆盖 | 拒绝优先且排序证据 | `app/modules/m4_conflicts/rules.py` | `tests/test_m4.py::test_deny_priority_counterexample` |
| TRAP-23 | 授权到期点 | 多放行一次 | 半开生效窗 | `app/modules/m3_grants/rules.py` | `tests/test_m3.py::test_expiry_endpoint_excluded` |
| TRAP-27 | 多租户同名资源 | 共用资源就当同租户，把B授权记到A名下 | 先锁租户，授权只认锁 | `app/tenants.py`、`app/modules/m3_grants/rules.py` | `tests/test_tenants.py::test_shared_resource_is_judged_per_tenant` |
| TRAP-28 | 档案未核齐 | 等档案一致才处理，拖住共享 | 声明优先锁定并留证，档案仅对照 | `app/tenants.py` | `tests/test_tenants.py::test_archive_mismatch_keeps_declaration_and_marks_evidence` |
| TRAP-29 | 声明有但凭据缺失 | 照声明放行 | 停在待核，不进授权复核 | `app/modules/m3_grants/rules.py` | `tests/test_tenants.py::test_missing_credential_waits_for_review` |
| TRAP-30 | 重跑归因重复 | 每次重跑新增一条归属 | 记录指纹为键，幂等登记 | `app/store.py` | `tests/test_tenants.py::test_rerun_does_not_add_duplicate_locks` |
| TRAP-31 | 归属切换失败 | 半途覆盖丢掉旧版与档案 | 版本条件更新，失败保留上一版 | `app/store.py` | `tests/test_tenants.py::test_failed_switch_preserves_previous_version_and_archive` |

## 对账规则

输入原始逻辑行=最终采纳来源行+隔离来源行+重复行+空白行+分段表头。派生记录用_sources保存完整来源，因此分组不丢行。业务预期合计与上游申报合计之差等于逐行差异之和。结果按输入摘要、规则版本及参数产生唯一批次，事务写入；同源重跑只复用已有批次。

## 已知不覆盖

4MB以上文件需预先按业务键分批；不模拟生产支付与外部回调。人工复核只变更批次状态，不改写原始记录。
