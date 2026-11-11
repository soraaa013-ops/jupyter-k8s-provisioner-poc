# Kubernetes manifests

- `base/`：Jupyter Server、Kubernetes Provisioner、RBAC、Service 和 Kernel NetworkPolicy。
- `platform-poc/`：四种 mock 数据源、原生协议代理、UEM collector、mock OIDC、JupyterHub 和补充网络策略。

完整部署必须从仓库根目录执行：

```bash
kubectl apply -k .
```

根目录 `kustomization.yaml` 会从 `src/` 生成运行所需 ConfigMap。单独执行 `kubectl apply -k deploy/platform-poc` 不包含源码 ConfigMap，不能作为完整安装方式。

生产环境应将源码构建进不可变镜像，不能继续使用 ConfigMap 挂代码或容器启动时在线安装依赖。
