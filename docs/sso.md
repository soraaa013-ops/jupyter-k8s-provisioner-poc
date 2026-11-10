# JupyterLab 企业 SSO 接入

## 推荐方案

多用户平台使用 `JupyterHub + OIDC/OAuth Authenticator + 单用户 Jupyter Server`。JupyterLab 不是单独的认证边界；浏览器先由 Hub 完成 OIDC Authorization Code 流程，Hub 按身份/工作区拉起 Server。

```text
Browser ─► JupyterHub ─► Enterprise IdP
             │ /hub/oauth_callback
             │ user/groups/roles
             ▼
       single-user Server ─► JupyterLab
             └─ Provisioner ─► Kernel Pod
```

优先 OIDCAuthenticator；若内部 IdP 只提供通用 OAuth2，则使用 GenericOAuthenticator 映射 username/groups。认证成功不等于授权，需显式允许用户/组并映射 Hub roles。

## Standalone POC 替代方案

单个 Server 可由受信任反向代理完成 SSO，并实现 Jupyter Server 2.x 自定义 `IdentityProvider` 验证代理身份，但必须：

- Server 网络上只能从认证代理到达，无绕过入口。
- 代理先删除外部身份 header，再注入已验证身份。
- WebSocket、XSRF、登出和 session 过期都经过验证。
- 不用简单关闭 token/password 代替身份校验。

只在前面放 oauth2-proxy 后关闭 Jupyter 认证，而 Server 仍可直连，会形成认证绕过。

## 内部 IdP 所需参数

- issuer/discovery、authorization/token/userinfo/JWKS endpoint。
- client ID；client secret 由 Secret 系统注入。
- redirect URI、scopes、username claim、groups claim。
- 组到平台角色映射、账号禁用时延、refresh token 策略。
- 单点/本地登出、会话时长、MFA/条件访问要求。
- 稳定用户 ID；不能用可变 display name 做主键。

## 验收

- Authorization Code；支持时启用 PKCE，并校验 state/nonce、issuer、audience、签名和时间。
- HTTPS 和 Secure/HttpOnly/SameSite Cookie；密钥不进镜像/Git。
- 未登录 REST/WebSocket 被拒绝；伪造 header 无法绕过。
- 用户禁用或移出允许组后不能新建会话，既有会话按策略回收。
- 普通用户不能篡改 claim 获得管理员权限。
- 身份一致传给 UEM/SQL Proxy，Kernel 仅获最小短期凭据。

参考：[OAuthenticator 通用配置](https://oauthenticator.readthedocs.io/en/latest/tutorials/general-setup.html)、[OIDC 配置](https://oauthenticator.readthedocs.io/en/latest/tutorials/provider-specific-setup/providers/oidc.html)、[IdentityProvider](https://jupyter-server.readthedocs.io/en/latest/api/jupyter_server.auth.html)。
