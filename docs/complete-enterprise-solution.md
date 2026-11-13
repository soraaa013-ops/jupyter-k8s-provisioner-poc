# Jupyter 企业平台完整方案

## 1. 方案结论

生产候选采用“可信控制面、轻量用户 Server、远程 Kernel、独立插件后端、原生数据库代理”五层架构：

```text
企业 IdP
   │ OIDC
   ▼
JupyterHub / Workspace Controller
   │ 创建 per-user Server
   ▼
Jupyter Server Pod（受控服务层）
├── JupyterLab / Contents / Sessions
├── 自研插件适配层
├── 显式禁用 Terminal
├── 无本地 Kernel
└── 仅持有短期、窄权限的服务凭证
        │
        ├──────────► UEM / Plugin / LLM Backend（可信服务）
        │
        ▼
EG Auth Proxy（身份绑定与 Kernel 策略）
        │
        ▼
Enterprise Gateway
        │ Kubernetes API
        ▼
Kernel Pod（不可信用户执行面）
├── Python / R / Spark / GPU
├── Notebook 中的 !bash / subprocess
├── 无平台密钥、无 Kubernetes token
└── 仅能访问批准的数据代理
        │
        ▼
PgBouncer / ProxySQL / HAProxy / Nginx
        │
        ▼
PostgreSQL / MySQL / MongoDB / Elasticsearch
```

核心决策如下：

1. Enterprise Gateway 负责远程 Kernel，不负责 Terminal。
2. Jupyter Server 可以持有凭证，但只能持有当前 Server 的短期、窄权限凭证，不能持有数据库密码、模型供应商 Key 或平台管理员 Token。
3. 需要高权限的插件拆成 Jupyter 插件适配层与独立可信 Backend，真实密钥只进入 Backend。
4. 用户数据库访问保持 psycopg、JDBC、SQLAlchemy、PyMySQL 等原生协议，通过开源代理治理连接。
5. 用户数据库访问和系统插件写库使用不同身份、不同代理 pool、不同数据库 role。
6. 网络默认拒绝；Kernel 只能到 Enterprise Gateway 必要链路、DNS 和批准的数据代理，不能直连真实数据库。

## 2. 安全目标与威胁模型

### 2.1 不可信主体

平台应假设用户可以：

- 控制浏览器请求和 Jupyter REST/WebSocket 调用；
- 在 Kernel 中执行任意 Python、shell、`subprocess` 和网络请求；
- 读取 Kernel 的环境变量、文件、`/proc` 和挂载；
- 尝试伪造工号、`KERNEL_USERNAME`、资源参数和插件请求；
- 尝试扫描 Kubernetes API、云元数据、其他租户和真实数据库。

任何进入 Kernel Pod 的秘密都应视为用户能够取得。

### 2.2 需要保护的资产

- OIDC client secret、Hub 管理 Token 和签名私钥；
- Enterprise Gateway 管理身份和 Kubernetes RBAC；
- UEM、系统插件、LLM Gateway 的服务密钥；
- 数据库管理员、系统服务和代理后端凭证；
- 其他用户的 Notebook、Kernel、PVC 和短期身份；
- 工号、Notebook 内容、SQL、模型 prompt 和审计记录。

### 2.3 信任边界

| 边界 | 可信程度 | 规则 |
| --- | --- | --- |
| Hub / Controller | 高 | 持有身份和创建 Server 的权限，不执行用户代码 |
| Jupyter Server | 中高 | 面向用户请求但不执行本地代码，只持有窄权限短期凭证 |
| EG Auth Proxy / EG | 高 | 绑定身份、执行 Kernel 策略、持有最小 Kubernetes RBAC |
| Kernel Pod | 不可信 | 默认视为已被用户完全控制 |
| Plugin Backend / UEM / LLM Gateway | 高 | 按服务拆分密钥和数据库 role，不暴露通用代理能力 |
| DB Proxy | 高 | 池化、路由、限流、审计；不能替代数据库授权 |

## 3. Enterprise Gateway 方案

### 3.1 组件职责

