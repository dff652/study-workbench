# PC 统一工作台本机验收（2026-10-05）

对应 [PC-00～10](pc-product-integration-plan-20261005.md)，实现规则见 [PC 与解析契约](pc-companion-contract.md)。本记录针对 `7c16583` 之后的本地增量；实现、主代理完整验收及第三轮独立复核已完成，最终 PASS；前两轮 FAIL 与修复过程另行保留。本验收完成时未提交；随后 PC 源码已本地提交，README／文档与完整未 push review 见 [后续清单](pc-follow-up-20261005.md)。本轮尚未 push 或部署。

## 实际实现

- 七个业务入口共享侧栏、顶栏、家庭及学习者上下文。具体记录地址支持刷新和前进／后退；图片及 PDF 在框架内预览，Word／ZIP 是显式下载。账号登录按同源原认证页面执行。
- 既有业务表单经白名单页面 API 复用服务端权限、CSRF、校验、幂等和追加修订；仅载入过滤后的主内容与固定选区／排序／派生控制器。业务页面不载入旧导航、旧主样式或 iframe；文档预览使用私有 PDF iframe 及每页图片。
- 新增独立解析草稿、人工确认、私有 PNG、后台输出及事件历史。跨页来源、层级小问、未知单位／区域、显式方法版本、三类订正分别保存。解析用途固定为家长答案，不创建真实作答、评价或掌握结果。
- 固定 companion 源码四模块，使用 Workbench 原生渲染器；逐题、分讲、合集复用同题正文。保留旧 v1／v2 导入与五册，原图字节不变。
- 自动保存、冲突对照、较早历史分页与进行中任务刷新、取消／重试、失败请求原幂等键恢复，以及多图逐张上传／失败项重试均有实现和行为验证。

## 主代理运行验证

| 项目 | 实际结果／范围 |
| --- | --- |
| 完整后端 | 最终当前源码 359 项全套通过，433.497 秒；系统检查无问题，迁移反向／重装及自有资源清理通过。此前专项与失败记录保留，不叠加到此数量 |
| 前端 | 主代理独立运行 14 文件／79 项全部通过；TypeScript 与生产构建通过 |
| PC 浏览器 | 最终修复报告 `4cc57d516b6d43449e0d318231ca51f8`：58 个业务状态、49 种 PC 页面模板、22 条链路全部通过，0 JS 异常、0 站外请求、0 内部代码／哈希正文泄漏 |
| 桌面宽度 | 全部 58 状态检查 1440；选区、知识、作答、评价编辑、模型配置、五册六个代表页面另验 1280／1920 |
| 文档 | 匿名两题／两讲、五份文档共 9 PDF 页；全部 PDF 和隔离 LibreOffice 转换的 9 页已目视，页数一致、0 越界；数学内容、OMML 及 ZIP 结构通过 |
| 容器恢复 | 最终源码／构建的自有合成项目 `38f3bfdf73f043c4`：73 哈希文件与全表行数恢复一致；五个 solutions 模型有记录，重建后文件／会话可用，非空实例恢复拒绝，UID=10001 |
| 本机数据及源码 | 原图、个人记录、凭据、导出、截图、恢复包和 dist 使用 Git 忽略的私有目录；完整实际差异由主代理审查，链接及源码清单另存私有验证记录 |

复验入口：

```bash
.venv/bin/python scripts/run_persistence_tests.py
npm --prefix frontend test
npm --prefix frontend run build
.venv/bin/python scripts/run_persistence_tests.py --pc-browser --skip-tests
.venv/bin/python scripts/verify_container.py
```

这些命令使用已有依赖、自有临时 PostgreSQL 与合成资料；数据库无发布端口，PC 服务只监听 loopback。浏览器拦截并拒绝站外请求，模型关闭。它们不会读取 36 的业务数据。

## 逐页矩阵

下表逐一登记原 48 种 PC 模板及新增帮助页。由 Django 测试客户端记录实际模板命中，再由 Chromium 验证工作台页面、标题及对应地址；不是从 URL 的 HTTP 200 推断页面完成。共享模板、局部片段、错误消息和移动帮助页不算独立 PC 页面。

