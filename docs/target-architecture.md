# 目标方案：Enterprise Gateway + 数据访问治理

## 1. 目标

目标方案面向公司数据/AI 平台，而不是当前腾讯云 POC 的直接生产化。核心目标：

- 所有用户代码在独立 Kernel Pod 中执行。
- Jupyter Server 不执行用户 shell，不向 Kernel 暴露平台密钥。
- Enterprise Gateway 集中管理 Kernel 生命周期、镜像、资源和 Kubernetes 权限。
- 用户保持原生 SQL/数据库驱动体验。
- 系统插件的数据库密钥只存在可信 Backend。
- 统一身份贯穿 Hub、Server、Kernel、数据代理、插件、UEM 和审计。
- 网络默认拒绝，数据库不能绕过代理直连。

## 2. 总体架构

```text
                                 ┌──────────────────────────┐
Browser ──HTTPS/WebSocket──────► │ Ingress / JupyterHub     │
                                 │ OIDC、授权、用户生命周期   │
                                 └────────────┬─────────────┘
                                              │ spawn
                                              ▼
                                 ┌──────────────────────────┐
                                 │ Per-user Jupyter Server  │
                                 │ Lab / Contents / Session │
                                 │ 禁用 Terminal、本地 Kernel│
                                 │ 无平台 DB 密码、无 K8s RBAC│
                                 └──────┬───────────┬───────┘
                                        │           │ 插件事件/API
                         remote kernel  │           ▼
                                        │    ┌─────────────────────┐
                                        │    │ Trusted Backends    │
                                        │    │ UEM / Plugin / LLM  │
                                        │    └──────────┬──────────┘
                                        ▼               │ 系统专属角色
                         ┌────────────────────────┐       │
                         │ EG Auth Proxy          │       │
                         │ 身份绑定、参数策略、限流 │       │
                         └───────────┬────────────┘       │
                                     ▼                    │
                         ┌────────────────────────┐       │
                         │ Enterprise Gateway     │       │
                         │ Kernel 生命周期与路由   │       │
                         └───────────┬────────────┘       │
                                     │ create              │
                                     ▼                    │
                         ┌────────────────────────┐       │
                         │ Per-kernel Pod         │       │
                         │ Python / !bash / GPU   │       │
                         │ 无平台密钥、无 K8s token│       │
                         └───────────┬────────────┘       │
                                     │ 用户短期 DB 身份     │
                                     ▼                    ▼
                         ┌──────────────────────────────────┐
                         │ Data Access Layer                │
                         │ PgBouncer / ProxySQL / HAProxy   │
                         │ Nginx / Egress Gateway           │
                         └────────────────┬─────────────────┘
                                          ▼
                              PostgreSQL / MySQL / Mongo / ES
```

## 3. 信任域

| 信任域 | 组件 | 可以持有 | 禁止持有 |
| --- | --- | --- | --- |
| 身份控制面 | IdP、JupyterHub | OIDC client secret、Hub DB、签发权限 | 用户数据库密码 |
| Kernel 控制面 | EG Auth Proxy、Enterprise Gateway | EG 服务身份、Kernel 创建 RBAC | 用户代码、平台数据库密码 |
| 用户展示层 | per-user Jupyter Server | 当前用户短期 Server/Gateway 身份 | K8s 创建权限、平台共享 DB/LLM/UEM 密钥 |
| 用户执行面 | Kernel Pod | 用户级短期数据凭证 | 平台密钥、K8s token、高权限 DB 密码 |
| 插件服务层 | UEM/Plugin/LLM Backend | 各服务专属 Secret 和 DB role | 通用管理员账号 |
| 数据访问层 | DB Proxy、数据库 | 后端连接凭证、路由与授权配置 | Hub/OIDC 密钥 |

原则：任何进入 Jupyter Server 或 Kernel 的凭证都按用户可见设计；真正的平台共享密钥
只留在 Hub、EG 控制面或独立可信 Backend。

## 4. Jupyter 与 Enterprise Gateway

### 4.1 用户 Server

JupyterHub 为每个用户创建轻量 Jupyter Server。Server 只提供 Lab、Contents、
Sessions 和插件适配层：

```python
c.ServerApp.terminals_enabled = False
```

同时要求：

- 删除本地 kernelspec，所有 Kernel 请求只能走 `GatewayClient`。
- Gateway 不可用时失败关闭，不能回退本地进程。
- 禁用用户 Server 配置加载、Extension Manager 和运行时安装 Server Extension。
- Server 使用只读镜像、非 root、drop ALL、RuntimeDefault seccomp。
- Server 不挂载 Kubernetes ServiceAccount token。

### 4.2 EG Auth Proxy

Stock Enterprise Gateway 默认假定上游已完成认证，不能只依赖共享
`EG_AUTH_TOKEN` 和客户端提交的 `KERNEL_USERNAME`。目标方案在 EG 前增加身份与策略层：

