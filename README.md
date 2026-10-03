# Study Workbench

面向家庭的学习资料与作答证据工作台。把照片整理成可追溯的题目，关联知识、方法、题型、独立作答和复习记录，支持纸上练习及 PDF／Word 导出。

当前阶段：**人工业务、知识与题库、逐次作答／评价、打印、复习／报告及容器服务已实现并通过独立验收。模型默认关闭，真实供应商测试留待手动配置；完整边界见 [DEV_STATE](DEV_STATE.md)。**

GitHub 项目：[dff652/study-workbench](https://github.com/dff652/study-workbench)。Public 仓库已创建并关联本地 `origin`；本次只创建仓库和提交文档，源码尚未推送。源码交付状态及下一步见[仓库交付记录](docs/repository-handoff.md)。

两条核心主线：

- **知识与题目组织**：知识库、题库、知识地图，以及知识点、方法、题型和题目的关联索引。
- **作答评价与学习跟踪**：手写过程评价、个人学习档案、逐次作答与复测历史。

上传、OCR、大模型与 agent、打印和备份支撑这两条主线。首版同时提供两条主线的基础人工流程，再加入 AI 辅助。

## 从哪里开始

| 文档 | 内容 |
| --- | --- |
| [当前进度](DEV_STATE.md) | 已完成事项、验证结果和下一步 |
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

知识体系功能已实现基础人工条目、分类树及关联列表，包含知识点、方法和题型的独立身份及题目双向索引。AI 草稿必须有来源并人工审核；复杂图谱推理和自动完整课程体系不属于当前交付。

容器交付用 Docker Compose 分开运行 Web、模型任务 worker 和 PostgreSQL；原图、派生文件、导出及数据库使用独立持久化卷。已在独立的 36 局域网实例测试；连接信息在被忽略的 `data/runtime-36/deployment.local.json`，账号在受保护的 `credentials.local.json`。服务状态及验收见 DEV_STATE，启动与恢复见容器说明。

首版流程：上传照片 → 框选题目 → 人工录入或 AI 草稿 → 关联知识点、方法和题型 → 审核及打印 → 评价手写过程并记录个人档案。已加入有来源的变式草稿、手工复习计划及学习证据报告；不生成掌握分数。

照片、个人学习记录和导出文件放运行数据目录，不进入源码版本控制。当前真实照片副本和导入包保存在被忽略的 `data/`，原照片、历史输出与脚本未改动；依赖只装入 `.venv`，没有调用付费推理 API。

## 离线验证

A1a 领域模块在 Python 3.12.3 下已验证，不依赖第三方库。在项目根目录运行：

```bash
python3 -m unittest discover -s tests/domain -p 'test_*.py' -v
```

领域测试覆盖双向来源、多次作答、未知、勘误与版本冲突，使用[虚构关系包](tests/fixtures/domain/synthetic-v0.1.json)。审核状态是输入快照，JSON 包不包含真实图像或完整审核／备份记录；完整设计与实现边界见[核心契约](docs/core-data-contract.md)。

更新日期：2026-10-03（Asia/Shanghai）。

## 持久化验证

安装 [requirements.txt](requirements.txt) 到项目 `.venv` 后运行 `.venv/bin/python scripts/run_persistence_tests.py`。仅使用虚构数据和已缓存的 PostgreSQL 镜像，验证数据库关闭网络、不发布端口并清理自有临时容器；默认不启动 Web 进程，包含服务及 HTTP 用例。配置、审核语义与完整交付边界见[持久化契约](docs/persistence-contract.md)。

追加 `--legacy-package <包目录> --data-root data` 可在同样的自有临时数据库验证本机索引。包准备、显式目标导入和未知处理见[导入契约](docs/legacy-import-contract.md)；默认验证不读取真实照片。

## 人工 Web 验证

本机开发的显式数据库／数据目录、交互账号初始化和 loopback 启动步骤见[人工 Web 契约](docs/manual-web-contract.md)。开发依赖和临时 Chromium 缓存准备后，追加 `--browser --business-browser` 可独立复验手机宽度的资料、知识、学习、打印和复习流程，截图与报告在被忽略的 `artifacts/b1-verification/`。只有虚构图片，验证结束不留服务或数据库。容器验收运行 `python3 scripts/verify_container.py`，只使用新的合成实例。

## 打印验证

A2 命令、公式支持集、字体与验收边界见[打印契约](docs/export-contract.md)。在 `.venv` 中运行 `.venv/bin/python -m unittest discover -s tests/exports -p 'test_*.py' -v`，本轮 20 项通过；五份旧文档的私有输入包与新输出分别在 `data/export-inputs/` 和 `exports/a2-v3/`，被 Git 忽略。PDF 全部逐页核对，Word 已核对原生公式及正文结构，并通过独立 LibreOffice Writer＋Math 的 29 页重排和目视核对；Microsoft Word 未实测。