#### JupyterHub

- 使用企业 OIDC 完成认证和组/角色映射；
- 为每个用户创建 Jupyter Server Pod；
- 签发或协助交换 Server 到 EG Auth Proxy、UEM Collector 的短期身份；
- 管理 Server 生命周期、Quota、PVC 和空闲回收；
- 不直接创建用户 Kernel。

#### Jupyter Server

- 提供 JupyterLab、Contents、Sessions 和插件 HTTP 接口；
- 所有 Kernel API 通过 `GatewayClient` 指向 EG Auth Proxy；
- 不挂载 Kubernetes ServiceAccount token；
- 不包含本地 kernelspec 或本地 Kernel fallback；
- 不运行用户 Terminal；
- 插件只做身份补充、schema 校验和调用可信 Backend。

#### EG Auth Proxy

Enterprise Gateway 官方默认假定上游已经认证用户，不能把共享 `EG_AUTH_TOKEN` 和客户端提交的 `KERNEL_USERNAME` 当成完整多租户认证。Auth Proxy 负责：

- 校验 Jupyter Server 的 mTLS、JWT 或工作负载身份；
- 从可信身份得出 user、tenant、groups 和 server ID；
- 删除客户端提交的身份字段并覆盖 `KERNEL_USERNAME`；
- 将用户映射到批准的 kernel profile；
- 拒绝任意镜像、namespace、ServiceAccount、UID/GID、volume、Pod template；
- 限制 CPU、内存、GPU、并发、超时和允许的环境变量；
- 为每个请求生成 trace ID 并写审计。

#### Enterprise Gateway

- 维护远程 Kernel API 和生命周期；
- 使用受控 kernelspec 与 Kubernetes process proxy 创建 Kernel Pod；
- 管理启动、连接信息、interrupt、restart、shutdown 和孤儿清理；
- 仅允许 Auth Proxy/Jupyter Server 网络访问；
- 使用专用 ServiceAccount，不能读取业务 Secret。

### 3.2 Jupyter Server 配置

示意配置：

```python
from pathlib import Path

c.ServerApp.terminals_enabled = False
c.ServerApp.allow_root = False

c.GatewayClient.url = "https://eg-auth-proxy.jupyter-control.svc:8888"
c.GatewayClient.auth_scheme = "Bearer"
c.GatewayClient.auth_token = Path(
    "/var/run/jupyter-identity/eg-token"
).read_text().strip()
c.GatewayClient.ca_certs = "/var/run/jupyter-identity/ca.crt"
c.GatewayClient.connect_timeout = 60
c.GatewayClient.request_timeout = 120
```

该示例在 Server 启动时读取 Token；如果使用 15–60 分钟短期 Token，必须让凭证
刷新机制与 GatewayClient 生命周期配合，不能只轮换磁盘文件却让进程继续使用旧值。
生产优先采用 mTLS/workload identity，或实现支持刷新请求头的受控客户端适配层；
过渡方案可在 Token 过期前滚动重启用户 Server。

生产还必须：

- 删除镜像内本地 kernelspec，启动后检查 kernelspec 来源；
- Gateway 不可用时让创建 Kernel 失败，禁止回退本地进程；
- 禁用 Extension Manager 和用户自定义 Server 配置加载；
- 将系统配置和 Python 环境设为只读，用户只写 Notebook/PVC；
- 使用非 root、drop ALL、RuntimeDefault seccomp、禁止提权；
- 禁止 `hostNetwork`、`hostPID`、`hostIPC`、`hostPath` 和 privileged；
- egress 只允许 Hub、EG Auth Proxy、批准的插件 Backend、DNS；
- 不在日志、错误页、配置展示接口中输出 Token。

禁用 Terminal 本身不能保护与本地 Kernel 同处的 Server；本方案同时移除所有本地 Kernel，确保 Notebook 中的 `!bash` 运行在远程 Kernel Pod。

### 3.3 Kernel Pod 模板

Kernel Pod 基线：

