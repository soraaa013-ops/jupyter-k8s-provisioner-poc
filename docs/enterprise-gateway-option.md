# Enterprise Gateway 备选方案

## 状态

**已完成架构调研，尚未在本 TKE 集群部署验证。** 当前稳定 POC 仍是
Kubernetes Provisioner 与 Workspace Pod 两条已实测路线。本文件定义下一轮
Enterprise Gateway POC 的范围和验收门，不能作为“已经跑通”的证明。

## 要解决的问题

Enterprise Gateway（EG）适合将用户代码与 Jupyter Server 分离，同时把 Kernel
创建权限从每个 Jupyter Server 收敛到集中 Gateway：

```text
Browser
  │
  ▼
JupyterHub ─► per-user Jupyter Server（相对可信）
              ├─ JupyterLab / Contents / 自研插件适配层
              ├─ 禁用本地 Terminal
              ├─ 禁用本地 Kernel fallback
              └─ GatewayClient
                       │ HTTP / WebSocket
                       ▼
                EG Auth Proxy / Authorizer
                       │
                       ▼
                Enterprise Gateway 3.3+
                       │ Kubernetes API
                       ▼
                per-kernel Pod（不可信）
```

用户在 Notebook 中执行 Python、`!bash`、`subprocess` 时均位于 Kernel Pod，
不能直接读取 Jupyter Server Pod 的环境变量和挂载。EG 官方定位是为多用户在
Kubernetes、YARN 等资源管理环境中启动远程 Kernel，并不管理多个 Jupyter
部署；用户 Server 生命周期仍由 JupyterHub/平台负责。

## 能力与非目标

| 问题 | EG 是否解决 | 说明 |
| --- | --- | --- |
| Server 与 Kernel 分 Pod | 是 | EG 创建并管理远程 Kernel Pod |
| 每 Kernel 独立资源/镜像 | 是 | 通过 kernelspec、process proxy 和 Pod 模板 |
| 收敛 Kubernetes RBAC | 是 | 主要由 EG 持有 Kernel 创建权限 |
| 原生 Notebook Kernel 协议 | 是 | Jupyter Server 使用 GatewayClient 转发 |
| 远程 Terminal | **否** | 原生 Terminal 仍在 Jupyter Server 本地执行 |
| 系统插件数据库密钥隔离 | **不直接解决** | 仍应拆到 UEM/Plugin Backend 等可信服务 |
| 用户认证 | **默认不完整** | EG 假定上游已认证；必须增加可信身份绑定 |
| NetworkPolicy 执行 | 否 | 仍依赖 CNI、Pod 安全组或 egress gateway |

## Terminal 决策

EG 只代理 Kernel。若 Jupyter Server 持有任何平台密钥，POC 必须禁用本地
Terminal：

```python
c.ServerApp.terminals_enabled = False
```

还必须移除本地 kernelspec、关闭 Extension Manager/用户 Server 配置加载，
并验证 Gateway 不可用时创建 Kernel **失败关闭**，不能回退为本地进程。

如果产品必须提供交互式 Shell，应另建受限 Workspace/Terminal Pod；这会形成
与 Kernel 不同的执行环境，需另行解决共享 PVC、依赖和身份一致性。EG 本身不
提供该能力。

## 身份与认证是核心风险

Stock EG 默认假定认证已经由 JupyterHub、Knox 或前置代理完成。共享
`EG_AUTH_TOKEN` 只能证明“请求知道同一个 token”，不能可靠证明具体用户；
`KERNEL_USERNAME` 是请求携带的身份值，不能直接信任用户提交。

生产方向必须满足：

1. 每个 Jupyter Server 使用独立、短期、可撤销的调用身份。
2. EG Auth Proxy 或自定义 Authorizer 校验调用方，并服务端覆盖
   `KERNEL_USERNAME`。
3. 用户不能选择任意 namespace、ServiceAccount、镜像、UID/GID、volume 或
   Pod template。
4. Kernel 创建策略按 user/group/tenant 限制 CPU、内存、GPU、并发与镜像。
5. EG API 只允许 Jupyter Server 网络访问，不向浏览器或公网开放。

仅配置 `authorized_users`/`unauthorized_users` 不等于完成认证，因为它依赖传入
的 `KERNEL_USERNAME`。

## 系统插件与密钥

EG 可以防止 Kernel 代码直接读取 Server 环境，但不应据此把系统数据库密码
复制到每个 Jupyter Server。对于记录工号和使用习惯的插件，仍采用：

```text
JupyterLab/Server 插件 ─► UEM Collector ─► PgBouncer ─► UEM Database
                              │
                              └─ 持有系统数据库凭证
```

