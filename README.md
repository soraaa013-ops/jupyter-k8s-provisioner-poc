# Jupyter Platform POC

面向企业数据/AI 平台的 Jupyter 技术验证仓库。项目不再只验证“Jupyter Server 与 Kernel 分 Pod”，而是持续沉淀身份、安全、网络、可观测性和数据访问能力。

## 当前验证地图

| 编号 | 验证项 | 状态 | 入口 |
| --- | --- | --- | --- |
| 001 | Jupyter Server 与 Kernel 分 Pod | 已跑通 | [`deploy/base`](deploy/base)、[`docs/architecture.md`](docs/architecture.md) |
| 002 | JupyterLab UEM 埋点与上报 | Mock collector、Lab/Server 扩展已实测 | [`docs/uem.md`](docs/uem.md) |
| 003 | Kernel 经原生协议代理访问数据源 | PgBouncer/ProxySQL/HAProxy/Nginx 已实测；TKE 网络隔离未通过 | [`docs/sql-proxy.md`](docs/sql-proxy.md) |
| 004 | 企业 SSO 接入 | Mock OIDC → JupyterHub 登录已实测 | [`docs/sso.md`](docs/sso.md) |
| 005 | Workspace Pod 与平台密钥隔离 | KubeSpawner、原生 Kernel/Terminal 已实测 | [`docs/workspace-isolation.md`](docs/workspace-isolation.md) |
| 006 | Enterprise Gateway 远程 Kernel 备选 | 已调研、待部署验证 | [`docs/enterprise-gateway-option.md`](docs/enterprise-gateway-option.md) |

整体组件边界见 [`docs/jupyter-architecture.md`](docs/jupyter-architecture.md)，后续顺序和验收标准见 [`docs/poc-roadmap.md`](docs/poc-roadmap.md)。
集群实际测试结果（包括没有通过的 NetworkPolicy）见 [`docs/validation-report.md`](docs/validation-report.md)。

## 方案评审入口

- [`docs/current-poc-summary.md`](docs/current-poc-summary.md)：当前已完成 POC、DB Proxy、Pod 分离与失败项整理。
- [`docs/target-architecture.md`](docs/target-architecture.md)：引入 Enterprise Gateway 后的生产目标方案与上线验收门。

## 源码在哪里

| 模块 | 源码 | 作用 |
| --- | --- | --- |
| 原生数据代理 | [`src/native-proxies`](src/native-proxies) | PgBouncer、ProxySQL、Mongo TCP 与 ES HTTP 代理配置 |
| UEM Collector | [`src/uem-collector/app.py`](src/uem-collector/app.py) | UEM schema、敏感字段拒绝与 mock 汇总 |
| JupyterLab UEM | [`src/extensions/jupyterlab-poc-uem/src/index.ts`](src/extensions/jupyterlab-poc-uem/src/index.ts) | 浏览器事件采集 |
| Jupyter Server UEM | [`src/extensions/jupyter-server-poc-telemetry/poc_telemetry.py`](src/extensions/jupyter-server-poc-telemetry/poc_telemetry.py) | 登录态校验与同源转发 |
| Mock OIDC | [`src/mock-oidc/app.py`](src/mock-oidc/app.py) | Authorization Code、JWT、JWKS、userinfo |
| 集群测试 | [`tests/platform_smoke.py`](tests/platform_smoke.py) | 正向查询与安全负向测试 |
| Workspace 测试 | [`tests/workspace_smoke.py`](tests/workspace_smoke.py) | 同 Pod Kernel/Terminal 与平台密钥隔离验证 |

Kubernetes 清单只放在 [`deploy/`](deploy/)；公司环境替换清单见 [`docs/company-adoption-guide.md`](docs/company-adoption-guide.md)。

## 核心原则

- 浏览器、Jupyter Server、Kernel 和外部数据源是不同信任域。
- Kernel 运行用户代码，默认按不可信工作负载处理。
- 数据库管理员/高权限长效凭证不进入 Notebook、Kernel 环境变量或镜像；原生驱动所需的代理侧/短期凭证通过受控方式注入或签发。
- 审计、身份和链路使用统一关联 ID，但默认不采集代码、输出、原始 SQL 和明文个人信息。
- 每个 POC 必须留下可复现部署、正反向安全测试和生产化差距。

## 已部署环境

腾讯云 TKE 集群 `cls-56b8021o`，API Server 内网地址 `10.0.0.8`；现有实验命名空间为 `jupyter-poc`。详情见 [`docs/cluster-profile.md`](docs/cluster-profile.md)。仓库不保存 kubeconfig、客户端证书或私钥。

## 快速开始（实验 001）

```bash
kubectl apply -k .
kubectl -n jupyter-poc rollout status deployment/jupyterlab
kubectl -n jupyter-poc port-forward service/jupyterlab 8888:8888
```

打开 `http://127.0.0.1:8888/lab`。操作说明见 [`docs/operations.md`](docs/operations.md)。

根目录 Kustomize 会启动临时 PostgreSQL、MySQL、MongoDB、Elasticsearch、四种原生代理、UEM collector、mock OIDC 和 JupyterHub，仅供 POC；其中 Secret 均为公开的 mock 值，不可用于真实环境。
