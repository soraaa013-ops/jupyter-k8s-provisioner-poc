# Source code

本目录包含 POC 的可执行实现，不包含 Kubernetes 资源定义。

```text
src/
├── data-gateway/                     # 多数据源访问、策略和审计
│   ├── app.py
│   └── requirements.txt
├── mock-oidc/                        # 仅供测试的 OIDC Provider
│   ├── app.py
│   └── requirements.txt
└── extensions/
    ├── jupyterlab-poc-uem/           # TypeScript 前端扩展和预构建产物
    │   ├── src/index.ts
    │   └── labextension/
    └── jupyter-server-poc-telemetry/ # Python Server Extension
        └── poc_telemetry.py
```

## Data Gateway API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/v1/sql/postgres` | 参数化只读 PostgreSQL 查询 |
| POST | `/v1/sql/mysql` | 参数化只读 MySQL 查询 |
| POST | `/v1/document/mongo/find` | 受限 MongoDB find |
| POST | `/v1/search/elasticsearch` | 受限 Elasticsearch search |
| POST | `/v1/uem/events` | UEM schema 校验和接收 |
| GET | `/v1/uem/summary` | POC 内存汇总 |

所有非健康检查接口要求 Bearer token。SQL 只允许单条只读语句；Mongo/ES 禁止可执行脚本类查询。当前鉴权和解析足够验证架构，不是生产级 SQL 防火墙。

## 构建 JupyterLab 扩展

```bash
cd src/extensions/jupyterlab-poc-uem
npm ci
npm run build
build-labextension --core-path /path/to/jupyterlab/staging .
```

预构建产物提交在 `labextension/`，由根目录 Kustomize 生成为 ConfigMap 并挂载到 JupyterLab。
