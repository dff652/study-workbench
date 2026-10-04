# MOB-01：HTTPS 与最小 PWA

更新日期：2026-10-04（Asia/Shanghai）。用户已同意实施 MOB-01，本轮范围为源码、配置、说明及**本机合成隔离验收**。不升级 36，不提交／推送，不安装手机证书，不开发 Flutter 或原生 API，不调用模型或外发照片。真实手机和主屏幕安装结果须另记录，不能由模拟浏览器代替。

上述为首轮实现边界。用户随后同意源码提交／push 和 36 备份升级；部署结果以 [DEV_STATE](../DEV_STATE.md) 的最新记录为准。手机信任、主屏幕安装及家庭试用仍需实际操作；不会因此启动原生客户端或模型测试。

## 1. 已实现的交付物

- [HTTPS 覆盖配置](../compose.mobile.yaml)：在现有 Compose 之上添加 Caddy，移除 Web 主机端口；数据库／资料卷沿用原定义。HTTPS 默认只绑定 loopback。
- [Caddy 配置](../deploy/caddy/Caddyfile)及[派生镜像](../deploy/caddy/Dockerfile)：固定官方 Caddy 2.11.4 的镜像 digest，使用独立私有 CA、8443 容器端口；关闭管理 API 和自动安装系统信任。
- [PWA 入口](../app/web/pwa.py)：公开 manifest、根作用域 service worker、手机说明。192／512 像素图标和 iPhone 图标为项目自绘界面资产，不来自照片。
- [浏览器客户端](../app/web/static/web/pwa/client.js)：注册 worker、断网提示、支持时提供安装按钮；不暂存作答或照片。
- [通用离线页](../app/web/static/web/pwa/offline.html)：仅含连接说明，没有账号、题干、图片或历史。
- [HTTP 边界测试](../tests/web/test_pwa.py)与[隔离容器／浏览器验收](../scripts/verify_mobile.py)。

现有业务、账号角色、原图、审核、作答／评价历史及模型发送门槛未改变。正式能力与未来 Flutter／API／离线范围仍见[移动技术方案](mobile-client-technical-plan.md)。

## 2. 信任与缓存边界

Web 在该覆盖配置中没有主机端口；外部请求只能走 HTTPS 代理。Caddy 明确覆盖 `X-Forwarded-Proto` 并去掉客户端 `Forwarded`，Django 开启 Secure cookie、HTTPS 重定向与受信代理头。健康检查仅在容器内部携带协议头，不能以重新发布 Web 端口解决健康问题。[Caddy 代理说明](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)支持这个代理边界设计。

代理运行用户与宿主机私有 CA 目录所有者一致，容器 root filesystem 只读、Linux capabilities 全部移除。官方 Caddy 可执行文件带 `cap_net_bind_service=ep`；当容器 capability bounding set 为空时执行会失败。派生镜像仅用已有 `setcap` 删除该文件标记，保留原二进制内容，不增加包或能力；8443 无需低端口绑定权限。

service worker 只缓存一个经过静态文件哈希命名的通用离线页，安装时以 `credentials: omit` 获取，拒绝重定向、失败或 private／no-store 响应。普通导航始终联网；仅网络失败时回退到通用提示。私有页面、API、图片、导出和表单写入都不进入 Cache Storage。no-store 策略扩展到 Django 动态响应，包括注销后匿名请求私有图片的登录重定向；公开静态文件继续由前置 WhiteNoise 提供。

worker 脚本本身 no-store，注册使用 `updateViaCache: none`；发布新的 worker／离线页会改变专用缓存名，激活时删除本项旧缓存，不删除其他应用的缓存。浏览器 HTTP 缓存仍可保存公开哈希静态资源；它与 Cache Storage 是不同机制。PWA 不是私人资料离线副本，也没有新增离线写入或后台上传能力。

## 3. 环境和部署前输入

需要 Docker、支持 `!reset` 的 Compose（至少 2.24.4）、已有应用构建依赖；隔离验收另需项目 `.venv` 的 Playwright、缓存 Chromium、已有 `certutil`／`bwrap`／`setpriv`，以及在测试机允许只读 mount namespace 的本地 sudo。不能为了验收修改全局信任或关闭证书验证。

当前固定代理镜像已在本机 amd64 核对运行版本；其他架构尚未验证，不能只更改标签后声称通过。TLS 主机名、对外端口、设备 DNS／VPN、证书路线与私有状态目录在实际部署前固定。测试中的 `localhost` 只用于本机，手机不能用它连接服务器。

配置变量：

| 变量 | 用途／约束 |
| --- | --- |
| `SWB_TLS_HOST` | 一个确切 hostname，不带 scheme、端口或路径；不使用通配符。手机必须能解析到目标服务 |
| `SWB_TLS_HOST_PORT` | 主机 HTTPS 端口，默认 8443；实际地址须带对应端口 |
| `SWB_TLS_BIND_ADDRESS` | 默认 `127.0.0.1`；仅在获目标设备部署授权后选择家庭接口 |
| `SWB_CADDY_STATE_DIR` | 绝对路径、当前管理员所有且 0700 的私有目录；包含 CA 私钥，不作为静态目录发布 |
| `SWB_PROXY_UID`／`SWB_PROXY_GID` | 上述目录实际所有者的数字 UID／GID；代理非 root |
| 原 `SWB_*` | 保留显式 DB／密码／secret／镜像标签／资源所有者等；密钥仍在私有 env 文件 |

