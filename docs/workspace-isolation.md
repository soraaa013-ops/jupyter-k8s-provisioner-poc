# Workspace Pod 与密钥隔离

## 推荐边界

POC 将平台控制面和用户执行面分开：

```text
Browser ─► JupyterHub（可信控制面，OIDC/Kubernetes 权限）
              │ KubeSpawner
              ▼
       Workspace Pod（不可信用户执行面）
       ├── 单用户 Jupyter Server / JupyterLab
       ├── 原生 Terminal / bash
       └── 一个或多个本地 Kernel
              │
              ▼
       PgBouncer / ProxySQL / 其他受控服务
```

这里需要区分 JupyterHub 和单用户 Jupyter Server。Hub 是平台控制器；单用户
Server 属于用户 Workspace，不应持有 OIDC client secret、Hub 管理 token、
Kubernetes 管理身份或数据库后台密码。Terminal 和 Kernel 都由单用户 Server
在本 Pod 内原生启动，因此不需要自研远程 PTY 插件。

## POC 安全设置

- KubeSpawner 为每个用户创建 `component=workspace` 的 Pod。
- Workspace 使用无 RBAC 权限的独立 ServiceAccount，且
  `automountServiceAccountToken=false`。
- OIDC client secret 和 Hub 管理 token 只注入 Hub Pod。
- Workspace 只收到 JupyterHub 自动签发的用户 Server token；它是用户可见的
  工作区级能力，不应被当作平台秘密。
- Workspace Pod 使用非 root 用户、RuntimeDefault seccomp、禁止提权并移除
  Linux capabilities。
- NetworkPolicy 默认拒绝 Workspace ingress/egress，只声明 Hub、DNS 和数据库
  代理路径。当前 TKE Serverless 没有实际执行这些 NetworkPolicy，仍需通过
  Pod 安全组/CNI/egress gateway 补齐。

## 为什么不是远程 Terminal 插件

若坚持“单用户 Jupyter Server 在可信 Pod，Terminal/Kernel 在另一个 Pod”，
Jupyter 原生 Terminal 无法跨 Pod，需要自定义 TerminalManager 或额外 Web
Terminal。当前核心需求是密钥隔离，因此把无平台密钥的单用户 Server 一起放入
Workspace，可以复用 Jupyter 原生 Terminal，同时把真正敏感的控制权限留在 Hub。

## 已验证行为

`tests/workspace_smoke.py` 从真实 Workspace Pod 内验证：

1. OIDC、Hub 管理和 UEM 密钥不在环境变量中。
2. Kubernetes ServiceAccount token 未挂载。
3. Jupyter REST API 创建的 Kernel 与 Workspace hostname 相同。
4. Jupyter Terminal WebSocket 执行 bash，hostname 与 Kernel/Workspace 相同。

生产还需加入 PVC、Hub 数据库持久化、TLS、镜像预构建、空闲回收、Quota、
动态凭证以及可执行 NetworkPolicy 的 CNI。
