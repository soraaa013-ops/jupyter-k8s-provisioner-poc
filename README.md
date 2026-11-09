# Jupyter Kubernetes Provisioner POC

在 Kubernetes 中运行 JupyterLab，并让每个 Kernel 运行在独立 Pod 中。

本项目使用 Jupyter Client Kernel Provisioner 和官方
`gateway-provisioners` 的 `KubernetesProvisioner`，**不部署 Jupyter
Enterprise Gateway**。

```text
Browser
   │ HTTP/WebSocket
   ▼
JupyterLab + Jupyter Server Pod
   │
   ├── Kubernetes API：创建、监控、删除 Kernel Pod
   └── ZMQ：与 Kernel 通信
          ▼
     Kernel Pod A / B / C ...
```

## 当前验证结果

- JupyterLab 与 Kernel 运行在不同 Pod。
- 一个 Jupyter Server 可以创建多个独立 Kernel Pod。
- Kernel 创建、连接信息回传和生命周期管理已在腾讯云 TKE Serverless 集群实测通过。
- Namespace 级最小 RBAC 已验证。
- `NetworkPolicy` 对象能创建，但当前 EKS Serverless 环境没有阻断 Kernel 到 Kubernetes API 的网络连接，不能作为生产隔离依据。
- Kernel Pod 已禁用 ServiceAccount token 自动挂载，减少 API 可达带来的风险。

## 快速部署

```bash
kubectl apply -k deploy/base
kubectl -n jupyter-poc rollout status deployment/jupyterlab --timeout=300s
kubectl -n jupyter-poc get pods -L component,kernel_id
```

当前 POC 在 JupyterLab 启动时从腾讯云 PyPI 镜像安装
`gateway-provisioners[k8s]==0.5.0`，并使用公开镜像：

- JupyterLab：`docker.io/jupyter/base-notebook:python-3.11`
- Kernel：`docker.io/elyra/kernel-py:3.3.0`

生产环境必须改为内部构建、扫描、签名并固定 digest 的镜像。

## 访问

```bash
kubectl -n jupyter-poc port-forward service/jupyterlab 8888:8888
```

打开 `http://127.0.0.1:8888/lab?token=poc-only-change-me`。

选择 `Kubernetes Python` 才会创建独立 Kernel Pod。默认 `python3` 是本地
Kernel，生产环境必须删除或禁用。

## 文档

- [架构设计](docs/architecture.md)
- [POC 集群画像](docs/cluster-profile.md)
- [网络与安全](docs/network-security.md)
- [部署与运维](docs/operations.md)
- [踩坑记录](docs/lessons-learned.md)
- [生产化路线](docs/production-roadmap.md)
- [架构决策记录](docs/adr/0001-kernel-provisioner.md)

## 安全说明

当前固定 token、运行时安装依赖、`emptyDir` 工作区和单副本 Jupyter Server
均只适用于 POC。不要原样部署到生产环境。

