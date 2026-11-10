# 部署与运维

## 部署

综合 POC 先部署 mock 数据源、Gateway、OIDC 和扩展 ConfigMap，再部署 JupyterLab：

```bash
kubectl apply -k deploy/platform-poc
kubectl apply -k deploy/base
kubectl -n jupyter-poc rollout status deploy/jupyterlab --timeout=300s
kubectl -n jupyter-poc get pods -L component,kernel_id
```

POC 启动时从腾讯云 PyPI 镜像安装 provisioner。首次 Serverless Pod 创建和
镜像拉取可能需要 1～3 分钟。

## 创建 Kernel 验证

进入 UI 选择 `Kubernetes Python`，或调用 API：

```bash
kubectl -n jupyter-poc port-forward svc/jupyterlab 8888:8888
curl -X POST 'http://127.0.0.1:8888/api/kernels?token=poc-only-change-me' \
  -H 'Content-Type: application/json' \
  -d '{"name":"k8s_python"}'
kubectl -n jupyter-poc get pods -L component,kernel_id
```

## 诊断顺序

```bash
kubectl -n jupyter-poc get pods -o wide
kubectl -n jupyter-poc get events --sort-by=.lastTimestamp
kubectl -n jupyter-poc logs deploy/jupyterlab --tail=200
kubectl -n jupyter-poc describe pod -l component=kernel
kubectl -n jupyter-poc auth can-i create pods \
  --as=system:serviceaccount:jupyter-poc:jupyterlab
```

- `ImagePullBackOff`：仓库不可达、镜像不存在或缺少凭据。
- Kernel 500 + connection timeout：镜像太慢、Pod 失败或回连被阻断。
- kernelspec 不出现：entry point 未注册或安装目录无权限。
- Ready 假阳性：需要真实 readiness；本项目使用 TCP 8888。

生产应通过企业 Ingress、TLS、SSO/OIDC、WebSocket 超时和访问日志接入。

## 清理

以下命令会删除 namespace 中全部 Notebook/Kernel 数据：

```bash
kubectl delete namespace jupyter-poc
```

升级时应回归创建、执行、中断、重启、删除、Server 重启后的孤儿清理与网络
隔离，并验证 Jupyter Server、jupyter_client、gateway-provisioners、Python
Kubernetes client 和 Kernel 镜像的版本组合。

## 综合平台验证

四种后端和控制组件都应为 Ready。自动化数据访问与隔离测试在 Kernel Pod 中运行：

```bash
kernel_pod=$(kubectl -n jupyter-poc get pod -l component=kernel -o jsonpath='{.items[0].metadata.name}')
kubectl -n jupyter-poc exec -i "$kernel_pod" -- python - < tests/platform_smoke.py
```

当前 TKE Serverless 环境中该测试预期因数据库端口仍可直连而失败；不能忽略此失败。测试详情见 `docs/validation-report.md`。

