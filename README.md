# Study Workbench

面向家庭的学习资料与作答证据工作台。把照片整理成可追溯的题目，关联知识、方法、题型、独立作答和复习记录，支持纸上练习及 PDF／Word 导出。

当前版本：**0.2.0-dev，开发测试版本（36 已部署）**。融合版采用 Workbench 后端、shadcn-admin 选定前端组件、SOP 工具与可选有限 AI。已实现资料任务、同页原图与内容核对、空白待补、后台五册生成／输出检查、学习总览与逐次记录，以及真实进度与复测计划；可选模型准备按固定阶段保留重做／取消历史。模型关闭可人工完成；没有模拟登录、随机统计或虚构掌握率。旋转／派生图等高级操作、知识地图和学习事件修订继续使用原有业务入口。

本轮完整结构化 skill 输出与配对教学图已接通：v1 兼容，v2 经原生来源校验和一次确认，保留版本与未知。真实小样含 2 道题、4 张图、12 条伴随记录，生成五册共 11 页；PDF 与隔离 LibreOffice 的全部 22 页已逐页检查。未记录孩子作答，不推断掌握。历史 formula_image 没有明确原生对应时拒绝，全量历史未迁移。

主代理后端全套 337 项通过，末次修复后 35 项专项通过；前端 31 项／构建、28 组融合浏览器与 23 文件容器备份恢复通过。独立复核另验后端 41 项（35 正式＋6 探针）、前端 31 项、skill 全套 75 项。准确范围及修复记录见 [本轮交付 review](docs/reviews/skill-delivery-20261004.md)、[融合实施任务](docs/fusion-execution-20261004.md)和 [DEV_STATE](DEV_STATE.md)。全套与专项分别记录，不合并成一次全套。

