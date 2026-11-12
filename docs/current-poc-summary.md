# 当前 POC 总结与阶段方案

## 1. 文档目的

本文只整理已经在腾讯云 TKE 实际实现或验证过的内容，重点回答两个问题：

1. Jupyter Server、Terminal、Kernel 应如何拆 Pod，才能隔离平台密钥与用户代码。
2. Notebook 如何保持原生数据库驱动体验，同时通过开源代理获得连接治理、路由和审计能力。

Enterprise Gateway 尚未部署，不计入本文的已通过能力；包含 EG 的生产候选架构见
[`target-architecture.md`](target-architecture.md)。

## 2. 当前环境与范围

- 集群：腾讯云 TKE `cls-56b8021o`
- API Server：内网 `10.0.0.8`
- namespace：`jupyter-poc`
- 数据源：POC 内临时 PostgreSQL、MySQL、MongoDB、Elasticsearch
- 数据代理：PgBouncer、ProxySQL、HAProxy、Nginx
- 身份：mock OIDC + JupyterHub
- 观测：JupyterLab UEM 扩展、Jupyter Server 扩展、mock UEM Collector

所有密码均为公开 mock 值，不能复制到生产环境。完整集群记录见
[`cluster-profile.md`](cluster-profile.md)。

## 3. POC 总览

| 验证项 | 结果 | 结论 |
| --- | --- | --- |
| Jupyter Server 与 Kernel 分 Pod | 通过 | `KubernetesProvisioner` 可创建、管理独立 Kernel Pod |
| Workspace Pod | 通过 | 单用户 Server、Terminal、Kernel 可在同一无平台密钥 Workspace 中运行 |
| Workspace RBAC/密钥隔离 | 通过 | 无 K8s token，不能读 Pod/Secret，无 OIDC/Hub/UEM 平台密钥 |
| PostgreSQL 原生代理 | 通过 | psycopg → PgBouncer → PostgreSQL |
| MySQL 原生代理 | 通过 | PyMySQL → ProxySQL → MySQL |
| MongoDB 透明代理 | 通过 | PyMongo → HAProxy → MongoDB |
| Elasticsearch 透明代理 | 通过 | Elasticsearch SDK → Nginx → Elasticsearch |
| ProxySQL 查询事件 | 通过 | 产生 digest 和 JSON event；原始 SQL 日志仅限 POC |
| UEM 浏览器事件 | 通过 | Lab 扩展产生 `lab_ready`，敏感字段校验生效 |
| Mock OIDC 登录 | 通过 | Authorization Code 到 JupyterHub 登录闭环 |
| Kernel/Workspace default-deny | **失败** | TKE Serverless 接收 NetworkPolicy 对象但没有数据面执行器 |
| 生产 DB 最小权限/动态凭证 | 未验证 | 当前 mock DB 用户权限和密码不代表生产授权方案 |
| Enterprise Gateway | 未验证 | 已完成调研和验收设计，尚未部署 |

实测证据与失败项见 [`validation-report.md`](validation-report.md)。

## 4. Pod 分离：两条已跑通路线

### 4.1 路线 A：Jupyter Server + 独立 Kernel Pod

```text
Browser
  │
  ▼
Jupyter Server Pod
  │ KubernetesProvisioner
  ▼
Kernel Pod（每 Kernel 一个 Pod）
```

#### 优点

- Kernel 有独立 CPU、内存、GPU、镜像、ServiceAccount 和网络边界。
- Notebook 中 Python、`!bash`、`subprocess` 均在 Kernel Pod 执行。
- 不需要长期运行的 Enterprise Gateway。
- JupyterLab 继续使用原生 Sessions/Kernels API。

#### 已发现的边界

- Jupyter Server 必须持有创建/删除 Kernel Pod 的 Kubernetes RBAC。
- Jupyter 原生 Terminal 仍在 Server Pod，不会跟随 Kernel Provisioner。
- 如果 Server 持有平台密钥，就必须禁用 Terminal、本地 Kernel 和其他本地代码执行入口。
- Kernel 状态依赖 Server 内的 KernelManager；Server HA、重连和孤儿回收需要额外设计。

适合：只面向 Kubernetes、希望组件少、需要每 Kernel 独立资源，但可以禁用或另行实现 Terminal 的场景。

### 4.2 路线 B：KubeSpawner Workspace Pod

```text
JupyterHub（可信控制面）
  │ KubeSpawner
  ▼
Workspace Pod（不可信用户执行面）
├── single-user Jupyter Server / Lab
├── 原生 Terminal
└── 一个或多个本地 Kernel
```

#### 优点

- Jupyter 原生 Terminal、Kernel、用户依赖和文件系统天然一致。
- 不需要自研远程 TerminalManager。
- OIDC client secret、Hub 管理 token 和 Kubernetes 创建权限留在 Hub。
- Workspace 不挂载 Kubernetes ServiceAccount token，用户代码无法读取平台密钥。

#### 实测结果

```text
WORKSPACE_KERNEL_OK:workspace-poc-user:jovyan
WORKSPACE_TERMINAL_OK:workspace-poc-user:jovyan
```

Kernel 和 Terminal 均运行在 `workspace-poc-user`。Workspace ServiceAccount 不能读取
Pod 或 Secret，也没有 `OAUTH_CLIENT_SECRET`、`HUB_ADMIN_TOKEN`、
`UEM_COLLECTOR_TOKEN`。

#### 边界

