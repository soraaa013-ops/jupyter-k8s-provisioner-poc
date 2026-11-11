# 公司内部落地指南

本文区分“已经验证的机制”“POC mock”和“公司环境必须补齐的能力”，避免把演示配置直接当作生产设计。

## 组件归属

| 组件 | 本项目负责 | 公司平台/基础设施需提供 |
| --- | --- | --- |
| JupyterHub/Server | 扩展、配置、用户 Server 生命周期接口 | 域名、Ingress、TLS、内部镜像仓库、持久化 |
| Kernel Provisioner | Kernel Pod 模板、资源/安全约束、销毁 | 可用节点池、CNI/Pod 出口控制、配额 |
| SSO | OIDC/OAuth 对接逻辑、claim/role 映射 | IdP client、issuer/JWKS、用户组、登出规范 |
| UEM | Lab 采集、Server 转发、schema、脱敏 | Huawei UEM 协议、应用 ID、合规与保留期 |
| Data Gateway | API、策略、审计字段、数据库适配器 | 真实数据库、动态凭证系统、审计平台、HA |

## POC 中必须替换的内容

- `src/mock-oidc` 只能测试协议，必须替换为公司 IdP。
- `deploy/platform-poc/mock-data.yaml` 的四个后端是临时数据源，不进入生产。
- `mock-database-credentials` 全是公开演示值，生产使用 Vault/KMS/Secret Manager 和轮换机制。
- 运行时 `pip install` 必须改为公司仓库中固定 digest 的预构建镜像。
- Jupyter token `poc-only-change-me` 必须删除，由 Hub/OIDC 管理认证。
- Data Gateway 当前是单副本、内存状态和 HTTP API；生产需要 HA、TLS/mTLS、持久审计和限流。
- PostgreSQL/MySQL 原生驱动兼容若为硬要求，需要协议代理或公司数据访问网关；当前统一 HTTP API 不等价于透明 wire-protocol proxy。

## 建议部署顺序

### 1. 基础能力确认

向 Kubernetes/网络团队取得：集群版本、节点类型、CNI、NetworkPolicy 执行器、Pod 出口控制方式、DNS、Service/Pod CIDR、内部镜像仓库和 Secret 方案。

不要只执行 `kubectl apply networkpolicy`；先确认存在执行器，例如 Calico/Cilium/Antrea 或云厂商组件，并运行真实连通性测试。

### 2. 身份先行

注册 OIDC client，确定 `issuer`、callback、scopes、稳定用户 ID、groups claim、管理员组和退出策略。先让 Hub 得到可信身份，再把同一 subject 传给 UEM 与 Data Gateway。

### 3. UEM 对接

冻结事件 schema 和禁止字段，先接 mock collector，再实现 Huawei exporter。浏览器只发行为事件；Server 使用当前登录用户覆盖客户端身份，负责签名、脱敏、限流和失败降级。

### 4. 数据访问

Kernel 只获得短期 Gateway token，不获得数据库密码。Gateway 根据用户、工作区和 Kernel 映射策略与数据库角色；数据库凭证由 workload identity 或动态凭证系统获取。

### 5. Kernel 出口

允许 DNS、Jupyter 控制面必要通信和 Gateway；拒绝 Kubernetes API、云元数据、公网、真实数据库地址及其他内部网段。实现手段可以是 NetworkPolicy、Pod 安全组或公司的 egress gateway，项目只依赖最终行为，不绑定某个网络产品。

## 必须通过的验收门

| 类别 | 正向 | 负向 |
| --- | --- | --- |
| Kernel 生命周期 | 创建、执行、中断、重启、删除 | Server 重启后孤儿回收、超时清理 |
| SSO | 合法用户/组登录 | 未登录、伪造 claim、禁用用户、非授权组拒绝 |
| UEM | ready/kernel/cell/error 可查询 | 源码、输出、SQL、token、明文账号不出现 |
| Data Gateway | 授权只读查询成功 | DDL、多语句、越权 schema、过期 token 拒绝 |
| 网络 | Kernel 能到 Gateway | 不能到 DB、API Server、metadata、公网和非白名单服务 |
| 凭证 | Gateway 能动态取凭证 | Kernel 文件、env、`/proc`、Notebook 中找不到 DB 密码 |
| 审计 | user/workspace/kernel/trace 可关联 | 日志不保存密码和默认禁止的原始 SQL |

验收必须从真实 Kernel Pod 内执行，而不是只检查 YAML 或控制台状态。

## 进入生产前的决策

1. 单用户 Server 是否由 JupyterHub/KubeSpawner创建，还是公司平台自有控制器创建。
2. Kernel 的工作目录、Notebook 文件和用户包如何持久化。
3. Data Gateway 是平台共享、租户独立还是用户独立。
4. PostgreSQL/MySQL 是否要求原生协议；Mongo/ES 是否只允许受限 API。
5. UEM 与安全审计的 schema、保留期、查询权限和告警责任人。
6. Kernel 镜像准入、依赖安装、GPU、资源配额与空闲回收策略。
