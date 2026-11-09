# 架构设计

## 目标

为数据/AI 平台提供动态 Jupyter 运行能力，同时将交互入口与用户代码执行面
隔离。用户代码只在独立 Kernel Pod 中运行，平台可以对 Kernel 设置独立的
资源、身份、调度和网络策略。

## 组件

### Jupyter Server Pod

- 承载 JupyterLab UI、Contents、Sessions 和 Kernel Manager。
- 安装 `gateway-provisioners[k8s]`。
- 使用专用 ServiceAccount，通过 Kubernetes API 管理 Kernel Pod。
- 接收 Kernel 回传的连接信息，并通过 ZMQ 与 Kernel 通信。

### KubernetesProvisioner

- 由 kernelspec 的 `metadata.kernel_provisioner` 选择。
- 根据 Kernel ID 创建唯一 Pod。
- 监控启动状态、处理中断/终止，并在 Kernel 关闭时删除 Pod。
- 不需要独立 Gateway 服务。

### Kernel Pod

- 每个 Kernel 对应一个 Pod。
- 运行用户提交的 Python 代码。
- 使用独立 CPU、内存、GPU、ServiceAccount 与网络边界。
- 通过动态 ZMQ 端口与 Jupyter Server 通信。

## 请求流程

```text
1. Browser -> Jupyter Server: POST /api/sessions 或 /api/kernels
2. Jupyter Server -> Provisioner: start_kernel(kernel_id)
3. Provisioner -> Kubernetes API: create Pod
4. Kernel Pod -> Jupyter Server: 回传加密连接信息（端口 8877）
5. Jupyter Server <-> Kernel Pod: ZMQ channels
6. 用户关闭 Kernel
7. Provisioner -> Kubernetes API: delete Pod
```

## 扩展模型

```text
Jupyter Server
├── Kernel Pod A: Python / 1 CPU / 2 GiB
├── Kernel Pod B: Python / 4 CPU / 16 GiB
└── Kernel Pod C: GPU / 8 CPU / 32 GiB
```

POC 使用共享 namespace。生产建议按租户或安全域划分 namespace，并让平台
控制面预创建 namespace、Quota、LimitRange、ServiceAccount 和网络策略。

## 状态与高可用

Jupyter Server 保存 Kernel Manager 状态。简单扩容多个 Jupyter Server 副本
不能自动获得高可用，必须解决会话粘性、Kernel 状态持久化和故障重连。

- Notebook 文件应放在 PVC、对象存储或版本库。
- Kernel 内存状态通常不保证跨 Pod/Server 故障恢复。

POC 证明了 Pod 分离和 provisioner 生命周期链路；它没有解决多租户认证、
调度公平性、镜像供应链、审计、持久化、HA、成本治理和完整网络隔离。