| 原页面模板 | 新归属 | 实际状态／截图名 |
| --- | --- | --- |
| `ai/config.html` | 设置 | `model-config` |
| `ai/index.html` | 设置 | `models` |
| `ai/review.html` | 设置 | `model-review` |
| `ai/run_detail.html` | 设置 | `model-run` |
| `ai/run_form.html` | 设置 | `model-new` |
| `catalogue/choose_household.html` | 知识与题库 | `catalogue-household-choice` |
| `catalogue/index.html` | 知识与题库 | `catalogue`、`catalogue-unscoped-index` |
| `catalogue/merge.html` | 知识与题库 | `question-merge` |
| `catalogue/question.html` | 知识与题库 | `catalogue-question` |
| `catalogue/split.html` | 知识与题库 | `question-split` |
| `knowledge/choose_household.html` | 知识与题库 | `knowledge-household-choice` |
| `knowledge/index.html` | 知识与题库 | `knowledge`、`knowledge-unscoped-index` |
| `knowledge/node.html` | 知识与题库 | `knowledge-node` |
| `knowledge/node_form.html` | 知识与题库 | `knowledge-new`、`method-new`、`question-type-new`、`knowledge-edit` |
| `knowledge/question.html` | 知识与题库 | `knowledge-question` |
| `learning/assessment.html` | 学习档案 | `assessment` |
| `learning/assessment_form.html` | 学习档案 | `assessment-new`、`assessment-edit` |
| `learning/attempt.html` | 学习档案 | `attempt` |
| `learning/attempt_form.html` | 学习档案 | `attempt-new`、`attempt-edit`、`attempt-correct` |
| `learning/index.html` | 学习档案 | `learning` |
| `learning/observation.html` | 学习档案 | `observation` |
| `learning/observation_form.html` | 学习档案 | `observation-new`、`observation-edit` |
| `learning/profile.html` | 学习档案 | `profile` |
| `learning/profile_form.html` | 学习档案 | `profile-new` |
| `operations/index.html` | 设置 | `operations` |
| `operations/retention_policy.html` | 设置 | `retention` |
| `operations/work_timing_form.html` | 设置 | `timing` |
| `printing/answer.html` | 文档中心 | `answer` |
| `printing/arithmetic.html` | 文档中心 | `arithmetic` |
| `printing/diagrams.html` | 文档中心 | `diagrams` |
| `printing/erratum.html` | 文档中心 | `erratum` |
| `printing/evidence_report.html` | 文档中心 | `evidence-report` |
| `printing/index.html` | 文档中心 | `prints` |
| `printing/packet.html` | 文档中心 | `five-books` |
| `printing/packet_prepare.html` | 文档中心 | `five-books-prepare` |
| `printing/snapshot.html` | 文档中心 | `snapshot` |
| `study/index.html` | 进度与复测 | `study` |
| `study/report.html` | 进度与复测 | `study-report` |
| `study/schedule_detail.html` | 进度与复测 | `schedule` |
| `study/schedule_form.html` | 进度与复测 | `schedule-new` |
| `web/help.html` | 设置 | `help` |
| `web/index.html` | 资料整理 | `materials-index` |
| `web/login.html` | 同源登录 | `login` |
| `web/material.html` | 资料整理 | `material-detail` |
| `web/members.html` | 设置 | `members` |
| `web/page.html` | 资料整理 | `page` |
| `web/page_reading.html` | 资料整理 | `page-reading` |
| `web/question.html` | 资料整理 | `question` |
| `web/question_form.html` | 资料整理 | `question-new`、`question-edit` |

## 实际业务链路

已验证的动作包含：导航返回／前进／刷新及侧栏上下文；两个学习者切换后回到正确档案和证据；知识↔题目↔原图；旋转 90°、坐标选择及转交题目录入；派生图框内预览；原快照 PDF inline 与 Word 实际下载；作答编辑追加同一实体的修订；待确认 v2 教学 PNG 与可读公式；两张上传中第二张中断后仅重试该图，3 次请求增加 2 页；解析自动保存、历史对照、分数公式预览、模型关闭下真实 worker 生成并保留旧输出；刷新恢复草稿；空家庭、只读拒绝和会话过期的真实登录流程。