```yaml
spec:
  automountServiceAccountToken: false
  restartPolicy: Never
  securityContext:
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: kernel
      securityContext:
        runAsNonRoot: true
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      resources:
        requests: {cpu: "500m", memory: "1Gi"}
        limits: {cpu: "2", memory: "4Gi"}
```

用户不能直接提交完整 Pod 模板。平台通过固定 profile 提供 Python、R、Spark、CPU、GPU 等组合，Auth Proxy 只接受 profile ID 和有限参数。

### 3.4 EG 版本与发布策略

- 使用经过公司验证的正式稳定版本，禁止 `latest`；当前方案基线至少为包含已知模板注入修复的 Enterprise Gateway 3.3.0。
- EG、kernelspec 和 Kernel 镜像固定 digest，生成 SBOM、漏洞扫描并签名。
- main/开发版文档中的能力必须在所选稳定版本中重新验证。
- 升级前回归 GatewayClient、Kernel create/restart/delete、Spark/GPU profile、会话恢复和安全负向测试。

## 4. Jupyter Server 密钥防泄露

### 4.1 Server 可以持有什么密钥

业务确实可能要求 Server 为 UEM、自研插件或 Gateway 调用持有身份。允许进入 Server 的只能是：

| 凭证 | 是否允许 | 要求 |
| --- | --- | --- |
| UEM ingestion token | 允许 | 当前 Server/用户专属，`aud=uem-collector`，仅 `uem:write`，短期可撤销 |
| EG Auth Proxy token | 允许 | 当前 Server 专属，`aud=eg-auth-proxy`，仅启动批准 profile |
| Plugin Backend token | 允许 | 每 Backend 单独 audience/scope，短期、限流 |
| 数据库密码 | 禁止 | 放 UEM/Plugin Backend 或 DB Proxy，不进入 Server |
| 模型供应商 Key | 禁止 | 放 LLM Gateway |
| Hub 管理 Token | 禁止 | 只在 Hub/Controller |
| Kubernetes 创建权限 | 禁止 | 只在 EG/Controller |

### 4.2 推荐注入方式

优先级从高到低：

1. **SPIFFE/SPIRE 或云工作负载身份**：Server 通过 mTLS 身份访问 Backend，无静态 Secret。
2. **投射的短期 ServiceAccount token**：使用独立 audience 和较短 expiration；该 ServiceAccount 不授予 Kubernetes API RBAC，Collector 验证 audience/subject。
3. **Token Broker 交换**：Spawner 注入一次性 bootstrap capability，Server 启动后交换为短期、窄权限 Token。
4. **Kubernetes Secret 文件**：仅作为过渡，挂载到独立只读路径，定期轮换，不写入镜像或 ConfigMap。

避免把长期 Token放进环境变量。环境变量容易进入进程转储、诊断输出和错误日志。若遗留插件只能读取 env，注入的也必须是短期窄权限 Token，而不是数据库密码。

推荐 JWT claims：

```json
{
  "iss": "jupyter-identity-broker",
  "sub": "server:alice:default",
  "user": "alice",
  "employee_id": "trusted-mapped-id",
  "server_id": "srv-01J...",
  "aud": "uem-collector",
  "scope": ["uem:write"],
  "exp": 1794502800,
  "jti": "01J..."
}
```

Collector 必须校验 issuer、audience、expiry、scope 和撤销状态，不能只解码 JWT。

### 4.3 即使密钥泄露也要限制影响面

- 每用户/Server 独立 Token，不使用全平台共享 Token；
- 15–60 分钟有效期，自动轮换；
- 只能访问单一 Backend 和单一操作；
- Backend 侧按 user/server/tenant 限流和配额；
- Token 不能读取历史事件、数据库或其他用户数据；
- 记录 `jti`，支持立即撤销；
- 日志只记录 Token 指纹，不记录 Token 正文；
- Server 删除时同步撤销凭证。

### 4.4 Server 密钥隔离成立的前提

以下条件缺一不可：

