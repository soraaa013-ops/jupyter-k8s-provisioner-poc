# ADR-0002：保留 Enterprise Gateway 作为远程 Kernel 备选

- 状态：Proposed / Research complete, implementation pending
- 日期：2026-11-11

## 背景

直接 Kubernetes Provisioner 已证明 Server/Kernel 分 Pod；Workspace 模式已证明
原生 Terminal 与平台密钥隔离。公司环境还可能需要集中 Kernel 控制、Spark/YARN、
Gateway HA、统一策略和减少每个 Server 的 Kubernetes RBAC，因此需要保留 EG
路线进行对比验证。

## 提议

新增独立 EG POC，不替换已有实现。JupyterHub 管理用户 Server，Server 禁用
Terminal 和本地 Kernel，只能经带可信身份绑定的 EG 启动远程 Kernel Pod。
系统插件数据库密钥继续放在独立 Collector/Plugin Backend，而不是 Server 或
Kernel。

## 验收前不做的结论

- 不把 EG 默认共享 token 当作多租户认证。
- 不声称 EG 支持远程 Terminal。
- 不声称增加 EG 副本就完成 Kernel 会话 HA。
- 不因 Kernel 无法读取 Server 环境，就允许插件把高权限数据库接口暴露给用户。
- 不把 main/3.4-dev 文档中的能力计入稳定版 3.3.0 验收。

## 决策门

只有 [`../enterprise-gateway-option.md`](../enterprise-gateway-option.md) 的最小链路、安全负向测试和故障测试通过
后，才能把状态改为 Accepted。若 EG 认证层、版本兼容或运维成本不可接受，维持
Workspace/直接 Provisioner 路线。
