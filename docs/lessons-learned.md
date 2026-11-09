# 踩坑记录

## 1. kubeconfig 指向错误内网地址

访问 `10.0.0.3:443` 一直超时，实际 TKE API Server 是 `10.0.0.8`。经验：
先在控制台核对 endpoint，再排查证书、RBAC和应用。

## 2. 同在腾讯云不等于同一私网

私网 IP 只有结合 VPC 才有意义。跨 VPC 需要云联网/对等连接、双向非重叠
路由和安全策略。本次通过 CCN 连接 `10.3.0.0/22` 与 `10.0.0.0/24`。

## 3. 公网仓库可达性不一致

EKS 拉取 Quay 超时，但 Docker Hub 成功。公网访问必须按具体仓库测试。
默认 PyPI 卡住，腾讯云 PyPI 镜像可用。生产应预构建镜像。

## 4. Kernel 镜像不等于 provisioner 包

`elyra/kernel-py:3.3.0` 包含 Kernel bootstrap，但 Jupyter Server 侧仍需安装
`gateway-provisioners` entry point。

## 5. kernelspec 安装权限被静默忽略

默认写 `/usr/local/share/jupyter/kernels`。非 root 无权限时 0.5.0 只打印
“Installing”并返回 0。必须使用 `--user`，再执行 `jupyter kernelspec list`。

## 6. Serverless 首次拉镜像超过默认超时

默认 30 秒内未回传 connection file，provisioner 删除 Kernel Pod并返回 500。
当前实现应设置 `GP_LAUNCH_TIMEOUT=180`，不能只依赖旧模板变量名。

## 7. Readiness 假阳性与认证 403

没有 probe 时 pip 仍在安装，Pod 已被视为 Ready。受 token 保护的
`/api/status` 返回 403，因此 POC 使用 TCP 8888 readiness。

## 8. CBS RWO 在 EKS Pod 间切换慢

上传 Pod写入 CBS 后，磁盘长期 DETACHING/ATTACHING。Serverless 卷生命周期
需要独立压测，不能照搬普通节点经验。

## 9. NetworkPolicy 对象存在不代表隔离生效

策略创建成功，但 Kernel 实测仍可连接 Kubernetes API。必须做数据面连通性
测试，不能只检查 `kubectl get networkpolicy`。

## 10. 默认本地 Kernel 会破坏隔离目标

基础镜像仍带 `python3` kernelspec。选择它会在 Jupyter Server Pod 内启动
Kernel。生产必须只暴露批准的远程 kernelspec。