1. Terminal 显式禁用。
2. 所有 Kernel 远程化且不存在本地 fallback。
3. 用户不能安装或加载任意 Server Extension。
4. 用户可写目录不在 Jupyter/Python 配置搜索路径中。
5. Server Pod 无 `pods/exec`、Secret 读取和任意 Kubernetes 权限。
6. 插件 API 不提供任意文件读取、任意 URL 请求、任意 SQL 或命令执行。
7. Server egress 只到白名单服务。

Server 仍是面向用户输入的攻击面，所以只能通过“最小权限 + 短期 + 独立 Backend”降低影响，不能把它当作适合保存长期高权限 Secret 的保险箱。

## 5. 插件安全方案

### 5.1 插件分级

| 类型 | 示例 | 实现方式 |
| --- | --- | --- |
| 前端展示插件 | 菜单、面板、状态展示 | JupyterLab Extension，不含任何 Secret |
| 轻量 Server 适配层 | 同源转发、schema 校验、当前用户补充 | Jupyter Server Extension，只用窄权限短期 Token |
| 高权限系统能力 | UEM 写库、元数据管理、作业控制 | 独立 Plugin Backend，持有专属 Secret/DB role |
| 用户执行能力 | SQL、Python、模型调用 | Kernel + 用户级短期身份，或受控 Gateway |

### 5.2 标准插件调用链

```text
JupyterLab Extension
  │ 同源请求 + XSRF
  ▼
Jupyter Server Extension
  │ 从认证会话取得 user/server，覆盖客户端身份
  │ schema 校验、大小限制、速率限制
  ▼
Plugin Backend
  │ 验证 Server token，执行授权
  │ 使用服务专属 DB role
  ▼
Database / Enterprise Service
```

Server Extension 不接受客户端声明的 employee ID、tenant、role。它使用 Hub/IdP 的可信身份覆盖这些字段。Backend 再验证 Token 中的 subject 与请求资源是否匹配。

### 5.3 UEM 埋码

建议事件：

```json
{
  "event_id": "01J...",
  "event_type": "jupyter.cell.execute",
  "event_version": 1,
  "occurred_at": "2026-11-13T10:00:00Z",
  "workspace_id": "ws-123",
  "kernel_id": "kernel-456",
  "properties": {
    "language": "python",
    "duration_ms": 1320,
    "outcome": "success"
  }
}
```

浏览器不提交可信工号。Server/Collector 从 OIDC subject 映射 employee ID，并补充 tenant、server、trace。默认禁止源码、输出、SQL、Token、prompt 和明文账号进入 properties。

产品使用事件可能被用户阻断或伪造，只能用于产品分析。以下数据应从可信控制面生成：

- 登录：IdP/JupyterHub；
- Server/Kernel 生命周期：Hub/EG/Kubernetes；
- CPU/GPU：Prometheus/Kubernetes；
- 数据库访问：DB Proxy/数据库审计；
- JupyterAI Token 与成本：LLM Gateway；
- 网络拒绝：CNI/egress gateway。

### 5.4 禁止的插件模式

- 在前端 bundle、Notebook、ConfigMap 中写 Key；
- 在 Jupyter Server 中保存系统数据库密码；
- 提供“传入 SQL 并以系统账号执行”的通用接口；
- 提供任意 URL 代理，形成 SSRF；
- 使用一个共享 Token 代表所有用户；
- 信任浏览器提交的 user、employee ID、tenant 或 role；
- 把 sidecar 当作强安全边界。用户即使读不到 sidecar Secret，也可能滥用 localhost 接口代表的高权限能力。

## 6. 开源 DB Proxy 方案

### 6.1 两类数据访问必须分开

#### 用户原生查询

```text
Kernel
  │ psycopg / JDBC / SQLAlchemy / pandas / PyMySQL
  │ 用户或 Kernel 受限短期凭证
  ▼
PgBouncer / ProxySQL
  ▼
用户授权范围内的数据库 role / RLS
```

#### 系统插件写库

```text
UEM Collector / Plugin Backend
  │ 服务专属凭证
  ▼
独立 PgBouncer/ProxySQL pool
  ▼
系统 schema 的最小权限服务 role
```

两条链路不共享账号、pool、审计策略或数据库权限。

