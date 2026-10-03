# B1 人工资料与审核 Web 契约

日期：2026-10-02。B1 的输入是 A1b 的家庭权限、内容修订和审核事务，输出是人工上传、框选、题干录入及审核页面。全部验证使用虚构照片与临时数据库；真实资料没有通过页面上传。运行结果以 [DEV_STATE](../DEV_STATE.md) 为准。最终容器化交付仍属于 D1。

2026-10-03 的后续扩展增加图片内放大／缩小、移动／框选与重置，以及资料页裁切、人工矩形遮白和对比度增强。新操作形成不可改写 ImageDerivative，保留原图、参数、原坐标、创建者／时间、输出哈希和有损说明；私有路由核对家庭与文件 SHA。放大后仍按预览固有像素回算原坐标；输出保持原图方向。数据库插入／提交失败会清理本请求独立路径的新派生文件。后续运行证据及局限见[缺口补齐记录](gap-closure-20261003.md)，下文保留 B1 阶段原范围。

## 1. 范围与共享关系

| 记录 | 身份与关系 | 可变边界 |
| --- | --- | --- |
| MaterialSet | UUID；属于一个 Household；记录标题、创建账号及时间 | B1 仅创建，不提供移动或删除 |
| MaterialPage | UUID；属于一个 MaterialSet；引用同家庭 ImageRecord；保留上传文件名与页序 | 只允许调整页序，原图与所属资料不能改写 |
| ImageRecord | 复用 A1b 原图 ID、SHA、存储键及像素尺寸 | 同家庭同 SHA 复用原图；不同上传请求可保留不同资料页关联 |
| PagePreview | 原图 × 0／90／180／270 度；保存 PNG SHA、尺寸与存储键 | 派生预览只追加，不能覆盖；原始上传字节保持不变 |
| QuestionSource | 与一个精确 QuestionRevision 一对一；原题号、所属资料及按序区域列表 | 每次题目修订新建；旧题号、预览、区域及顺序留存 |
| Question／RegionRevision | 使用既有 A1b 身份、内容头和追加修订 | 新编辑追加版本，旧题干与框保留；仍需单独审核 |
| ReviewDecision／RequestReceipt | 复用 A1b 审核链、发布投影和幂等凭据 | 不将最新草稿当作已发布版本；重复请求不重复创建 |

领域 JSON 的 schema v0.1 保持不变。预览旋转与页面关联在 Web 元数据保存，领域 RegionRevision 使用 `original_pixels`。当前 `QuestionSource` 只为 B1 新人工录入的题目建立；旧索引缺题干和逐题框，不自动迁移成完整人工题目。旧索引的知识关联及来源缺口在 B2 接入。

题目可从一张或多张资料页选 1～30 个区域，按加入顺序保存。题目详情链接到各来源页；来源页反查该原图各历史版本引用的题目。若同一原图重复上传，多资料页共享原图反向索引，具体题目来源仍记录精确 MaterialPage。父题／小题结构、题目合拆和来源去笔迹不在 B1 页面范围。

## 2. 原图、预览与坐标

上传服务完整解码 JPEG／PNG，按实际格式校验；拒绝损坏、无法解码、多帧、超过 12 MiB 或超过 1600 万像素的文件。HTTP 上传处理器在默认临时文件处理前限制整个请求文件字节为 12 MiB。多选界面逐张串行请求，显示每张文件名、成功／复用或失败原因；不因其中一张失败回退已成功的其他文件。

原图按 SHA 存储，文件名不参与磁盘路径构造。预览从原始像素建立无 EXIF 元数据的新画布；忽略 EXIF 的自动方向转换，用户选择顺时针旋转。框为当前预览固有像素坐标 `(x0,y0,x1,y1)`，不是 CSS 显示像素。后端校验有限数值、非空面积、边界、角度和预览 SHA，再映射到原图像素。

| 顺时针角度 | 预览点 `(x,y)` 对应原图点；原图宽 W、高 H |
| --- | --- |
| 0° | `(x,y)` |
| 90° | `(y,H-x)` |
| 180° | `(W-x,H-y)` |
| 270° | `(W-y,x)` |

每个 QuestionSource 区域保存 `page_id`、`rotation`、`preview_sha256`、`display_bbox`、`original_bbox`、`region_revision_id`、`sequence`；EvidenceRef 同时固定原图 SHA、区域修订与顺序。拖动与键盘输入使用相同契约，历史页在对应旋转预览上显示原框。

`SWB_DATA_ROOT` 必须显式设置为私有目录（0700）；上传的原图与预览为 0600，路径只能位于该目录。写文件、持久数据库提交及异常清理共用文件锁：单次上传失败，回滚新数据库记录并删除本请求新写文件，不删除此前复用的文件。此处覆盖正常异常路径；进程突然退出／断电留下的孤立文件恢复与数据库／文件联合备份属于 D1，未作为完整恢复验收。

## 3. 权限、编辑与审核

使用 Django 登录／会话与 CSRF，注销必须 POST。活跃家庭成员可读；owner／reviewer 可创建、上传、排序、编辑和审核，viewer 禁止写入。服务每次重新校验账号及家庭，用户提交的资料页必须属于当前资料；跨家庭或无权对象统一返回 404。照片预览只通过登录后、按对象授权的 FileResponse 返回，没有公开 media 目录；登录与私有页面／图片使用 `private, no-store`。

