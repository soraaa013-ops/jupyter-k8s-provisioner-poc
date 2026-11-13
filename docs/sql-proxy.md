# 原生数据库代理设计

## 目标

Notebook 使用标准数据库驱动，代理前后代码基本一致：

```python
# PostgreSQL
psycopg.connect(host="postgres-proxy", port=5432, dbname="analytics", ...)

# MySQL
pymysql.connect(host="mysql-proxy", port=6033, database="analytics", ...)

# SQLAlchemy/pandas 仍使用标准 PostgreSQL 或 MySQL URL。
```

不能要求用户将 SQL 封装成自定义 HTTP 请求。本项目已经移除早期的自研 SQL HTTP API。

## 已部署链路

```text
Kernel + psycopg ── PostgreSQL wire protocol ──► PgBouncer:5432 ──► PostgreSQL
Kernel + PyMySQL ── MySQL wire protocol ───────► ProxySQL:6033  ──► MySQL
Kernel + PyMongo ── Mongo wire protocol ───────► HAProxy:27017  ──► MongoDB
Kernel + ES SDK  ── Elasticsearch HTTP API ────► Nginx:9200     ──► Elasticsearch
```

代理以独立 Deployment/Service 运行，不放在 Jupyter Server Pod。Kernel 独立成 Pod 后，Server Pod 的 localhost 对 Kernel 不可见；稳定入口必须是 Service 或公司内部代理域名。

## 能力边界

| 代理 | 用户兼容性 | 连接池 | 查询规则/路由 | 审计能力 | 不能解决 |
| --- | --- | --- | --- | --- | --- |
| PgBouncer | PostgreSQL 原生协议 | 强 | 很弱 | 连接/池统计 | SQL 防火墙、细粒度审计 |
| ProxySQL | MySQL 原生协议 | 强 | query rules、路由、超时 | digest 统计、JSON events log | 单独完成企业身份到 DB 身份映射 |
| HAProxy | Mongo wire 透明 TCP | 连接级 | L4 路由 | 连接日志 | Mongo 查询解析、字段级策略 |
| Nginx | ES REST API | HTTP keepalive | path/method/限流 | HTTP access log | Elasticsearch DSL 语义级授权 |

PgBouncer 官方定位是连接池：应用像连接 PostgreSQL 一样连接 PgBouncer。它不是查询审计产品。PostgreSQL 的只读、schema/table 权限、RLS 和审计应主要由数据库角色、`pg_hba.conf`、pgaudit/数据库日志承担。

ProxySQL 可以按 username/schema/digest/pattern 配置 query rules，并从 `stats_mysql_query_digest` 获取聚合统计。JSON events log 会包含原始 SQL；生产默认不应全量开启，除非数据分级、脱敏、加密、访问权限和保留期均已确认。

POC 只有一个固定 mock MySQL 后端，因此关闭了 ProxySQL monitor。生产应创建仅具备所需权限的专用 monitor 用户并启用后端健康检查；不要复用业务账号。

> 安全版本说明（2026-11-13）：POC 实测的 PgBouncer 1.25.2 不能作为生产基线。
> 官方 1.26.1 修复了认证绕过和两个客户端可触发的 DoS CVE；生产镜像至少使用
> 1.26.1 或后续已修复稳定版，并固定 digest、扫描和签名。

## 凭证模型

PgBouncer 和 ProxySQL 默认不会神奇地把“客户端身份”变成完全不同的数据库身份：客户端认证信息通常仍与后端用户关联。因此开源连接池本身不能同时保证“Kernel 不知道任何可用于数据库的凭据”和“透明原生协议”。

可选生产模型：

1. **代理账号 + 网络不可绕过**：Kernel 持有受限数据库用户凭据，只能访问代理；数据库只允许代理源地址。这是最容易落地的模型。
2. **短期数据库凭证**：平台为用户/Kernel 签发短期 DB token，代理负责池化；过期后不可复用。
3. **证书/SPIFFE/企业认证插件**：客户端到代理使用工作负载证书，代理映射后端身份。取决于 Proxy 版本、数据库和公司 IAM 能力。
4. **真正的凭证代理/公司数据网关**：如果强制要求 Kernel 完全不知道 DB 凭据，需要支持前后端身份映射的现成企业网关；PgBouncer 本身不是这个产品。

无论选择哪种模型，Kernel 直连数据库必须在网络上失败，否则用户可以绕过代理的连接限制、路由和审计。

## 透明性注意事项

### PgBouncer

POC 使用 `pool_mode=session`，兼容性最高。生产若切换 `transaction` pooling，需要回归：

- session-level `SET`、临时表、advisory lock；
- prepared statement 与驱动行为；
- LISTEN/NOTIFY；
- 事务边界、连接状态和 ORM 连接池。

### ProxySQL

需要回归：

- prepared statements；
- transaction persistence；
- session variables 和 `SET NAMES`；
- SQLAlchemy/JDBC/pandas；
- query rule 未误伤驱动握手语句；
- 配置从 MEMORY `LOAD ... TO RUNTIME`、`SAVE ... TO DISK` 的生命周期。

### MongoDB/Elasticsearch

HAProxy 保持 Mongo wire protocol，但无法做查询审计。需要 Mongo 查询级授权时，应使用 MongoDB 自身 RBAC/audit 或专用产品。

Elasticsearch 客户端本身使用 HTTP；Nginx 不改变 SDK。生产应由 Elasticsearch security role 限制 index/action，并在 Nginx/Ingress 限制 method、path、body size、并发和超时。

## POC 验收

运行前在 Kernel 环境安装标准驱动：

```bash
pip install 'psycopg[binary]' PyMySQL pymongo elasticsearch
python tests/native_proxy_smoke.py
```

已经实测四条原生客户端链路均返回 mock 数据。生产还必须验证：

1. Kernel 直连真实 DB IP/端口失败。
2. 代理异常时连接失败，不回退直连。
3. 只读 DB role 无法执行 DDL/DML，不能只依赖正则 query rule。
4. 每用户连接数、查询超时、结果大小和数据库 resource group 生效。
5. ORM、prepared statement、事务、临时表和 session state 兼容。
6. 审计能关联 user/workspace/kernel，但凭证和敏感 SQL 不进入普通日志。

参考：[PgBouncer usage](https://www.pgbouncer.org/usage)、[ProxySQL users](https://proxysql.com/documentation/users-configuration)、[ProxySQL query rules](https://proxysql.com/documentation/main-runtime/mysql-tables/)、[ProxySQL query logging](https://proxysql.com/documentation/query-logging/)。