### 6.2 PostgreSQL：PgBouncer

PgBouncer 保持 PostgreSQL wire protocol，应用像连接 PostgreSQL 一样连接代理。

生产建议：

- 使用 PgBouncer **1.26.1 或更高的已修复版本**并固定镜像 digest。当前 POC 的 1.25.2 只保留验证记录，不可作为生产基线；1.26.1 修复了认证绕过和两个可由客户端触发的 DoS CVE。
- 初期使用 `pool_mode=session` 获得最高兼容性。
- 只有在回归 session `SET`、临时表、advisory lock、prepared statement、LISTEN/NOTIFY 和 ORM 后，才考虑 `transaction` pooling。
- 客户端和后端连接启用 TLS；认证优先 SCRAM-SHA-256、证书或公司身份集成。
- 按用户/数据库设置 pool size、连接上限、query timeout、idle transaction timeout。
- 管理 console 只允许运维网络和专用管理员身份访问。

PgBouncer 是连接池，不是 SQL 防火墙或细粒度审计系统。table/schema/RLS、只读和 DDL/DML 权限必须由 PostgreSQL role 与数据库审计执行。

### 6.3 MySQL：ProxySQL

ProxySQL 提供 MySQL 原生协议、连接池、hostgroup 路由、query rules、超时、digest 和事件日志。

生产建议：

- 使用公司批准并扫描的稳定版本，固定 digest；配置通过 Admin Interface 管理并持久化到 disk/runtime。
- 创建专用 monitor 用户，只授予连接/ping/read_only 检查需要的权限，不复用业务账号。
- frontend/backend 均启用 TLS；评估 SPIFFE 身份能力。
- 按 user/schema/digest 配置连接数、超时、路由和必要的 query rules。
- 回归 prepared statement、事务粘性、session variables、`SET NAMES`、JDBC、SQLAlchemy 和 pandas。
- 默认使用 digest/统计进行观测。原始 SQL 日志只在数据分级、脱敏、加密、访问权限和保留期确认后选择性开启。
- Admin 端口不向 Kernel、Jupyter Server 或公网开放。

ProxySQL 的 query rules、firewall 和日志是纵深防御，不能替代 MySQL 用户权限和数据库审计。

### 6.4 MongoDB：HAProxy

HAProxy 可保持 MongoDB wire protocol 并提供 L4 负载均衡、健康检查和连接日志，但不能理解 Mongo 查询或做字段级审计。

- 用户使用标准 PyMongo URI；
- TLS 和认证由 MongoDB 原生能力承担；
- query/action 权限使用 MongoDB RBAC；
- 若要求查询正文审计或细粒度策略，使用 MongoDB Enterprise/native audit 或专用产品，而不是继续堆 HAProxy 规则。

### 6.5 Elasticsearch：Nginx 或 Envoy

Elasticsearch SDK 本身使用 HTTP，Nginx/Envoy 可以透明处理 TLS、连接复用、method/path、body size、并发、超时和 access log。

- index/action 权限由 Elasticsearch Security role 执行；
- 不仅按 URL path 判断 DSL 查询权限；
- 禁止开放集群管理 API；
- 大响应、scroll、bulk、script query 和慢查询单独限额；
- 对系统插件与用户查询使用不同身份。

### 6.6 凭证模型

开源连接池不会自动完成企业身份到数据库身份的转换。按优先顺序选择：

1. 每用户/Kernel 的数据库最小权限短期凭证；
2. 数据库 IAM/证书/SPIFFE 等工作负载身份；
3. 数据库只接受代理源地址，阻止直连绕过；
4. 若强制要求 Kernel 完全不持有可用数据库凭证，引入支持前后端身份映射的企业数据网关，PgBouncer 本身不能完成该要求。

## 7. 网络和 Kubernetes 权限

### 7.1 通信矩阵

