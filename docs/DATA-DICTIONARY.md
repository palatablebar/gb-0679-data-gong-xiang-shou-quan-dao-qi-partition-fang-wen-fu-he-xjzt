# 授权定义

资源orders与订单等价，customers与客户等价。principal为主体文本，不支持模糊主体。partition为YYYY-MM；分区授权[start,end)不含end月。授权时间也为[start,end)，到期时刻立即失效。

每条授权包含主体、资源、生效窗、分区窗和allow/deny。全部条件必须同时匹配。拒绝优先，多个允许不能覆盖任何显式拒绝；无匹配默认拒绝。匹配规则ID按字典序稳定排序，冲突显示全部允许与拒绝证据。

observed为真实访问执行结果allowed或blocked；reported为上游0/1判定，留作证据。expected为实际授权复算，分区模块重建reported为执行结果便于二值对账。越权放行和误拦截分别计数，禁止用相互抵消的总数代替逐条核查。

业务ID和超大整数按文本保形；Decimal参与数量金额计算，对外序列化为字符串。哨兵集合定义在app/values.py，缺失值不能当零。所有时间带UTC偏移，先转UTC比较，业务日按指定地区划分。区间统一[start,end)。重复业务键保留第一条、完全相同行计重复；值冲突行隔离且保留原值。空文件、全空白、仅表头分开拒绝。

运行清单包括输入sha256、规则版本、参数、生成时刻与耗时。源行编号以CSV解析器的物理结束行号表示，引号内换行不增加记录数。输入超过4MB返回413，非法表头和类型返回422，失效版本复核返回409。

## 租户列与归属定义

基础8列固定；其后可追加两个可选列，顺序固定：`tenant`、`tenant_credential`。追加列不改变旧文件的表头校验。

- `tenant`：上游租户声明。同一事件号下不同租户是各自独立的访问，不是重复记录。
- `tenant_credential`：声明凭据。有声明无凭据的记录停在待核，不得进入授权复核。
- 归属锁状态：`声明锁定`、`待核`、`单租户`（未启用租户模型的批次）。
- 待核原因：`TENANT_DECLARATION_MISSING`、`TENANT_CREDENTIAL_MISSING`、`TENANT_DECLARATION_CONFLICT`。
- 声明与档案不一致：`TENANT_DECLARED_ARCHIVE_CONFLICT`，锁仍按声明，`evidence.archive_mismatch=true`。
- 场景参数（`/api/runs` 的 `parameters`）：`grants` 可带 `tenant`；`tenant_declarations` 为 `[{event_id,tenant,credential}]`；`tenant_archive` 为 `[{event_id|principal,resource,partition,tenant}]`，仅作对照。