- 单用户 Jupyter Server 也属于用户信任域，不能注入平台共享密钥。
- Terminal/Kernel 默认共享 Pod 资源和网络边界，不具备每 Kernel 独立 GPU/网络策略。
- 用户 Server token 对用户可见，应限制为当前用户/Workspace 能力。
- 系统插件需要数据库或外部服务密钥时，必须拆出可信 Backend。

适合：必须提供原生 Terminal，希望用户获得完整一致环境，且接受 Server/Kernel 同属一个不可信 Workspace 的场景。

## 5. DB Proxy POC

### 5.1 目标与已部署链路

用户继续使用 psycopg、PyMySQL、SQLAlchemy、pandas、PyMongo 和 Elasticsearch SDK，
不引入自定义 SQL HTTP API：

```text
Kernel + psycopg ─► PgBouncer:5432 ─► PostgreSQL
Kernel + PyMySQL ─► ProxySQL:6033  ─► MySQL
Kernel + PyMongo ─► HAProxy:27017  ─► MongoDB
Kernel + ES SDK  ─► Nginx:9200     ─► Elasticsearch
```

示例：

```python
psycopg.connect(host="postgres-proxy", port=5432, dbname="analytics", ...)
pymysql.connect(host="mysql-proxy", port=6033, database="analytics", ...)
```

四条链路均已从真实 Kernel Pod 返回 mock 数据，测试位于
[`../tests/native_proxy_smoke.py`](../tests/native_proxy_smoke.py)。

### 5.2 各代理的正确定位

| 代理 | 主要价值 | 不能替代 |
| --- | --- | --- |
| PgBouncer | PostgreSQL 连接池、连接数收敛 | SQL 防火墙、细粒度审计、身份网关 |
| ProxySQL | MySQL 连接池、路由、超时、query rules、digest | 数据库 RBAC、完整企业身份映射 |
| HAProxy | MongoDB wire protocol 的 L4 透明转发 | Mongo 查询解析和字段级策略 |
| Nginx | ES HTTP 连接复用、path/method/限流 | Elasticsearch DSL 语义授权 |

授权仍应由数据库 role、schema/table privilege、RLS、resource group 和数据库审计承担。

### 5.3 用户查询与系统插件写库必须分流

#### 用户原生数据库体验

```text
Kernel
  │ 用户/Workspace 受限短期凭证
  ▼
PgBouncer / ProxySQL
  │
  ▼
用户授权范围内的数据库角色
```

Kernel 中的凭证应视为用户可见，因此只能是短期、最小权限、可撤销凭证。数据库只
允许代理源地址，Kernel 直连真实数据库必须失败。

#### 系统插件写数据库

记录工号、Jupyter 使用习惯、作业状态等系统插件不能在 Workspace/Kernel 中持有
数据库密码：

```text
JupyterLab/Server 插件
  │ 事件或受限业务 API
  ▼
UEM Collector / Plugin Backend（可信 Pod）
  │ 插件专属数据库角色
  ▼
PgBouncer / ProxySQL
  ▼
系统数据库
```

Collector 从可信身份补充工号，忽略客户端自报 employee ID。浏览器行为事件可用于
产品分析，但可被用户阻断或伪造；登录、资源、计费和数据库访问等安全审计必须来自
IdP、Hub、Kubernetes、LLM Gateway、数据库代理或数据库自身。

### 5.4 凭证模型结论

PgBouncer/ProxySQL 不会自动把客户端身份转换成完全不同的后端身份。生产候选顺序：

1. 用户级受限数据库角色 + 网络不可绕过。
2. 每用户/Kernel 短期数据库凭证。
3. mTLS/SPIFFE/数据库认证插件进行工作负载身份映射。
4. 若要求 Kernel 完全不知道任何数据库认证秘密，采用支持前后端身份映射的企业数据网关。

## 6. 当前最大阻塞：网络策略没有执行

当前 TKE Serverless `eklet` 环境中：

- `NetworkPolicy` 对象创建成功；
- Kernel 和 Workspace 仍可直连 mock 数据库、Kubernetes API；
- 集群未发现 Calico、Cilium、Antrea 或腾讯云 `networkpolicy` 执行组件。

因此当前只验证了应用链路和 Kubernetes RBAC，没有验证生产所需的出网隔离。公司环境
必须使用可执行 NetworkPolicy 的 CNI、Pod 安全组、独立子网 ACL 或 egress gateway，
并以 Pod 内真实 TCP 测试作为验收依据。

## 7. 当前阶段可复用结论

1. Pod 是平台密钥与用户代码之间更合适的安全边界；同 Pod 不同环境变量不是安全边界。
2. 任何进入 Workspace/Kernel 的秘密都应假设用户可以取得。
3. 原生 Terminal 与“可信 Jupyter Server”目标存在冲突：要么 Server 属于无平台密钥的 Workspace，要么禁用本地 Terminal。
4. 用户 SQL 与系统插件写库是两类不同信任链路，不能共享高权限数据库账号。
5. 开源 DB Proxy 能保持原生体验并提供池化/路由，但不能单独完成身份、授权、审计和防绕过。
6. Kubernetes 接受安全对象不代表数据面生效，必须做负向连通性验证。

## 8. 尚未完成的生产能力

- Enterprise Gateway 实际部署、可信身份绑定和故障恢复。
- 可执行的 Kernel/Workspace 出网隔离。
- 真实数据库最小权限 role、短期凭证和直连阻断。
- ProxySQL/PgBouncer HA、TLS/mTLS、监控用户和配置持久化。
- PVC、Hub 数据库、Notebook 备份与删除策略。
- 内部预构建镜像、digest、SBOM、签名和漏洞准入。
- UEM Collector 持久数据库、消息缓冲、去重、保留期和 Huawei UEM 对接。

