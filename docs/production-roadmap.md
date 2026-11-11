# 生产化路线

## 阶段 0：POC（当前）

- [x] Jupyter Server 与 Kernel Pod 分离
- [x] KubernetesProvisioner 生命周期链路
- [x] Namespace RBAC和基础资源限制
- [x] 网络策略定义和实测
- [x] Workspace Pod 原生 Terminal/Kernel 与平台密钥隔离
- [x] Enterprise Gateway 备选架构调研
- [ ] Enterprise Gateway 最小链路与安全负向测试
- [ ] 代码执行、中断和重启自动化测试

## 阶段 1：可重复部署

- 内部构建 Jupyter Server 与 Kernel 镜像，固定 digest。
- Helm/Kustomize 环境分层，移除运行时 pip 安装。
- Secret 管理 token，随后接入 OIDC/SSO。
- Notebook PVC或对象存储持久化。
- 移除本地 `python3` kernelspec。
- 增加 smoke、RBAC、网络和资源限制测试。

## 阶段 2：平台 API

- Workspace API：创建、查询、暂停和删除 Jupyter Server。
- Kernel Policy：批准镜像、CPU/内存/GPU、并发和空闲回收。
- 用户/租户映射：namespace、ServiceAccount、Quota 与网络策略。
- 幂等 reconcile、最终状态、超时、重试和孤儿清理。
- 审计用户、workspace、kernel ID、镜像 digest、资源和时间线。

## 阶段 3：安全与多租户

- 在目标 CNI/安全组上证明 default-deny 有效。
- 独立 Kernel 子网或安全组，阻断控制面、元数据与生产网段。
- Pod Security Admission restricted、自定义准入策略。
- Workload Identity/短期凭据，禁止静态云密钥。
- 镜像签名、SBOM、漏洞门禁和 allowlist。
- 租户级成本、配额、优先级与公平调度。

## 阶段 4：可靠性与规模

- Jupyter Server 会话粘性和故障模型。
- Kernel 状态持久化/重连策略或明确不可恢复语义。
- 空闲 Kernel/Workspace culling。
- 预拉镜像、弹性容量和启动时延 SLO。
- 指标、日志、Tracing、告警、容量预测和故障演练。

## 上线门槛

1. Kernel 无 token 且无法连接 Kubernetes API和元数据服务。
2. 不同租户 Kernel 无法互访。
3. 所有镜像固定 digest、扫描并签名。
4. CPU、内存、GPU和 Pod 数量均有硬限制。
5. 关闭 Kernel 后资源可在规定时间内回收。
6. 关键生命周期有审计日志、指标和告警。
7. Notebook 数据有明确的持久化、备份和删除策略。

