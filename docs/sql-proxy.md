# 多 Pod 模式下的 SQL Proxy

## 关键结论

Kernel 在独立 Pod 后，它的 `127.0.0.1` 只属于 Kernel Pod。即使 SQL Proxy 是 Jupyter Server Pod 的 sidecar，Kernel 也必须经 Kubernetes Service（如 `sql-proxy.jupyter-poc.svc:5432`）访问，不能连接 localhost。

```text
Jupyter Server Pod
  ├─ jupyter-server
  └─ sql-proxy（持有/动态获取 DB 凭证）
          ▲
          │ ClusterIP + 短期会话身份
Kernel Pod┘
  ├─ NetworkPolicy 只允许到 Proxy
  └─ 禁止直连数据库

sql-proxy ── TLS/mTLS ──► allowlist 数据库
```

Sidecar 方案满足本次 POC，但 Proxy 与 Server 同生共死，扩容后也会出现多个实例。生产更适合独立 SQL Gateway Deployment（按租户/安全域部署），配置 Service、HPA/PDB 和独立审计存储。

若强制要求 Kernel 使用 localhost，只能把 Proxy sidecar 放进每个 Kernel Pod；同 Pod 容器共享网络命名空间，因此这不是强凭证隔离。凭证仍需 workload identity/动态令牌，不能进入 Kernel 可读 volume。

## Proxy 职责

- Kernel 使用短期 session token 或 mTLS 身份；Proxy 映射到数据库角色。
- allowlist database/schema/operation，限制并发、超时、返回行数与大小。
- 协议级解析并阻止多语句和危险 DDL/DCL，不能只靠正则。
- 审计用户伪名、workspace/kernel、目标库、操作、规范化 fingerprint、耗时、行数和结果。
- 原始 SQL 可能含 PII/密钥，默认不落日志；确需留存需审批、加密和保留期。
- Proxy egress 仅到批准数据库；Kernel egress 不能绕过 Proxy。

## 选型

| 场景 | 候选 | 边界 |
| --- | --- | --- |
| PostgreSQL 连接池 | PgBouncer | 不等于完整 SQL 策略/审计网关 |
| MySQL 协议规则 | ProxySQL | query rules 可用；审计与授权需按版本核实 |
| 多数据库统一策略 | 自研/公司内部协议感知 Gateway | 成本较高，身份、策略、审计可统一 |

POC 建议先选 PostgreSQL，证明凭证隔离、网络不可绕过和审计闭环，再考虑多协议。

## 验收矩阵

1. Kernel 经 Service 执行允许的只读查询。
2. Kernel 文件、环境变量和 `/proc` 中没有 DB 长效密码。
3. Kernel 直连 DB IP/端口失败，直连 Server 其他端口失败。
4. 伪造身份、过期 token、越权 schema、DDL、多语句和超时查询被拒绝并审计。
5. Proxy 异常时默认关闭访问，不回退为直连。
6. 日志含统一关联 ID，但无凭证和默认禁记的原始 SQL。
