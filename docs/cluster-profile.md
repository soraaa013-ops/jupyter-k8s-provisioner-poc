# POC 集群画像

采集时间：2026-11-09，时区 Asia/Shanghai。以下内容只描述本次验证环境。

## 控制面

| 项目 | 值 |
|---|---|
| 云厂商 | 腾讯云 |
| 集群类型 | TKE Serverless / EKS |
| 集群 ID | `cls-56b8021o` |
| Kubernetes Server | `v1.36.2-tke.2` |
| API Server 内网端点 | `10.0.0.8:443` |
| API Server Service | `default/kubernetes-intranet` |
| Service ClusterIP | `192.168.0.1` |
| Pod/Serverless 子网 | `10.0.0.0/24` |
| 地域 | Singapore (`sg`) |
| 可用区 | `ap-singapore-1` / topology `900001` |

`10.0.0.3` 是最初 kubeconfig 中的错误/旧地址；实际内网 API Server 为
`10.0.0.8`。

## 计算

| 项目 | 值 |
|---|---|
| 节点实现 | `eklet` 虚拟节点 |
| Instance Type | `eklet` |
| Runtime | `eks://2.0` |
| 节点子网 | `subnet-l4yp2vhk` |
| GPU | 本次节点标签均显示不可用 |

这是 Serverless 调度模型。镜像拉取、CBS 挂载/解绑、网络策略等行为与普通
CVM 节点可能不同。

## 存储与入口

| 项目 | 值 |
|---|---|
| 默认 StorageClass | `cbs` |
| Provisioner | `com.tencent.cloud.csi.cbs` |
| Volume Binding | `Immediate` |
| 默认 IngressClass | `qcloud` |
| Ingress Controller | `cloud.tencent.com/ingress-controller` |

POC 的 Notebook 工作目录使用 `emptyDir`，Pod 替换后数据会丢失。

## 已部署资源

Namespace `jupyter-poc` 中包含 JupyterLab Deployment/Service、专用
ServiceAccount 和 namespace Role、三条 Kernel NetworkPolicy，以及独立
Kernel Pod。Kernel 具有 `component=kernel` 和 `kernel_id=<uuid>` 标签。

## 网络验证

从 Kernel Pod实测：

| 目标 | 结果 |
|---|---|
| JupyterLab Service:8888 | 可连接（期望） |
| Kubernetes Service `192.168.0.1:443` | **可连接（不期望）** |
| API 内网端点 `10.0.0.8:443` | **可连接（不期望）** |
| `1.1.1.1:443` | 超时 |
| CoreDNS | 可解析 |

当前环境不能仅依赖 Kubernetes NetworkPolicy 保护 Kernel。公网超时也不能
单独证明 NetworkPolicy 生效，可能由 Serverless 子网出口策略造成。

