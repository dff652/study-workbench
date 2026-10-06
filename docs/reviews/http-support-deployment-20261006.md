# 内网 HTTP 支持、部署与验收

更新：2026-10-06。用户同意内网通过 IP＋端口访问；本次补齐 HTTP 兼容并增加独立入口，保留原 HTTPS 服务。源码已本地提交，运行及最终独立 review 状态在下方记录；后续由用户统一手动 push。

## 入口与运行身份

| 项目 | HTTP | HTTPS |
| --- | --- | --- |
| 工作台 | `http://192.168.2.36:18080/app/` | `https://192.168.2.36:18443/app/` |
| 登录 | `/accounts/login/`，沿用已有账号 | `/accounts/login/`，沿用已有账号 |
| 服务 | 新增 `http`，直接 Gunicorn | 原 Caddy → `web`，原 worker 保持 |
| 设置 | `app.http_production` | 原 `app.production` |
| 源码 | `02ce45536c98534a9c01a2b75640bb25b1eb8a3d` | `4ab5a227ceef49f18a99a3d9ed5c41eb964e44fb` |
| 镜像标签 | `test-20261006-http-02ce455` | `test-20261006-ux-4ab5a22` |
| 镜像 ID | `sha256:cbf9974a0261d7991b75509115667a659d786b086ce1618ecf4677f6c4d654d3` | `sha256:485c1486f3a76d715807b84ff2e8d00e496933aa5a22bb459c90abc027aa6006` |

两个入口使用同一业务数据库和资料卷，不复制资料或账号。HTTPS 保持原镜像和证书配置；本轮文档提交不会重建镜像。版本仍为 `0.2.0-dev`。

## 修复与边界

- 非安全 HTTP origin 缺少 `crypto.randomUUID()`；共享请求键使用 `crypto.getRandomValues()` 生成符合 UUID v4 格式的随机键，保持同一请求重试的幂等语义。缺少全部安全随机源时报告失败。学科保存也使用共享函数，异常进入正常错误及 busy 清理逻辑。
- HTTP 使用独立设置，只在此服务关闭 HTTPS 跳转、Secure cookie 和代理头信任；HTTP 与 HTTPS 原服务的环境没有互相覆盖。HTTP 设置拒绝上述三个 HTTPS 开关仍开启的错误配置。
- cookie 按主机／路径匹配，不按端口隔离。因此 HTTP 使用 `swb_http_sessionid`／`swb_http_csrftoken`，HTTPS 保持 `sessionid`／`csrftoken`；两个入口分别登录、分别注销。Session 仍为 HttpOnly，CSRF 校验保留，不开放跨域写入。
- HTTP 提供常规浏览器工作台；service worker／PWA 安装依赖安全上下文，客户端在该 HTTP origin 跳过注册。需要 PWA 时仍使用原 HTTPS 入口。
- 原图、作答、评价、修订和未知状态不改；没有新增迁移，没有启用模型。本次实际写入仅发生在自有合成隔离实例，正式环境只有登录／注销及业务只读验收。

## 部署方式与后续操作

[HTTP 覆盖配置](../../compose.http.yaml)默认绑定 `127.0.0.1`，本次保护环境文件显式选择家庭接口 `192.168.2.36`／`18080`。要求支持 `!override` 的 Docker Compose 2.24 以上；本机实际版本为 5.1.3。

在既有 `data/runtime-36/compose.env` 中补充 `SWB_HTTP_IMAGE_TAG`、`SWB_HTTP_SOURCE_REVISION`、`SWB_HTTP_BUILD_DATE`、`SWB_HTTP_HOST`、`SWB_HTTP_BIND_ADDRESS` 和 `SWB_HTTP_HOST_PORT`。上述实际运行身份固定为表中版本；秘密字段保留原值，不在文档或 shell 参数中显示。保持保护权限，并使用三个配置文件：

```sh
docker compose --env-file data/runtime-36/compose.env -p study-workbench-36 \
  -f compose.yaml -f compose.mobile.yaml -f compose.http.yaml ps

# 已完成镜像构建并检查，启动时仅增加 HTTP，不重建或重启原服务。
docker compose --env-file data/runtime-36/compose.env -p study-workbench-36 \
  -f compose.yaml -f compose.mobile.yaml -f compose.http.yaml \
  up -d --no-deps --no-build --wait http
```