| 来源 | 允许 | 拒绝 |
| --- | --- | --- |
| Browser | Ingress HTTPS/WebSocket | EG、Pod/Service 内网地址 |
| Jupyter Server | Hub、EG Auth Proxy、Plugin Backend、DNS | K8s API、真实 DB、云元数据、公网 |
| EG Auth Proxy | Enterprise Gateway、身份服务 | 数据库、Kernel 业务网络 |
| Enterprise Gateway | K8s API、Kernel 必要回连 | 系统数据库、非批准企业服务 |
| Kernel | DNS、必要 Kernel 协议、批准 DB Proxy/对象存储 | K8s API、metadata、公网、真实 DB、其他租户 |
| Plugin Backend | 专属 DB Proxy、必要企业服务 | 用户 Kernel、其他服务数据库 |
| DB Proxy | 指定数据库实例 | 其他数据库和公网 |

### 7.2 RBAC

- Hub：创建/删除用户 Server，不读取业务 Secret；
- Jupyter Server：无 Kubernetes API 权限；
- EG：只管理指定 Kernel namespace 中批准的 Pod/Service/ConfigMap，不读 Secret；
- Kernel：无权限 ServiceAccount，且 `automountServiceAccountToken=false`；
- Plugin Backend：通常无 Kubernetes API 权限；需要工作负载身份时只使用 audience 限定的 projected token。

### 7.3 网络执行

NetworkPolicy YAML 不是安全证明。必须在公司 CNI、Pod 安全组、子网 ACL 或 egress gateway 上从真实 Kernel 做以下负向测试：

- API Server、`169.254.169.254`、公网不可达；
- 真实数据库 IP/端口不可达；
- 其他用户 Server、Kernel、PVC 服务不可达；
- 只有批准的代理和对象存储端点可达。

## 8. 高可用与可观测性

| 组件 | HA/状态策略 | 关键指标 |
| --- | --- | --- |
| JupyterHub | 外部 PostgreSQL、备份、PDB、受控 HA | 登录、spawn 时延、失败率 |
| Jupyter Server | 可重建，Notebook/PVC 持久化 | API/WebSocket、内存、活动时间 |
| EG Auth Proxy | 无状态多副本 | 鉴权拒绝、profile、延迟、限流 |
| Enterprise Gateway | 会话持久化、粘性/重连、孤儿回收演练 | Kernel create/restart/delete、孤儿数 |
| Kernel | 默认内存状态不可恢复 | 启动时延、CPU/GPU/内存、空闲时间 |
| PgBouncer | 多副本/滚动维护、配置与 TLS 管理 | pool、wait、连接、query/xact time |
| ProxySQL | HA、配置持久化和 monitor | hostgroup、digest、错误、连接池 |
| Plugin Backend | 无状态副本 + 队列/幂等 DB | 接收/拒绝、积压、写库时延 |

统一关联字段：tenant、user/employee subject、server/workspace ID、kernel ID、request/trace ID、目标服务、结果、耗时和资源量。默认不记录 Token、Notebook 源码、输出、原始 SQL 和 prompt。

## 9. 实施阶段

### 阶段 1：Enterprise Gateway 最小闭环

1. 部署固定版本 EG、EG Auth Proxy 和 Python Kernel profile。
2. Jupyter Server 显式禁用 Terminal和本地 Kernel。
3. 验证 create、execute、interrupt、restart、delete。
4. 验证 Server canary secret 不在 Kernel。
5. 验证伪造 user、镜像、namespace、ServiceAccount、volume 和超配资源失败。

### 阶段 2：Server 短期身份和插件

1. 部署 Identity Broker 或接入 SPIFFE/workload identity。
2. UEM Token 改为 per-server、audience/scope 限定、短期可撤销。
3. UEM Collector 使用专属 PostgreSQL role 持久化。
4. 验证用户伪造 employee ID、跨用户事件和重放请求失败。
5. JupyterAI 通过 LLM Gateway，Server/Kernel 中不存在供应商 Key。

### 阶段 3：DB Proxy

1. 将 PgBouncer 升级到 1.26.1+ 固定镜像。
2. 接入真实测试 PostgreSQL/MySQL 最小权限 role。
3. 实现用户/Kernel 短期凭证或公司工作负载身份。
4. 回归 psycopg、JDBC、SQLAlchemy、pandas、PyMySQL、事务和 prepared statement。
5. 验证 Kernel 直连真实数据库失败，代理异常时不回退直连。