单一 TLS 入口也可填写局域网 IP。Caddy 的 `default_sni` 与该入口一致，让不发送 SNI 的纯 IP 客户端选择正确证书；客户端仍必须验证 CA 和 IP SAN，不忽略证书错误。选项含义见 [Caddy 官方说明](https://caddyserver.com/docs/caddyfile/options#default-sni)。

覆盖配置将 Web 的 allowed host、CSRF origin 和三个 HTTPS 开关绑定到上述单一 TLS 入口，不能把旧 HTTP origin 当作本阶段外部入口。原 `compose.yaml` 的独立 HTTP 模式继续保留；在同一已升级项目漏掉覆盖文件会重新发布旧 Web 端口，操作时必须保持完整文件列表。

## 4. 可复验的本机隔离验收

从项目根目录运行（浏览器缓存路径按本机实际填写）：

```sh
PLAYWRIGHT_BROWSERS_PATH=/path/to/private/browser-cache .venv/bin/python scripts/verify_mobile.py
# 纯 IP 入口回归：使用同一隔离边界，实际验证无 SNI 客户端。
PLAYWRIGHT_BROWSERS_PATH=/path/to/private/browser-cache .venv/bin/python scripts/verify_mobile.py --tls-host 127.0.0.1
```

脚本生成唯一 owner／项目／镜像标签，只绑定 loopback，使用虚构题目、图片、账号与三次作答。测试前拒绝现有同名资源；不访问 36。官方 Caddy 与 PostgreSQL 镜像须已缓存，验收脚本不自行 pull；构建应用使用既有 Dockerfile。

TLS 验证使用独立 CA 文件和默认 hostname 验证，同时验证无该 CA 的客户端拒绝连接。Chromium 的两个 NSS 目录只在临时 mount namespace 映射到新的私有数据库；sudo 显式保留原用户 HOME，测试用户不改 HOME。Playwright 的 Node 请求客户端用进程级 `NODE_EXTRA_CA_CERTS` 信任同一根证书。宿主原目录不写入，不使用 `ignoreHTTPSErrors` 或证书错误豁免参数。浏览器与其子进程退出后该 namespace 消失；测试 CA／诊断材料只留在被忽略的验收目录。

检查包括安装元数据／图标／Chromium 安装资格、Secure session／CSRF、知识↔题目↔原图、三次作答及评价、Cache Storage 仅有通用页、worker 更新检查与旧缓存清理、断网／联网、注销拒绝私有读取，以及 Web／代理重建后应用记录、全部私有文件和 CA 保持。

报告、合成截图及诊断保存在 `artifacts/mobile-verification/<owner>/`。包含测试凭据的 `browser.local.json` 为 0600，父目录 0700；不发布整个目录或 CA 状态。脚本核对标签后移除自有容器／卷／网络及测试镜像，保留已有官方镜像和其他项目资源。测试失败不能记录为通过，当前真实结果见 DEV_STATE。

## 5. 后续家庭部署操作准备

这组说明用于**将来获目标实例部署授权后的操作**，本轮没有执行。已有 36 不应另建同名空项目，也不能照搬测试 owner、用户名或 localhost 地址。

1. 固定使用中的项目名、原 DB／资料卷和当前镜像；取得升级前一致备份及恢复证据，按[容器 SOP](container-deployment.md)处理。
2. 准备选定的家庭 hostname／DNS／VPN 和私有代理目录；在受保护的原 env 副本追加 TLS 变量，确认 UID／GID，生成新的候选镜像标签。配置中的密码、签名与私钥不发到聊天。
3. 带完整两个 Compose 文件做配置检查并构建 `web caddy`，先在隔离项目验证相同入口策略。只用 `config --quiet` 检查，避免输出合并后的凭据。
4. 按授权的升级窗口停止原 Web／worker，备份并校验；以原项目和原卷使用覆盖配置启动候选版本，确认直接 Web 端口消失、DB 无发布端口。
5. 用导出的根证书核对 TLS，验证登录／私有图片、历史、打印与模型关闭；完成手机信任及业务验收后才更新部署状态。初次 CA、域名变化和入口变化都记录到私有部署清单。

完整文件列表示例，`SWB_TARGET_PROJECT` 与私有 env 路径必须按目标实例固定；未设置项目变量时命令直接拒绝：

```sh
docker compose --env-file .env.mobile.local -p "${SWB_TARGET_PROJECT:?先设置已核实的原项目名}" -f compose.yaml -f compose.mobile.yaml config --quiet
docker compose --env-file .env.mobile.local -p "${SWB_TARGET_PROJECT:?先设置已核实的原项目名}" -f compose.yaml -f compose.mobile.yaml build web caddy
docker compose --env-file .env.mobile.local -p "${SWB_TARGET_PROJECT:?先设置已核实的原项目名}" -f compose.yaml -f compose.mobile.yaml up --detach --no-build --wait
```

该配置只监听 HTTPS，不发布 HTTP 跳转端口；使用明确的 `https://<hostname>:<端口>`。loopback 改为家庭接口、DNS、路由／防火墙及 VPN 变化是目标部署步骤，本轮未执行。

## 6. 根证书和手机接入

本版配置采用 Caddy 私有 CA，不进行公开证书签发或 DNS API 调用。CA 目录中的 `root.key`／intermediate key 保留在服务器，不能发到手机。只导出根证书 `root.crt`，从受保护的服务器路径取得，通过可信渠道传送并独立核对证书指纹。[Caddy 本地 HTTPS](https://caddyserver.com/docs/automatic-https)说明客户端需要信任根证书。

在服务管理员本机核对证书，或转换为手机可导入的 DER 格式：

```sh
openssl x509 -in "${SWB_PRIVATE_CA_DIR:?先设置已核实的私有代理目录}/caddy/pki/authorities/local/root.crt" -noout -fingerprint -sha256
openssl x509 -in "${SWB_PRIVATE_CA_DIR:?先设置已核实的私有代理目录}/caddy/pki/authorities/local/root.crt" -outform DER -out data/mobile-ca-root.cer
```

证书的 SHA-256 指纹与 PEM 文件的 SHA-256 是两种值，不混用。不要从出现证书错误的网页直接信任来历未核实的根证书。

Android：在目标机型的安全／凭据管理界面导入经过核对的 **CA 证书**，不是 Wi-Fi 客户端凭据；具体菜单随厂商／系统不同。Google 的[证书管理说明](https://support.google.com/pixelphone/answer/2844832)提供通用入口与单项移除说明，实际机型的 CA 选项及浏览器信任必须真机核对；不清空全部设备凭据。

iPhone：安装核实过的根证书配置描述文件后，还需在“设置 → 通用 → 关于本机 → 证书信任设置”开启对应根证书的完整信任。手动安装并不自动得到 TLS 信任，依据 [Apple 说明](https://support.apple.com/en-us/102390)。只处理本家庭根证书；如果改用公开受信证书，另评估配置与移除旧证书。

手机连入家庭网络／VPN，先在浏览器确认正确 hostname 和无证书错误，再登录。Android 在浏览器菜单选择安装或主屏幕入口；iPhone 在 Safari 分享菜单添加主屏幕。PWA 图标不是原生安装包，无 App Store／Play 发布动作。证书、DNS 或服务不可用时不会靠主屏幕入口绕过故障。

## 7. 真机验收记录与上线门槛

每个平台记录实际机型、OS／浏览器版本、日期、HTTPS origin、服务镜像／源码与确认人；报告私有保存，公开状态去敏。

| 步骤 | 应得到的结果 |
| --- | --- |
| HTTPS 信任与入口 | 正确 hostname／端口、证书链与指纹；无忽略错误；局域网／VPN 路径符合配置 |
| 添加、退出、重开 | 主屏幕打开同一服务，登录态按策略保留；退出后私有历史／图片须重新登录 |
| 资料与历史 | 原图区域可核对；知识与题目双向可查；三种来源作答和各次评价仍分别存在 |
| 网络与失败 | 断网只显示通用页／提示；无私人离线历史；恢复连接后先核对未确认操作 |
| 升级 | 已安装入口可使用候选版本；公开静态更新正常；旧历史／文件不覆盖 |
| 实际版式 | 真机文字、按钮、放大／移动与旋转可用；记录实际照片格式、尺寸和拒绝情况 |

本任务不新增 HEIC 支持、不修改当前 12 MiB 请求／1600 万像素限制，不承诺原生后台上传。T-06 家长核定、真实作答日期及耗时、T-07 手动模型实测仍按原任务执行。真机及家庭确认未完成前，不把 MOB-01 全部验收、M1a 或整体 M1 判为通过。

## 8. 备份与回退

正式升级前按原 SOP 停止写入方、配对 DB／文件备份，保留旧镜像和配置。代理 CA 状态与 TLS 配置单独做受保护备份，保持根私钥可恢复；丢失 CA 会要求设备重新信任，不等于家庭数据丢失。

代理重建使用同一个私有状态目录；升级前确认目录不是新空路径。证书备份不能替代 DB／资料备份，也不能公开上传整套 CA。

本轮没有新增数据库迁移。若后续回退 HTTPS／PWA，先关闭新入口并恢复配套旧配置／旧镜像，在保留原卷或隔离恢复点上验证业务；漏用覆盖配置会恢复 Web 直接端口，所以回退需同时检查网络暴露和客户端入口。service worker 曾被安装时，浏览器仍可能保留通用离线页；卸载主屏幕入口及移除该站点数据／对应证书应明确说明，不声称服务端回退自动清空所有手机状态。
