# Source code

本目录包含 POC 的可执行实现，不包含 Kubernetes 资源定义。

```text
src/
├── uem-collector/                    # UEM mock 接收、校验和汇总
│   ├── app.py
│   └── requirements.txt
├── mock-oidc/                        # 仅供测试的 OIDC Provider
│   ├── app.py
│   └── requirements.txt
├── native-proxies/                   # 开源原生协议代理配置
│   ├── pgbouncer.ini
│   ├── proxysql.cnf
│   ├── haproxy.cfg
│   └── nginx.conf
└── extensions/
    ├── jupyterlab-poc-uem/           # TypeScript 前端扩展和预构建产物
    │   ├── src/index.ts
    │   └── labextension/
    └── jupyter-server-poc-telemetry/ # Python Server Extension
        └── poc_telemetry.py
```

## 原生数据库连接

用户代码保持数据库驱动原有用法，只替换 host/port：

```python
psycopg.connect(host="postgres-proxy", port=5432, ...)
pymysql.connect(host="mysql-proxy", port=6033, ...)
MongoClient("mongodb://...@mongo-proxy:27017/")
Elasticsearch("http://elasticsearch-proxy:9200")
```

完整验证见 `tests/native_proxy_smoke.py`。

## UEM Collector API

| Method | Path | 功能 |
| --- | --- | --- |
| POST | `/v1/uem/events` | UEM schema 校验和接收 |
| GET | `/v1/uem/summary` | POC 内存汇总 |

## 构建 JupyterLab 扩展

```bash
cd src/extensions/jupyterlab-poc-uem
npm ci
npm run build
build-labextension --core-path /path/to/jupyterlab/staging .
```

预构建产物提交在 `labextension/`，由根目录 Kustomize 生成为 ConfigMap 并挂载到 JupyterLab。