Collector 从可信身份解析工号，忽略客户端自报 employee ID。平台数据库凭证只
存在 Collector；Jupyter Server 只携带面向 Collector 的短期、受限身份。其他
需要高权限的自研插件同样拆分为 Workspace/Server 适配层与可信 Plugin Backend。

## 安全部署基线

- 使用稳定版 `3.3.0` 或更高的已发布修复版，并固定镜像 digest；不要直接使用
  `latest` 或把 main/3.4-dev 文档能力当作已发布能力。
- 3.3.0 修复了 UID/GID 校验绕过、Jinja2 模板注入和 Kubernetes manifest 注入
  等安全问题，旧版本不进入本 POC。
- EG Service 使用 `ClusterIP`，通过 NetworkPolicy/安全组只接受 Jupyter Server。
- EG 使用专用 ServiceAccount；权限只覆盖目标 Kernel namespace 和必要资源。
- Kernel Pod 禁止挂载 EG/Jupyter Server Secret，默认不挂载 ServiceAccount
  token，使用 restricted Pod Security 与非 root 用户。
- Pod 模板和 kernelspec 进入镜像供应链，固定 digest、扫描、签名并做 allowlist。
- 对 Kernel 回连端口、EG API、ZMQ/WebSocket、TLS/mTLS 和超时分别建模。
- HA 必须验证会话持久化、Gateway 重启、Kernel 重连和孤儿清理，不能只增加副本。

## POC 实施计划

### 阶段 1：最小链路

1. 独立 namespace 部署 EG 3.3.x `Deployment + ClusterIP`。
2. 构建固定版本的 EG 与 Python Kernel 镜像，禁止运行时安装。
3. 配置一个 Jupyter Server 使用 `GatewayClient.url`。
4. 创建、执行、中断、重启、删除远程 Python Kernel。
5. 证明 Kernel 与 Server hostname、PID、环境变量和 ServiceAccount 不同。

### 阶段 2：安全负向测试

1. Server 的 canary secret 在 Kernel 中不存在。
2. JupyterLab Terminal 被禁用，Terminal REST/WebSocket 端点不可用。
3. EG 不可用时不启动本地 Kernel。
4. 伪造 `KERNEL_USERNAME`、镜像、ServiceAccount、namespace、volume 被拒绝。
5. 浏览器/Kernel 不能直连 EG 管理 API。
6. Kernel 不能访问 Kubernetes API、元数据、公网和真实数据库。
7. 非批准镜像、超配 CPU/GPU、跨租户 Kernel 创建失败。

### 阶段 3：插件与可靠性

1. UEM 插件经 Collector 写 mock PostgreSQL，Server/Kernel 均没有 DB 密码。
2. Server、EG、Kernel 分别重启并记录恢复语义。
3. 验证 idle culling、孤儿回收、并发上限与启动时延。
4. 将 user/workspace/server/kernel ID 关联进 UEM、EG 和 Kubernetes 审计。

## 决策矩阵

| 需求 | Workspace Pod | 直接 Provisioner | Enterprise Gateway |
| --- | --- | --- | --- |
| 原生 Terminal | 最好 | Server 本地，不安全时需禁用 | Server 本地，不安全时需禁用 |
| Server/Kernel 强隔离 | 否，Server 属于用户执行面 | 是 | 是 |
| 每 Kernel 独立资源 | 弱/需额外实现 | 是 | 是 |
| Kubernetes 权限收敛 | Hub 创建 Workspace | 每 Server 持有权限 | 集中到 EG |
| Spark/YARN/多计算后端 | 非重点 | Kubernetes 为主 | 最适合 |
| 网关运维复杂度 | 低 | 中 | 高 |
| 平台插件密钥 | 放独立 Backend | 放独立 Backend | 仍放独立 Backend |

初步选择原则：需要原生 Terminal 与统一用户环境时优先 Workspace；希望所有
用户代码远程化、每 Kernel 独立调度或接入 Spark/YARN 时评估 EG；希望最少组件
且只面向 Kubernetes 时继续保留直接 Provisioner。

## 官方资料

- [项目与能力边界](https://github.com/jupyter-server/enterprise_gateway)
- [Jupyter Server 连接 Enterprise Gateway](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/users/connecting-to-eg.html)
- [系统架构与 Process Proxy](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/contributors/system-architecture.html)
- [安全配置与用户授权](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/operators/config-security.html)
- [Kubernetes 部署](https://jupyter-enterprise-gateway.readthedocs.io/en/main/operators/deploy-kubernetes.html)
- [3.3.0 Release 与安全修复](https://github.com/jupyter-server/enterprise_gateway/releases/tag/v3.3.0)