GitHub 项目：[dff652/study-workbench](https://github.com/dff652/study-workbench)。本轮已完成文档／独立 review、统一源码提交与手动 push，以及 36 备份、空实例恢复和升级。Workbench 源码 `c4aa96f`、skill 三文件提交 `c947710` 已与各自远端 main 核对。36 运行 `0.2.0-dev`／`test-20261004-fusion-c4aa96f`，26 项运维与 14 组真实 HTTPS 浏览器检查通过；原记录、24 个私有文件及 CA 保持。部署回执见 [仓库交付记录](docs/repository-handoff.md)。容器根地址登录后自动进入 `/app/`，旧资料库保留在 `/materials/`；其他原生业务入口保持可访问。

融合依据 [SOP／agent／shadcn-admin 技术方案](docs/integrated-workflow-technical-plan-20261004.md)：Workbench 保留 Django／PostgreSQL 正式数据，skill 提供版本化规则与确定性本机工具，shadcn-admin 提供选定前端组件，有限 AI 按需辅助。上传、对照核对、五册检查与下载是主流程；人工确认用于把整理内容与原图核对后保存，不需要逐层审核。真实模型由用户后续配置测试；Android 真机、MS Word 实开和真实家庭效果仍需人工验收，NAS 发布另定范围。

两条核心主线：

- **知识与题目组织**：知识库、题库、知识地图，以及知识点、方法、题型和题目的关联索引。
- **作答评价与学习跟踪**：手写过程评价、个人学习档案、逐次作答与复测历史。

上传、OCR、大模型与 agent、打印和备份支撑这两条主线。首版同时提供两条主线的基础人工流程，再加入 AI 辅助。

## 从哪里开始

| 文档 | 内容 |
| --- | --- |
| [当前进度](DEV_STATE.md) | 已完成事项、验证结果和下一步 |
| [核心补齐契约与范围](docs/fusion-completion-contract.md) | 进度／计划、同页核对、固定准备阶段与剩余交付边界 |
| [融合技术方案与逐项评估](docs/integrated-workflow-technical-plan-20261004.md) | 18 项功能、前端边界、可选 agent、流程重设计、API／工具契约、统计与 FUS 阶段 |
| [AI 连续核对与整页状态](docs/ai-continuity-20261004.md) | 明确确认、知识来源关联、整页分区历史及合成验收边界 |
| [AI 与整页本轮 review](docs/reviews/ai-continuity-20261004.md) | 原子确认、精确来源、未知及历史约束、独立复核与交付边界 |
| [真实几何与教学图](docs/geometry-workflow-20261004.md) | 33 张来源核定、教学图 Web 版本与两题五册小样、映射待补边界 |
| [几何本轮 review](docs/reviews/geometry-20261004.md) | 教学图、两题真实五册、完整增量与独立验收结论 |
| [SOP 人工流程 review](docs/reviews/sop-20261004.md) | 完整差异与独立复核、已验输入和后续统一交付边界 |
| [SOP 人工流程与五册实施](docs/sop-flow-implementation-20261004.md) | 几何适配、一键确认、五册核对与 ZIP、轻量成员及未验边界 |
| [图片到文档 SOP 对照](docs/sop-implementation-assessment-20261004.md) | NAS 四册 SOP、S01～S10 实现差距、几何适配与五册／NAS 后续任务 |
| [移动客户端技术方案](docs/mobile-client-technical-plan.md) | 家庭优先的 PWA／Flutter 路线、API／登录、照片／同步、部署分发与阶段边界 |
| [HTTPS 与最小 PWA](docs/mobile-deployment.md) | MOB-01 配置、缓存／信任边界、隔离验收、手机证书及后续升级步骤 |
| [缺口补齐与人工待办](docs/gap-closure-20261003.md) | T-01～T-07 的共享契约、最终工程证据和人工试用条件 |
| [需求与实现核查](docs/requirements-implementation-audit-20261003.md) | 18 FR／6 NFR／24 AC 的实际覆盖、工程缺口及后续任务 |
| [仓库交付记录](docs/repository-handoff.md) | Public 仓库、源码／私有数据边界与提交／推送状态 |
| [首次推送前审查](docs/reviews/pre-push-20261003.md) | 完整提交审查、修复及独立验收 |
| [功能清单与覆盖说明](docs/feature-checklist.md) | 知识库／题库、知识地图、手写评价和学习档案的范围及阶段 |
| [产品需求 v0.2](docs/requirements.md) | 首版范围、用户流程、数据边界和可追踪验收场景 |
| [开发与复用评估](docs/build-vs-reuse-assessment.md) | 两条核心主线、候选源码证据、组件复用与定制边界、后续决策条件 |
| [A0 候选路径证据](docs/reuse-evidence-a0.md) | 固定提交的持久化、人工修改、复习与导出行为，及未证实项 |
| [持久化与审核契约](docs/persistence-contract.md) | A1b 物理记录、权限、追加审核、冲突与开发验证 |
| [旧索引导入契约](docs/legacy-import-contract.md) | 私有来源包、81 条原索引、父节点、未知及重复导入／追溯 |
| [打印契约与验收](docs/export-contract.md) | A2 公式、用途隔离、字体、私有快照与五份文档回归 |
| [知识、学习与打印契约](docs/business-web-contract.md) | 两条核心主线的版本、审核、独立证据与打印边界 |
| [本轮 24 场景验收](docs/acceptance-20261003.md) | 已验工程能力、运行证据及真实模型延期边界 |
| [模型配置与测试](docs/model-configuration.md) | 默认关闭、预算、受控任务及手动启用步骤 |
| [本机数据策略](docs/local-data-policy.md) | 默认保留、显式归档／退役、独立账本及人工耗时 |
| [容器启动与恢复](docs/container-deployment.md) | Web／后台任务／数据库、账号、备份恢复及版本回退 |
| [人工 Web 契约与启动](docs/manual-web-contract.md) | B1 登录、私有上传、旋转坐标、历史审核及手机浏览器复验 |
| [第三方组件与字体](docs/third-party-notices.md) | 固定依赖、字体来源及许可声明 |
| [核心数据契约草案](docs/core-data-contract.md) | 知识关联、原图、逐次作答、评价版本与审核约束，合成验收样例 |
| [大模型 API 与 agent 可行性](docs/llm-agent-feasibility.md) | 官方能力证据、技术分工、预算与待实测事项 |
| [实施分工](docs/implementation-plan.md) | 主代理与 Luna 的任务所有权、先后顺序和验收责任 |
| [需求评审记录](docs/reviews/requirements-v0.1.md) | 独立评审发现与主代理处理结论 |
| [评估与路线图](docs/assessment-and-roadmap.md) | 产品定位、调研、技术选型、数据设计、阶段验收和 Luna 分工 |
| [现有资料与代码清单](docs/source-inventory.md) | 本次会话成果、代码复用边界、来源与迁移注意事项 |
| [协作约定](AGENTS.md) | 后续任务的范围控制、资料处理和审查要求 |

## 已有基础

- 23 张来源照片；61 道编号题，拆成 81 条小题索引。
- 六组方法：基础变形与换元、公式与通项、分数裂项、整数裂项、比较与估算、方程与新定义。
- 五份成套文档，每份包含 PDF 和 Word；PDF 合计 29 页。
- 手写证据评价、独立复测题、家长观察记录，以及可复用的文档渲染代码。

这些资料来自人工核对与编排。现有索引尚不是完整 OCR 题库；A1b-I 保留 81 条原行、91 个题目节点和 23 张照片，题干与坐标待补。数据库导入仅在自有临时实例验收，结束清理；本机私有来源包保留。人工页面现支持知识关联、来源缺口和学习记录；旧索引仍须逐题补齐题干、区域及作答依据，不会自动成为完整已审核题库。

## 当前方向

采用成熟组件、现有分类／渲染成果和定制核心业务。候选应用保留为流程参考；没有复制、安装或运行候选。运行基础为 Django 5.2 LTS／PostgreSQL 16。

本机融合版已采用 shadcn-admin 的选定前端布局与组件，接入现有 Django 业务服务；该仓库的演示登录、用户和随机统计不作为业务实现。同源 API、SOP 接入及统计口径已冻结，学习总览、记录列表与资料任务已经实现。使用 skill 不要求引入自治 agent 框架，确定性工具和人工入口继续保留。

知识体系功能已实现基础人工条目、分类树及关联列表，包含知识点、方法和题型的独立身份及题目双向索引。AI 草稿必须有来源并人工审核；复杂图谱推理和自动完整课程体系不属于当前交付。

容器交付用 Docker Compose 分开运行 Web、模型任务 worker 和 PostgreSQL；原图、派生文件、导出及数据库使用独立持久化卷。已在独立的 36 局域网实例测试；连接信息在被忽略的 `data/runtime-36/deployment.local.json`，账号在受保护的 `credentials.local.json`。服务状态及验收见 DEV_STATE，启动与恢复见容器说明。

移动交付按家庭自用优先推进：已实现 [HTTPS 与最小 PWA](docs/mobile-deployment.md)，通过隔离验收并在另获用户同意后完成 36 备份升级。入口采用局域网 IP＋私有 CA，Android 优先，真机证书／主屏幕安装仍待实际操作。独立 Flutter App、完整原生 API 和离线同步仍为[后续方案](docs/mobile-client-technical-plan.md)，尚未实施；模型继续关闭。

本机教学图页及两道真实原题的五册检查版已通过隔离工程验证，具体版式与 review 状态见 [几何实施记录](docs/geometry-workflow-20261004.md)；全量几何迁移及 9 个通用辅助标签仍待核定。

本机人工流程已增加：上传照片 → 框选题目并保存确认 → 确认家长答案／知识关联 → 从资料集生成五册检查版与 ZIP。学习档案仍分别记录逐次作答与评价，不生成掌握分数。AI 返回后直接核对，明确确认时一次保存并接受；原提案、来源和历史可回看，整页状态支持人工分区及待补记录。上述源码已包含在本轮统一提交与 36 融合升级中；阶段实现见 [SOP 实施记录](docs/sop-flow-implementation-20261004.md)，当前运行回执见 DEV_STATE。

照片、个人学习记录和导出文件放运行数据目录，不进入源码版本控制。当前真实照片副本和导入包保存在被忽略的 `data/`，原照片、历史输出与脚本未改动；依赖只装入 `.venv`，没有调用付费推理 API。

## 离线验证

A1a 领域模块在 Python 3.12.3 下已验证，不依赖第三方库。在项目根目录运行：

```bash
python3 -m unittest discover -s tests/domain -p 'test_*.py' -v
```

领域测试覆盖双向来源、多次作答、未知、勘误与版本冲突，使用[虚构关系包](tests/fixtures/domain/synthetic-v0.1.json)。审核状态是输入快照，JSON 包不包含真实图像或完整审核／备份记录；完整设计与实现边界见[核心契约](docs/core-data-contract.md)。

更新日期：2026-10-04（Asia/Shanghai）。

## 持久化验证

安装 [requirements.txt](requirements.txt) 到项目 `.venv` 后运行 `.venv/bin/python scripts/run_persistence_tests.py`。仅使用虚构数据和已缓存的 PostgreSQL 镜像，验证数据库关闭网络、不发布端口并清理自有临时容器；默认不启动 Web 进程，包含服务及 HTTP 用例。配置、审核语义与完整交付边界见[持久化契约](docs/persistence-contract.md)。

追加 `--legacy-package <包目录> --data-root data` 可在同样的自有临时数据库验证本机索引。包准备、显式目标导入和未知处理见[导入契约](docs/legacy-import-contract.md)；默认验证不读取真实照片。

## 人工 Web 验证

本机开发的显式数据库／数据目录、交互账号初始化和 loopback 启动步骤见[人工 Web 契约](docs/manual-web-contract.md)。开发依赖和临时 Chromium 缓存准备后，追加 `--browser --business-browser` 可独立复验手机宽度的资料、知识、学习、打印和复习流程，截图与报告在被忽略的 `artifacts/b1-verification/`。只有虚构图片，验证结束不留服务或数据库。容器验收运行 `python3 scripts/verify_container.py`，只使用新的合成实例。

## 打印验证

A2 命令、公式支持集、字体与验收边界见[打印契约](docs/export-contract.md)。在 `.venv` 中运行 `.venv/bin/python -m unittest discover -s tests/exports -p 'test_*.py' -v`，本轮 20 项通过；五份旧文档的私有输入包与新输出分别在 `data/export-inputs/` 和 `exports/a2-v3/`，被 Git 忽略。PDF 全部逐页核对，Word 已核对原生公式及正文结构，并通过独立 LibreOffice Writer＋Math 的 29 页重排和目视核对；Microsoft Word 未实测。
