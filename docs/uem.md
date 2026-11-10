# JupyterLab UEM 埋点设计

## 结论

采用“JupyterLab 前端扩展采集 → 同源 Jupyter Server Extension 接收 → 企业 UEM/OTel 后端转发”。浏览器不保存 UEM 写入密钥，也不声明最终用户身份。

```text
Lab extension ── POST /platform/telemetry/v1/events ──► Server extension
  batch/sample/retry/beacon                            schema/rate-limit/redact
                                                      current_user 补充身份
                                                               │
                                                               ▼
                                                    Huawei UEM / Collector
```

## 事件与隐私

采集 `lab_ready`、Notebook 激活、Kernel 启停/重启/死亡、Cell 执行耗时与结果、JS 异常、Web Vitals、REST/WebSocket 耗时。默认禁止 Notebook 源码、输出、原始 SQL、完整文件路径、Cookie/Token 和明文账号。用户标识由服务端根据登录身份生成稳定伪名。

前端使用 JupyterLab 官方 token/signal 观察 Notebook tracker、SessionContext 和 commands，避免依赖 DOM 文案或大面积 monkey patch。采集器应包含 schema 版本、批量、采样、超时、指数退避和队列上限，卸载时使用 `sendBeacon`。

Server Extension 校验当前登录、XSRF、schema、字段长度与速率，覆盖客户端身份字段，补充 deployment/workspace/user，再脱敏转发。服务端事件可同时写入 EventBus/结构化日志。

## 华为内部落地前需确认

- UEM SDK/协议、endpoint、应用标识和签名方式。
- 数据分级、保留期、用户告知与退出机制。
- 内部账号伪名化规则，以及是否允许服务端代理上报。
- 必须维度、采样率、告警和仪表盘口径。

当前仅定义 vendor-neutral adapter；获得内部规范后实现 `HuaweiUemExporter`，内部密钥和地址不提交 Git。

## 验收

- 首屏、Kernel 生命周期、Cell 成败和 JS 异常可查询。
- UEM 故障不影响 Notebook/Kernel 主链路；断网不无限占用内存。
- 抓包和样本中无源码、输出、Token、原始 SQL、明文用户名。
- 客户端伪造 user ID 时，服务端仍记录真实登录身份。

参考：[JupyterLab Extension Points](https://jupyterlab.readthedocs.io/en/latest/extension/extension_points.html)、[Jupyter Server EventBus](https://jupyter-server.readthedocs.io/en/latest/api/jupyter_server.services.events.html)、[结构化日志](https://jupyter-server.readthedocs.io/en/latest/operators/configuring-logging.html)。