1. 校验 Jupyter Server 的短期服务身份。
2. 根据 Hub 会话确定 `user_id`、tenant、groups 和 workspace。
3. 服务端覆盖 `KERNEL_USERNAME`，拒绝客户端伪造。
4. 将用户/组映射为允许的 kernel profile。
5. 限制镜像、namespace、ServiceAccount、UID/GID、volume、CPU、内存、GPU 和并发。
6. 写入 user/server/kernel/trace 关联审计。

### 4.3 Enterprise Gateway

- 使用已发布且包含安全修复的 3.3.0 或后续稳定版，固定镜像 digest。
- 使用 `ClusterIP`，只允许 Jupyter Server/Auth Proxy 访问。
- 以独立 ServiceAccount 管理专用 Kernel namespace，不授予 Secret 读取权限。
- kernelspec 和 Pod template 构建进受控镜像，不接受用户任意模板。
- 会话持久化、EG 重启、Kernel 重连和孤儿清理必须实测后才能启用多副本。

### 4.4 Terminal 策略

Enterprise Gateway 不代理 Terminal。目标基线禁用 Jupyter 原生 Terminal，Notebook
中的 `!bash` 在远程 Kernel Pod 内执行。

如果业务必须提供交互式 Shell，作为二期能力单独提供 Workspace Shell Pod：

```text
JupyterLab ─► Remote Terminal Gateway ─► Workspace Shell Pod
```

Shell Pod 与 Kernel 可共享用户 PVC，但不共享平台密钥；远程 PTY、身份绑定、空闲回收
和命令审计需独立验收。不能让 Terminal 回退到 Jupyter Server Pod。

## 5. 数据库访问目标方案

### 5.1 用户原生查询

```text
Kernel
  │ psycopg / JDBC / SQLAlchemy / PyMySQL
  │ 用户或 Kernel 短期凭证
  ▼
PgBouncer / ProxySQL
  │
  ▼
数据库最小权限 role / RLS / resource group
```

要求：

- 客户端代码只修改 host/port/凭证来源，不改变原生协议和事务 API。
- 数据库防火墙只允许代理源地址；Kernel 到真实 DB IP/端口必须失败。
- 凭证绑定 user、tenant、workspace、kernel，短期、可撤销、可轮换。
- PostgreSQL 使用 PgBouncer `session` 起步；切换 transaction pooling 前回归临时表、
  prepared statement、session `SET`、LISTEN/NOTIFY 和 ORM 行为。
- MySQL 在 ProxySQL 回归 prepared statements、事务粘性、session variables、JDBC、
  SQLAlchemy/pandas 和 query rules。
- DB Proxy 日志默认记录身份、目标、digest、耗时、行数和结果状态；原始 SQL 按数据
  分级决定，不能默认全量记录。

### 5.2 系统插件写库

UEM、使用习惯、作业状态、JupyterAI 统计等系统能力采用独立可信服务：

```text
Lab/Server 插件
  │ 当前用户短期身份 + schema 化事件/业务请求
  ▼
UEM Collector / Plugin Backend / LLM Gateway
  │ 服务专属 DB role
  ▼
专用 PgBouncer/ProxySQL pool
  ▼
系统数据库
```

- 插件不能接收任意 SQL 代替用户执行高权限操作。
- 每个 Backend 使用独立数据库角色和 schema 权限，不共享管理员账号。
- 工号从 OIDC subject/可信映射获得，忽略客户端自报身份。
- 浏览器 UEM 只作为产品分析；安全审计从 Hub、EG、Kubernetes、数据库和网关产生。
- JupyterAI 的平台模型 Key 只在 LLM Gateway，Jupyter 插件只拿用户级短期 capability。

### 5.3 MongoDB 与 Elasticsearch

- HAProxy 仅提供 MongoDB L4 透明转发；查询授权和审计依赖 MongoDB RBAC/audit 或专用网关。
- Nginx 保持 Elasticsearch HTTP SDK 体验；index/action 授权依赖 Elasticsearch Security，
  Nginx/Ingress 负责 method/path/body size/并发/超时等外围限制。

## 6. 网络目标矩阵

| 来源 | 允许目标 | 必须拒绝 |
| --- | --- | --- |
| Browser | Ingress HTTPS/WebSocket | Pod/Service/EG 内网地址 |
| Jupyter Server | Hub、EG Auth Proxy、Plugin Backend、DNS | K8s API、真实 DB、云元数据、公网 |
| EG Auth Proxy | Enterprise Gateway、身份验证服务 | Kernel 业务端口、数据库 |
| Enterprise Gateway | K8s API、Kernel 回连所需端口 | 系统数据库、非批准内部服务 |
| Kernel | Server/EG 必要协议、DNS、批准的数据代理/对象存储 | K8s API、元数据、公网、真实 DB、其他租户 |
| Plugin Backend | 专用 DB Proxy、必要企业服务 | 用户 Kernel、非本服务数据库 |
| DB Proxy | 指定数据库实例 | 其他数据库和公网 |

