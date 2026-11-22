# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 租户归属

- `GET /api/tenants/locks`：列出归属登记，`?status=待核` 可筛选；返回 locked/pending/legacy/archive_mismatch 汇总。
- `GET /api/tenants/locks/<access_key>`：单条归属、证据与版本历史。
- `POST /api/tenants/locks/<access_key>/switch`：显式切换，body 需 `version` 与 `tenant`；版本不符、目标与现状相同、记录仍在待核均返回 409；失败保留上一版与原档案。

`access_key` 形如 `T001|<16位十六进制>`，在路径中直接作为一段传递，不做 `%2F` 转义（其中不含斜杠）。`/api/runs` 的 `parameters` 支持 `tenant_declarations`、`tenant_archive` 与带 `tenant` 的 `grants`。`sample=tenants.csv` 自带上述场景参数。
