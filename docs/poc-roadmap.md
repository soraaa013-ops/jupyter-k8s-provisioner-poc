# POC 路线与决策门

## 建议顺序

1. 固化多 Pod 实验：把运行时安装改为锁版本镜像，补自动冒烟和网络负向测试。
2. SSO：身份是 UEM 与 SQL 授权的上游，先得到稳定 user/group。
3. UEM：用 mock collector 验证通用扩展，再接 `HuaweiUemExporter`。
4. SQL Proxy：以 PostgreSQL 完成身份映射、网络隔离和审计闭环。
5. 故障与规模：验证 Hub/Server/Kernel/Proxy 重启、扩缩容和升级。

## 每项必须交付

- 背景、非目标、架构图、信任边界、ADR。
- 可复现 manifests/镜像/配置，依赖锁版本。
- happy path、越权/绕过测试、故障注入结果。
- 凭证清单、网络矩阵、日志/指标/审计字段。
- 从 POC 到生产的缺口、成本与明确决策。

## 需要公司内部输入

- Huawei UEM 接入规范、合规字段与测试 endpoint。
- 企业 OIDC/OAuth discovery、client 注册流程、claims/groups 样例。
- SQL POC 数据库协议、测试库、允许操作与审计要求。

真实密钥只进入外部 Secret 系统或临时 Kubernetes Secret，不提交 Git。
