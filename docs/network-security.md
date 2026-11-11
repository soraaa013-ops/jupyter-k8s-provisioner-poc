# 网络与安全设计

## 威胁模型

Kernel 执行用户提供的任意代码，应按不可信工作负载处理。主要风险包括：

- 访问 Kubernetes API 和 ServiceAccount token。
- 扫描或攻击平台、数据库和其他租户 Pod。
- 访问云元数据服务并窃取临时凭据。
- 向公网外传数据或下载恶意载荷。
- 消耗 CPU、内存、GPU、IP 与存储资源。
- 利用特权容器、hostPath、hostNetwork 或高危 capability 逃逸。

## 允许的最小通信

```text
Browser -> Jupyter ingress: HTTPS/WebSocket
Jupyter Server -> Kubernetes API: Pod lifecycle
Jupyter Server <-> Kernel: connection response + dynamic ZMQ
Kernel -> DNS: TCP/UDP 53
Kernel -> approved data services: explicit allowlist only
```

## 当前 POC

`deploy/base/network-policy.yaml` 对 `component=kernel` 默认拒绝 ingress/egress，
仅放行 JupyterLab 双向通信和 kube-system DNS。

但是本次 TKE Serverless 实测发现 Kernel 仍能连接 Kubernetes API 和 mock
数据库。检查发现节点为 `eklet` 超级节点，集群中没有 Calico、Cilium、Antrea
等策略执行器，也没有腾讯云 `networkpolicy` 组件。API Server 接受并保存
NetworkPolicy，不代表数据面实际执行策略。

腾讯云 NetworkPolicy 是需要单独安装的集群组件；预期会在 `kube-system` 创建
名为 `networkpolicy` 的 DaemonSet。当前集群不存在该对象。公司环境排查命令：

```bash
kubectl -n kube-system get daemonset networkpolicy
kubectl get pods -A | grep -Ei 'calico|cilium|antrea|networkpolicy'
kubectl get nodes -o custom-columns=NAME:.metadata.name,RUNTIME:.status.nodeInfo.containerRuntimeVersion
```

超级节点 Pod 直接占用 VPC IP。如果 NetworkPolicy 组件不覆盖该节点类型，应改用
Pod 安全组/SecurityGroupPolicy；如果公司环境是普通节点且已有 Calico/Cilium，
继续使用本项目的 NetworkPolicy 即可。最终以 Kernel 内连通性测试为准。

## 生产要求

1. 选择并实测支持 NetworkPolicy 的 CNI，将连通性测试纳入持续验收。
2. Serverless 场景评估腾讯云安全组、Pod 安全组或独立子网 ACL。
3. Kernel 设置 `automountServiceAccountToken: false`。
4. 禁用 hostNetwork、hostPID、hostIPC、hostPath 和 privileged。
5. 使用 `runAsNonRoot`、只读根文件系统、seccomp RuntimeDefault、drop ALL。
6. 阻断云元数据地址 `169.254.169.254/32` 及厂商特定端点。
7. 数据服务使用目标 CIDR/端口白名单或 egress gateway。
8. 不允许用户直接修改 Pod模板、镜像、ServiceAccount、volume 或调度字段。
9. 配置 ResourceQuota、LimitRange、Pod 数量和每用户并发限制。
10. 记录用户、Kernel ID、镜像、资源和销毁审计事件。

Jupyter Server 的 ServiceAccount 只应管理 Kernel Pod。Kernel 使用无权限
ServiceAccount，且不挂载 token。生产平台不能直接信任浏览器传入的
`KERNEL_*` 环境变量。

镜像应进入内部仓库，固定 digest，生成 SBOM、扫描并签名。生产 Kernel 不应
在启动时在线安装软件，除非经过受控内部代理。