实现可以是 Cilium/Calico NetworkPolicy、Pod 安全组、独立子网 ACL 与 egress gateway
组合，但验收只看真实连通行为，不看对象是否创建成功。

## 7. 身份与关联 ID

可信身份链：

```text
OIDC sub / employee_id
  → Hub user
  → server_id / workspace_id
  → EG kernel_id
  → DB session / plugin request / trace_id
```

所有服务统一记录：

- tenant/user/employee subject
- server/workspace/kernel ID
- request/trace ID
- 目标服务、数据库或模型
- 开始/结束时间、状态、耗时和资源量

禁止把密码、token、Notebook 源码、输出和原始 SQL默认写入普通日志。

## 8. 高可用与状态

| 组件 | 状态 | 目标方案 |
| --- | --- | --- |
| JupyterHub | 用户、Spawner、OAuth | 外部 PostgreSQL、备份、PDB、单活/受控 HA |
| Jupyter Server | Notebook session、文件 | 用户 PVC/对象存储；Server 可重建 |
| Enterprise Gateway | Kernel 会话路由 | 持久 session、粘性/重连、故障演练后多副本 |
| Kernel | 内存执行状态 | 默认不可恢复；Notebook/PVC 可保留 |
| PgBouncer/ProxySQL | pool、路由配置、统计 | HA、配置持久化、PDB、监控、TLS |
| UEM/Plugin Backend | 事件/业务请求 | 无状态副本 + 队列/DB 幂等 |

## 9. 分阶段落地

### 阶段 A：Enterprise Gateway 安全链路

- 部署固定版本 EG、Auth Proxy、一个 Python Kernel profile。
- 验证创建、执行、中断、重启、删除。
- 验证 Server canary secret 不在 Kernel，Terminal 被禁用，本地 fallback 不存在。
- 验证伪造用户、镜像、ServiceAccount、namespace、volume 和超配资源被拒绝。

### 阶段 B：数据库生产模型

- 接入真实测试 PostgreSQL/MySQL 和最小权限角色。
- 实现用户/Kernel 短期凭证或 workload identity。
- 数据库仅允许代理源地址，完成直连阻断负向测试。
- 回归 ORM、JDBC、事务、prepared statement、临时表和 session state。

### 阶段 C：系统插件可信后端

- UEM Collector 持久写入 PostgreSQL，Workspace/Server/Kernel 无 DB 密码。
- 工号由可信 OIDC subject 映射，完成伪造身份负向测试。
- JupyterAI 经 LLM Gateway，验证模型权限、额度、审计与 Key 隔离。

### 阶段 D：网络、可靠性与规模

- 在公司 CNI/安全组环境证明 default-deny。
- 演练 Hub、Server、EG、Kernel、DB Proxy、Backend 重启。
- 验证空闲回收、孤儿清理、并发/Quota、镜像预拉取和启动 SLO。

## 10. 上线验收门

1. Kernel 无平台 Secret、无 Kubernetes token，不能访问 API Server/metadata/公网/真实 DB。
2. Terminal 不在 Jupyter Server 本地启动；若提供远程 Shell，其安全边界单独通过。
3. EG 身份由服务端绑定，用户不能伪造 `KERNEL_USERNAME` 或资源模板参数。
4. 用户通过原生驱动访问代理成功，直连真实数据库失败。
5. 系统插件、UEM、JupyterAI 的平台密钥只存在可信 Backend。
6. 每个数据库调用方使用独立最小权限 role，DDL/DML/跨 schema 越权测试失败。
7. Hub、Server、EG、Kernel、Proxy 和 Backend 的身份/trace 可关联。
8. 所有镜像固定 digest、生成 SBOM、扫描并签名。
9. 故障恢复、孤儿回收、空闲回收和配额达到约定 SLO。
10. PII、Notebook 内容、SQL 和模型 prompt 的采集/保留经过合规评审。

## 11. 关键选型结论

- **目标主线**：JupyterHub + 轻量 Jupyter Server + EG Auth Proxy + Enterprise Gateway + per-kernel Pod。
- **用户数据库访问**：原生协议 + PgBouncer/ProxySQL + 用户/Kernel 短期身份。
- **系统插件数据库访问**：独立 Plugin Backend/UEM Collector + 服务专属 DB role。
- **Terminal**：基线禁用；确有需求时建设独立 Remote Terminal/Workspace Shell，不回到 Server Pod。
- **网络**：必须在公司真实 CNI/安全组上通过行为测试，当前 TKE Serverless 结果不能作为生产证明。
- **备选回退**：若 EG 身份层、版本兼容或运维成本不可接受，回退直接 Provisioner；若原生 Terminal 优先级最高，采用无平台密钥 Workspace Pod。

Enterprise Gateway 的版本、安全和 POC 细则见
[`enterprise-gateway-option.md`](enterprise-gateway-option.md)，数据库代理细节见
[`sql-proxy.md`](sql-proxy.md)。
