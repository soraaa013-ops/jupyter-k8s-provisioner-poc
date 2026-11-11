# Jupyter 架构与扩展面

```text
Browser: JupyterLab UI + frontend extensions
              │ HTTPS / REST / WebSocket
              ▼
Jupyter Server: auth, Contents, Sessions, Kernels, Server Extensions
              │ Kernel Provisioner
              ▼
Kernel Pod: ipykernel + user code
              │ controlled egress
              └────────► SQL Proxy / storage / compute
```

JupyterLab 是浏览器前端；Jupyter Server 是 HTTP/WebSocket 控制面；Kernel 是执行用户代码的计算面。Notebook 是文档，Kernel 是有状态进程，Session 将文档与 Kernel 关联。Kernel Provisioner 是 KernelManager 与运行环境之间的扩展点，本项目用它创建独立 Kernel Pod。

本项目同时保留三种部署模型：

| 模型 | Server/Kernel | Terminal | 状态 |
| --- | --- | --- | --- |
| 直接 Kubernetes Provisioner | 分 Pod | Server 本地 | 已实测 |
| KubeSpawner Workspace | 同一用户 Workspace | 原生且同环境 | 已实测 |
| Enterprise Gateway | 分 Pod，经集中 Gateway | Server 本地，安全模式需禁用 | 已调研、待实测 |

Enterprise Gateway 路线详见 [`enterprise-gateway-option.md`](enterprise-gateway-option.md)。它集中远程 Kernel
管理，但不提供远程 Terminal，也不能替代 UEM/插件可信后端。

## 平台扩展点

| 诉求 | 推荐扩展点 |
| --- | --- |
| 页面行为、首屏、Notebook/Kernel 状态 | JupyterLab 前端扩展 |
| 接收 UEM、补充身份、服务端审计 | Jupyter Server Extension |
| 登录和用户模型 | JupyterHub/OAuthenticator 或 Server `IdentityProvider` |
| 独立 Kernel Pod | Kernel Provisioner |
| Kernel 网络与资源隔离 | Kubernetes NetworkPolicy/Quota |
| 数据库凭证、SQL 策略与审计 | 独立 SQL Proxy 信任域 |

## 信任边界

1. 浏览器数据可被修改，服务端不能信任客户端声明的 user ID。
2. Server 是控制面，可持有平台身份，但不能把数据库长效凭证交给 Kernel。
3. Kernel 执行任意代码，必须假设用户能读取其文件、环境变量并扫描网络。
4. Service 只提供稳定地址，不是安全边界；限制依赖 NetworkPolicy、认证和目标侧授权。
5. UEM、SSO、SQL 审计共享关联 ID，但分别执行数据最小化。

生产建议由 JupyterHub 负责多用户登录、授权和拉起单用户 Server；Provisioner 为 Kernel 会话创建计算 Pod；SQL Gateway 与遥测采集器作为独立基础服务扩缩容。

参考：[Jupyter Server 架构](https://jupyter-server.readthedocs.io/en/latest/developers/architecture.html)、[认证 API](https://jupyter-server.readthedocs.io/en/latest/api/jupyter_server.auth.html)、[Server Extension](https://jupyter-server.readthedocs.io/en/stable/developers/extensions.html)、[JupyterLab 扩展点](https://jupyterlab.readthedocs.io/en/latest/extension/extension_points.html)。
