# 实际验证报告

## Enterprise Gateway：尚未验证

Enterprise Gateway 当前只有架构调研和验收设计，未部署到本 TKE 集群，也没有
产生运行测试结果。不得将 `docs/enterprise-gateway-option.md` 的目标能力视为已
通过项；后续实测结果将在独立章节记录。

## Workspace Pod：通过

JupyterHub 5.3 + KubeSpawner 7.0.0 已在 TKE 创建 `workspace-poc-user`。从该
Pod 内通过 Jupyter 原生 API 创建 Kernel 和 Terminal，实测输出：

```text
WORKSPACE_KERNEL_OK:workspace-poc-user:jovyan
WORKSPACE_TERMINAL_OK:workspace-poc-user:jovyan
```

Workspace 未挂载 Kubernetes ServiceAccount token，也没有
`OAUTH_CLIENT_SECRET`、`HUB_ADMIN_TOKEN`、`UEM_COLLECTOR_TOKEN`。它仍包含
JupyterHub 为当前用户 Server 签发的受限 API token，这是用户工作区凭证而非
平台管理密钥。

RBAC 实测：Hub ServiceAccount 可创建 Pod 但不能读取 Secret；Workspace
ServiceAccount 不能读取 Pod 或 Secret。

网络负向测试未通过：Workspace 仍能连接 `mock-mysql:3306`。这再次证明当前
TKE Serverless 环境没有执行已提交的 NetworkPolicy；Workspace 模式解决了密钥
和 Kubernetes 身份隔离，但没有自动解决 CNI/Pod 出口隔离。

验证时间：2026-11-10；环境：腾讯云 TKE `cls-56b8021o`，namespace `jupyter-poc`。

## 已通过

- Jupyter Server 与 Kernel 位于不同 Pod，Kernel 由 Kubernetes Provisioner 创建。
- 集群内真实启动 PostgreSQL 16、MySQL 8.4、MongoDB 7、Elasticsearch 8.15.5，并写入 mock 数据。
- 独立 Kernel 使用原生 `psycopg` 经 PgBouncer 查询 PostgreSQL 成功。
- 独立 Kernel 使用原生 PyMySQL 经 ProxySQL 查询 MySQL 成功。
- 独立 Kernel 使用 PyMongo 经 HAProxy 查询 MongoDB 成功。
- 独立 Kernel 使用 Elasticsearch Python client 经 Nginx 查询成功。
- ProxySQL 已生成 JSON query event 和 digest；该模式包含原始 SQL，仅用于 POC，生产需按数据分级决定是否启用。
- PgBouncer 1.25.2 使用 session pooling，原生 psycopg 行为验证通过。
- UEM 合法事件返回 202；含 `code` 等敏感属性的事件返回 422。
- 预构建 JupyterLab UEM 扩展和 Jupyter Server 转发扩展均加载成功；Headless Chrome 实际打开 Lab 后，collector 收到浏览器产生的 `lab_ready`。
- Mock OIDC Authorization Code 流程完成，JupyterHub 创建并登录 `poc-user`，最终 `/hub/home` 返回 200。

## 未通过：TKE 网络隔离

NetworkPolicy 对象已创建，但从新建 Kernel Pod 到四个后端及 TKE API Server 的 TCP 连接全部成功。集群为 `eklet` 超级节点，且没有 Calico/Cilium/Antrea 或腾讯云 `networkpolicy` 组件，因此当前没有数据面执行这些 Kubernetes NetworkPolicy。不能把“对象存在”当作网络隔离成功。

下一步应在腾讯云侧启用/配置适用于 Serverless Pod 的安全组或网络 ACL，或迁移到确认支持所选 NetworkPolicy provider 的节点池，然后重新运行 `tests/platform_smoke.py`，直到四项均显示 `DIRECT_BLOCKED`。

## 尚未完成：生产数据库授权

Mock 用户为了初始化方便仍拥有较高权限，而且 Kernel 使用的是演示密码。本轮只证明原生协议兼容和代理链路，不代表凭证隔离、只读授权或查询审计已经达到生产要求。公司环境必须创建最小权限 DB role、限制数据库只接受代理源地址，并确定短期凭证或工作负载身份方案。

## SSO 范围

本轮验证了外部 OIDC 到 JupyterHub 的登录、state、PKCE code challenge、token/userinfo 和用户创建。默认 LocalProcessSpawner 无法为容器内不存在的 Linux 用户启动 Server，这是预期边界；生产应替换为 KubeSpawner/平台自有 Spawner。现有 Kubernetes Provisioner 仍负责 Server 内的 Kernel Pod，不应拿它替代 Hub 的用户 Server Spawner。
