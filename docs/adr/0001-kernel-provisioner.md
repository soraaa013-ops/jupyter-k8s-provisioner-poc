# ADR-0001：使用 Kernel Provisioner 分离 Jupyter Server 与 Kernel

- 状态：Accepted for POC
- 日期：2026-11-09

## 背景

平台需要限制用户代码对生产网络和集群资源的访问。如果 Kernel 与 Jupyter
Server 位于同一 Pod，就无法只对 Kernel 设置独立网络、身份和资源边界。

## 决策

使用 Jupyter Client Kernel Provisioner API，以及官方
`gateway-provisioners` 的 `KubernetesProvisioner`。Jupyter Server 位于一个
Pod，每个 Kernel 位于独立 Pod。不部署 Enterprise Gateway。

## 理由

- Provisioner 是 Jupyter Client 的标准扩展点。
- JupyterLab 仍使用原生 sessions/kernels API。
- 每个 Kernel 可独立设置资源、镜像、身份、调度和网络策略。
- 少一个长期运行的 Gateway 服务和额外跳转层。

## 代价

- Jupyter Server 必须访问 Kubernetes API并持有创建 Pod 的权限。
- Jupyter Server 与 Kernel 必须网络互通。
- Kernel 管理状态依赖 Jupyter Server；HA和恢复需额外设计。
- 需要维护兼容的 kernelspec、launcher 和 Kernel 镜像。

未选择同 Pod 本地 Kernel（不满足隔离）、Enterprise Gateway（本 POC明确使用
直接 Provisioner）和自研 Kernel 协议代理（重复标准能力且成本高）。

该决策仅覆盖实验 001，不排除后续并行比较。Enterprise Gateway 备选已在
`ADR-0002` 中重新打开，状态为 Proposed，不修改本 ADR 的历史结论。