独立复核后新增五条实际链路：报告深链的学习者归一化及报告／计划切换；operations 跨家庭导航、刷新及 AI 明确家庭地址；透明原图生成来源 PNG 后丢响应重试保留同键、只新增一条资产且 RGBA 像素一致；仅选 Word 时真实 worker 生成三份 Word、五张逐页预览、无 PDF iframe 且下载均可用；全家庭复测列表进入其他学习者计划、陈旧外围选择的直达／刷新及跨家庭范围恢复，并核对作答／评价／已知档案上下文的观察详情。最终共 22 条完整链路通过。

主代理目视覆盖上述 58 个状态的全页及六类页面的另外 12 个桌面宽度截图；布局没有横向溢出、遮挡或旧导航并存。长表单的最终截图先等待字体及原图布局稳定；白色原图是明确的合成输入，不是实际家庭照片。PDF 每页预览与独立导出目视另行记录，不把 headless 浏览器内置 PDF viewer 的空白画面作为分页验收。

逐页目视使用 `947459a50767419ab6e46dfe50d3cb5c` 的全部 58 状态和 12 张其他宽度截图。随后 `81147fca8e304f9692cb0b59e3d9f579` 补看图片布局稳定的新旧六份输出及页面末尾表单。独立复核修复后，`b6491697b1824daa96110ba82c3b43cb` 补看家庭／学习者上下文、Word-only 全页预览及完整解析长页，最终 `4cc57d516b6d43449e0d318231ca51f8` 补看实际范围归一化后的完整计划表单；未变化的原生表单及桌面样式沿用此前逐页目视证据。学习者进度截图包含正常加载状态，正确切换另由实际请求及页面断言验证。

## 修复与复核范围

实施中发现并修复：React 重绘丢失原生输入／选区；保存后跳转仍误判未保存；学习者深链上下文被覆盖；待确认图示／公式无法实际阅读；原快照 PDF 使用 attachment 无法框内预览；较早任务操作／轮询不刷新；保存／生成丢响应重试更换请求键；普通选择项暴露内部来源哈希；只读成员知识列表出现新建入口。修复均保留服务端权限、来源或历史约束，并运行对应回归。

验收脚本的模板路径、合成档案年级、卡片标题 locator、AI 配置拒绝状态及全页截图稳定等待也按实际契约校正；新增透明来源合成数据的创建顺序、编码家庭地址与保存完成等待按实际行为修正，最后新增截图辅助函数的调用参数也已修正。失败日志及主动中断的过渡测试运行保留，不用这些运行宣称最终通过。第一轮六项问题及第二轮计划归属问题均已修复，两轮独立 FAIL 与后续结论分开见 [增量 review](reviews/pc-unification-20261005.md)。

## 证据与交付状态

完整日志、截图、导出预览与源码哈希清单保存在 Git 忽略的私有 `artifacts/pc-20261005/`、`artifacts/pc-verification/`。完整后端、前端、PC 与容器日志分别保留；失败运行也保留并区分。最终容器已重建并验证全部修复后的应用源码和前端产物；这是合成备份／空实例恢复，不是升级 36。

PC-01～10 本地实现及主代理验收已完成，第三轮独立复核 PASS：独立后端 359 项（420.375 秒）、前端 79 项及构建、PC 报告 `ad16b7bfcdfc4404a104e1efd20faa11` 的 58 状态／49 模板／22 链路，以及另外 10 项实际构建浏览器探针和 2 项真实 HTTP 检查均通过。两项专项不相加称为 361 项全套。PC 源码已本地提交；本轮尚未 push 或部署，交付状态见后续清单。36 的前一轮交付记录为 `test-20261004-fusion-c4aa96f`，本轮未操作该服务。真实模型、家庭完整批次、移动客户端、NAS 发布及 PC／macOS Microsoft Word 实开均不由合成验证推断完成；Word 两项继续为 `not_tested`。
