# 实际验证报告

验证时间：2026-11-10；环境：腾讯云 TKE `cls-56b8021o`，namespace `jupyter-poc`。

## 已通过

- Jupyter Server 与 Kernel 位于不同 Pod，Kernel 由 Kubernetes Provisioner 创建。
- 集群内真实启动 PostgreSQL 16、MySQL 8.4、MongoDB 7、Elasticsearch 8.15.5，并写入 mock 数据。
- 独立 Kernel 经 Data Gateway 成功查询四种后端。
- PostgreSQL/MySQL 只接受单条只读 SQL，DDL 被拒绝。
- MongoDB `$where`、Elasticsearch script 类可执行查询能力被拒绝。
- Gateway 审计仅记录 subject 哈希、关联 ID、后端、操作、query fingerprint、耗时、行数和结果，不记录原始语句。
- 数据库凭证只注入 Gateway；Kernel 没有数据库密码。
- UEM 合法事件返回 202；含 `code` 等敏感属性的事件返回 422。
- 预构建 JupyterLab UEM 扩展和 Jupyter Server 转发扩展均加载成功；Headless Chrome 实际打开 Lab 后，collector 收到浏览器产生的 `lab_ready`。
- Mock OIDC Authorization Code 流程完成，JupyterHub 创建并登录 `poc-user`，最终 `/hub/home` 返回 200。

## 未通过：TKE 网络隔离

NetworkPolicy 对象已创建，但从现有 Kernel Pod 到四个后端的 TCP 连接全部成功。因此当前 TKE Serverless/EKS 数据面没有执行这些 Kubernetes NetworkPolicy，不能把“对象存在”当作网络隔离成功。

当前仍有数据库认证这一层：Kernel 没有后端密码，无法完成数据库登录；但生产验收要求网络层也失败。下一步应在腾讯云侧启用/配置适用于 Serverless Pod 的安全组或网络 ACL，或迁移到确认支持所选 NetworkPolicy provider 的节点池，然后重新运行 `tests/platform_smoke.py`，直到四项均显示 `DIRECT_BLOCKED`。

## SSO 范围

本轮验证了外部 OIDC 到 JupyterHub 的登录、state、PKCE code challenge、token/userinfo 和用户创建。默认 LocalProcessSpawner 无法为容器内不存在的 Linux 用户启动 Server，这是预期边界；生产应替换为 KubeSpawner/平台自有 Spawner。现有 Kubernetes Provisioner 仍负责 Server 内的 Kernel Pod，不应拿它替代 Hub 的用户 Server Spawner。