### 阶段 4：网络、可靠性和规模

1. 在公司 CNI/安全组环境证明 default-deny。
2. 演练 Hub、Server、EG、Kernel、Proxy、Backend 重启。
3. 验证空闲回收、孤儿清理、Quota、公平调度和镜像预拉取。
4. 建立 SLO、Dashboard、告警和容量模型。

## 10. 上线验收门

1. 所有 Notebook 代码和 `!bash` 只在远程 Kernel Pod 执行。
2. Jupyter Server Terminal、本地 Kernel fallback、用户 Server 配置加载均被禁用。
3. Server 仅持有短期窄权限 Token，不含 DB、LLM、Hub 管理和 Kubernetes 高权限密钥。
4. Kernel 无平台 Secret、无 K8s token，无法访问 API Server、metadata、公网和真实 DB。
5. Auth Proxy 绑定可信用户并拒绝伪造 `KERNEL_USERNAME` 与危险 Kernel 参数。
6. 插件系统密钥只存在独立 Backend；插件 API 不提供任意 SQL、URL 或命令执行。
7. 用户原生数据库驱动经代理成功，真实数据库直连失败。
8. PostgreSQL/MySQL role、RLS/schema、只读/写入权限和 DDL/DML 负向测试通过。
9. PgBouncer 使用 1.26.1+ 已修复版本；所有镜像固定 digest、扫描、SBOM、签名。
10. Hub、Server、EG、Kernel、插件、DB Proxy 和数据库审计可以按统一 trace 关联。
11. 凭证轮换、撤销、Server 删除和异常退出不会遗留长期有效 Token。
12. 故障恢复、孤儿回收、空闲回收和并发容量达到约定 SLO。

## 11. 开源组件清单

| 能力 | 推荐组件 | 备注 |
| --- | --- | --- |
| 用户与 Server 生命周期 | JupyterHub + KubeSpawner/平台 Controller | 接企业 OIDC |
| 远程 Kernel | Jupyter Enterprise Gateway | 前置 Auth Proxy/Authorizer |
| PostgreSQL 连接池 | PgBouncer 1.26.1+ | 不是 SQL 防火墙 |
| MySQL 代理 | ProxySQL | query rules、hostgroup、digest、日志 |
| MongoDB L4 代理 | HAProxy | 查询权限依赖 MongoDB |
| Elasticsearch HTTP 代理 | Nginx 或 Envoy | index/action 依赖 ES Security |
| 身份 | SPIFFE/SPIRE、公司 IAM 或 Token Broker | 短期 workload identity |
| Secret | Vault/公司 Secret Manager/KMS | 不把长期 Secret 写入 env/ConfigMap |
| 网络 | Cilium/Calico/Pod 安全组/egress gateway | 必须做真实负向测试 |
| UEM/插件后端 | 独立微服务 + 队列/数据库 | 每服务独立 role |
| 模型访问 | LLM Gateway | 隔离供应商 Key、额度和审计 |

## 12. 官方参考

- [Enterprise Gateway 客户端连接和认证](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/users/connecting-to-eg.html)
- [Enterprise Gateway 安全配置](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/operators/config-security.html)
- [GatewayClient 配置](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/users/client-config.html)
- [Jupyter Server 配置](https://jupyter-server.readthedocs.io/en/latest/other/full-config.html)
- [PgBouncer 使用方式](https://www.pgbouncer.org/usage)
- [PgBouncer 配置和 pooling/auth](https://www.pgbouncer.org/config)
- [PgBouncer 1.26.1 安全发布](https://www.pgbouncer.org/)
- [ProxySQL 查询规则和统计](https://proxysql.com/documentation/proxysql-configuration/)
- [ProxySQL 查询日志](https://proxysql.com/documentation/query-logging)
- [ProxySQL 安全能力](https://proxysql.com/documentation/security/)