HTTP 启动只执行 `check`、`migrate --check`、静态文件收集和 Gunicorn；不执行数据库迁移。它继承非 root、只读根文件系统和原私有资料卷。原 Web／数据库不发布直接端口，新增 HTTP 独立发布所选接口端口。整项目操作也必须保留三个配置文件；不要用新 HTTP 标签替换原 Web／worker 标签。

## 验收结果

当前状态：主代理合成与正式运行验收 **PASS**，切换前独立预审 **PASS**；最终独立运行／文档交付 review 正在进行。源码本地提交 `02ce455`，配套文档另行本地提交，不 push。

源码阶段本轮实际运行完整前端 **194 项**、生产设置／CSRF **7 项**，类型检查和生产构建通过。镜像 **284 个**应用、入口、依赖说明及前端文件 SHA 与已提交源码／已验构建完全相符。旧应用完整后端测试没有在本次重新运行；前轮结果见 [UI UX 部署](ux-remediation-deployment-20261006.md)。

合成完整验收 **6 组 PASS**，使用实际 LAN HTTP origin，验证不属于安全上下文、没有 `randomUUID` 但有 `getRandomValues`，在浏览器保存分类、幂等重放、创建资料及注销；错误 Origin 和缺少 CSRF 实际返回 403。合成 PostgreSQL 与资料目录均为独立 tmpfs，验后仅清理匹配自有项目／所有者的资源。

主代理正式浏览器 **17 组检查 PASS**，验证七入口加载、四种宽度、原图、作答／评价历史、历史 PDF／Word 下载及退役状态、实际 native PDF viewer 正文，实际 Chromium native viewer 为 success、1 页／第 1 页，主代理目视题目正文及缩略图；并在同一浏览器先后登录两个入口，验证 HTTP 登录／注销不改写 HTTPS cookie 或登录状态。正式启动前后全部 52 张表／24 文件／迁移严格一致；浏览器登录／注销后单列账号登录时间和会话表，其他 50 张业务表、24 文件及迁移保持精确一致。原四服务及 11 个无关容器的 ID／镜像／启动时间／挂载完整字段集合保持，Docker 挂载返回顺序先归一化。原根 CA 指纹保持，HTTPS 通过严格 CA／IP 验证，无证书豁免；HTTP 登录／注销期间，原 HTTPS cookie 值与权限属性不变，CSRF 正常刷新到期时间单独区分。正式浏览器无 JavaScript 错误、无业务写入或第三方请求；启用模型及调用数均为 0。

两轮合成失败来自注销探针误读不存在字段及把公开帮助页当私有页，最终依据实际私有 API 未登录应 401 的契约通过；两轮正式浏览器初始探针把 HTTPS 正常刷新 CSRF 到期时间误判为 cookie 改写，诊断确认只有 expires 变化后归一化并完整重验。失败证据保持，不将失败轮次登记为 PASS。

私有证据位于被忽略的 `artifacts/runtime-36/http-20261006T074411Z/`；包括构建、已验 SHA、环境前后副本、容器身份、合成试验、浏览器报告／截图及独立复核。凭据／照片／数据库快照／生成文件不进入 Git。原用户 DOCX 和整改主基线、Word 阅读副本没有修改，不重做 Word 验收。

## 回退

本次不升级原四服务、不变更数据库架构，因此 HTTP 回退仅移除新增且项目／所有者标签匹配的 `http` 容器，并恢复本次前的保护环境文件；既有 HTTPS、数据库、卷和业务数据保持。不要删除整个项目或用旧备份覆盖当前数据。启动失败脚本按上述范围回退。

原前轮 PRE／POST 配套备份及实际空恢复证据保留，见 [UI UX 部署](ux-remediation-deployment-20261006.md)。本轮没有另外执行第三次空恢复或声称新增配套备份；只新增兼容监听服务，并校验启动不改业务。容量预审后构建仅新增约 16 MiB，保留旧镜像／恢复点，不做广泛清理。浏览器临时文件并发时自由空间曾低于 128 MiB 保留线，独立代理中止自己的探针并改用自有 tmpfs 临时目录后重验；主浏览器退出和自有临时清理后复测约 274 MiB 自由空间，正式服务保持健康。

实体客户端、真实家庭完整流程、Microsoft Word 实开、Android／PWA 真机和真实模型仍未验。本轮工程及运行验收不替代上述产品验收。