编辑凭据由服务器签名，绑定用途、题目、修订和预期内容／依赖头，有效期一小时。审核凭据还绑定上一审核决定；改动头或审核链后迟到请求返回 409，要求重新确认。凭据本身不授予权限。创建、上传、排序及题目编辑使用各自操作的 RequestReceipt；审核沿用既有 `review` 操作。同键同内容成功重放可返回旧结果，同键换内容拒绝。

人工内容仅填印刷题干与工作稿，不解析手写作者、答案或掌握程度。题干允许留空保存待补草稿，但不能审核通过。没有自动创建 Learner、SourceObservation、Attempt、AssessmentRevision 或独立掌握事件。课堂笔记／提示后完成／独立作答的区分，以及讲义勘误与孩子错误的业务页面在 B2；既有领域与持久化区分保持。

审核接受、退回、撤回均追加决定。新草稿及退回新草稿保留旧发布指针；历史界面显示每版题干、修订理由、来源框和审核决定。这只是 B1 人工资料子集，不表示全部 M1a 或所有 AC 已通过。

## 4. 文件所有权

主代理维护 [Web 模型](../app/web/models.py)、[服务](../app/web/services.py)、[图像与坐标](../app/web/images.py)、[上传上限](../app/web/uploads.py)、[私有响应](../app/web/middleware.py)、Web 迁移、settings／根路由、RequestReceipt 操作迁移、服务测试、隔离 runner 和 [浏览器验收](../scripts/verify_web.py)。

一个 `luna6-worker / gpt-6-luna` 仅维护 forms／views／页面路由、模板／静态文件和 HTTP 测试。主代理审查全部实际变化并独立运行自动测试及真实浏览器；worker 交付不代替验收，也不改变 v0.2 需求的评审状态。

## 5. 本机开发与复验

开发配置见 [.env.example](../.env.example)；程序不自动加载该文件。明确提供 `SWB_DB_HOST/NAME/USER`、`SWB_SECRET_KEY` 和 `SWB_DATA_ROOT`，数据库由开发者另行准备。不要把真实凭据写入源码或命令参数。

准备本机开发账号的顺序：`manage.py migrate` → `manage.py createsuperuser`（交互输入密码）→ `manage.py shell` 中取该账号并调用 `app.persistence.services.create_household(user, "自定家庭名")`。superuser 也必须有家庭成员关系，不自动越过家庭授权。

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000 --insecure
```

这是仅监听 loopback 的开发服务；`--insecure` 仅用于 DEBUG=False 时由开发服务器提供静态样式。生产静态服务、TLS、镜像、Compose、升级与备份恢复由 D1 配置；本轮没有应用部署或常驻服务。

合成自动测试不需要准备账号或真实数据库，使用已缓存固定 PostgreSQL 镜像，由 runner 禁用网络、无端口映射、创建私有 socket／tmpfs 并清理自有容器。普通验证：

```bash
.venv/bin/python scripts/run_persistence_tests.py
```

浏览器验证需要 [requirements-dev.txt](../requirements-dev.txt) 的开发依赖及单独临时 Chromium 缓存，不加入运行依赖：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
swb_browser_cache=$(mktemp -d /tmp/swb-browser-cache-XXXXXX)
PLAYWRIGHT_BROWSERS_PATH="$swb_browser_cache" .venv/bin/python -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH="$swb_browser_cache" .venv/bin/python scripts/run_persistence_tests.py --browser
```

浏览器脚本核对 runner 的随机 ownership 文件与私有路径，拒绝指定其他数据库；只启动临时 loopback 开发进程，只生成虚构 PNG，浏览器禁止外部网络请求。截图与聚合报告在被 Git 忽略的 `artifacts/b1-verification/<owner>/`，不含登录密码。测试结束停止进程、删除数据库／上传文件；可自行清理临时浏览器缓存。

框架依据：[Django 5.2 上传](https://docs.djangoproject.com/en/5.2/topics/http/file-uploads/)、[认证](https://docs.djangoproject.com/en/5.2/topics/auth/default/)、[FileResponse](https://docs.djangoproject.com/en/5.2/ref/request-response/#fileresponse-objects)。框架能力不替代本项目对象权限与来源校验。

## 6. 知识体系的需求与后续

FR-15／AC-21 已包含人工建立知识条目及 AI 生成待审草稿；FR-16／AC-22 已包含知识、方法、题型及题目的双向关联。首版采用分类树和关联列表，六组方法作为初始分类。生成内容需要所选来源、适用条件与人工审核；不承诺自动产出完整课程体系或推断孩子掌握。复杂图谱、先修依赖和易混关系仍为后续增强。

B2 宜分为三个有界任务：B2a 知识条目／方法／题型管理及关联查询；B2b 学习者档案、逐次作答及结构化评价；B2c 数据库版本／权限与 A2 打印衔接。AI 草稿生成属于 C1／C2，在供应商、预算和外发许可明确后接入。路线图不自动授权这些任务，文件范围及验收见[实施分工](implementation-plan.md)。
