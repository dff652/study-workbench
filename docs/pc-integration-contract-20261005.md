# PC 两套实现整合契约（2026-10-05）

状态：本机实现与主代理验收完成，独立第二轮复核 PASS，见 [整合验收](reviews/pc-integration-20261005.md)；源码提交／review／push／合并按 [Web 第一期交付](web-phase1-release-20261005.md)单独记录，运行服务另行升级。工程基线为 main `71647accbc8d2698102dd1137ac08a8067321ad0`；参考实现为 `codex/web-foundation` 的 `def982d`。使用独立 `codex/pc-integration` worktree，保留两个原工作区及其历史。

## 唯一正式系统与兼容

- 保留主线 `app/solutions` 五模型、原 API 路径、人工确认、取消／重试／中断恢复、输出检查与事件历史、原生 PDF／Word 生成及 RGBA 来源图校验。不会注册参考分支的另一套解析模型或引入第二套渲染器。
- 已存 `swb.solution.v1` 内容、来源快照和历史输出不改写。API 继续读取和校验 v1。编辑器将副本转换为 v2，明确保存才追加新版本；历史对照转换仅供显示。
- `swb.solution.v2` 保留 v1 顶层与题目字段，将 `steps` 改为结构化数组，并增加 `alternative_steps`。每步包含唯一稳定 `id`、`text`、可空 `formula`、可空 `figure`、布尔 `new_page`（在该步骤前分页）。`figure` 沿用 asset_id／role／caption／width_mm，来源图规则不变。
- v1 的步骤依次转换为文字步骤；没有对应依据的旧 formulas／figures 保留原顺序独立呈现，不按索引猜配。新增关联由用户明确选择。编辑、移动、删除不改变仍存在步骤的 id。
- 新保存可以保留历史链接供比较；新确认／生成以及后台执行前后，所引用题目必须属于本资料，题目／知识／方法／题型必须仍是当前已发布版本（head 等于 published）。已生成历史仍可依照原权限读取。来源指纹包括结构化步骤引用的图示。

## 私人工作副本

- 仅新增 `workflows.WorkspaceDraft`，按 household／actor／key 隔离。GET `/api/v1/drafts/<key>/?household=…`；POST `/api/v1/draft-save/<key>/?household=…`，字段为 expected_version、base_stamp、payload、request_key。
- 响应 draft 含 key、version、base_stamp、payload、updated_at；并发冲突为 409 `draft_conflict`，同时提供当前 draft。版本 0 表示未创建。`{cleared:true}` 作为带版本清空标记，旧窗口不能复活已清空草稿。
- 自动保存只写私人工作副本，不创建正式解析版本、确认、作答、评价或掌握结论。正式保存／确认是显式操作。发现恢复候选或冲突时暂停自动覆盖；恢复由用户选择。
- 客户端串行保存最新输入；清空等待在途保存结束；切换家庭／资料／页面时忽略旧范围迟到响应。失败保留当前输入，恢复不包含未上传文件，敏感表单与凭据排除。

## 检索、报告与使用体验

- 资料列表服务端 `q`／`page`／`page_size` 搜索分页，响应 items、total、page、page_size、has_next、query；现有客户端可读取追加字段。返回可见范围，不用前 200 项代替全量检索。
- 五册证据报告明确选择 `material_questions`（当前资料关联题目）或 `selected_learner_history`（该学习者全部历史）。保存范围进输入和输出记录；旧请求缺省维持原全部历史语义。
- 同时服务小学生／初中生独立使用和家长协助。首页突出下一步学习行动；整理、确认及维护集中呈现。沿用现有账号权限，不新建隐式学生权限模式。
- 技术协议、标识、哈希和内部状态不作为普通操作说明。使用清楚中文、分组与渐进展开；关键提示／错误直接显示。补充帮助支持 tooltip 的鼠标、键盘与触摸操作，不只依靠悬停或颜色。

## 文件责任与验收

- 主代理：本契约、后端／迁移／共享 types 与 api、渲染、报告范围、App 与学习首页、公共 HelpTip、脚本／文档及最终完整 diff 与独立运行验收。
- Luna6-1：frontend/src/features/drafts、materials、workspace（仅这些模块及测试）。私人副本恢复与并发、资料搜索分页、旧表单安全恢复与清晰流程。
- Luna6-2：frontend/src/features/solutions（仅该模块及测试）。v1／v2 副本转换、结构化步骤、公式／图示迟到响应与删除移动、显式保存和私人副本、历史与输出流程。
- 两名 worker 共用新整合 worktree，不回退他人改动，不修改共享文件，不提交／推送。接口变更先交主代理处理。
- 主代理重跑整合后的迁移、后端、前端／构建、实际浏览器三条业务闭环、公式与完整 PDF／Word 版式、配套备份恢复。旧两套测试数量不能相加充当新版本验收；真实 Microsoft Word／Android／家庭数据／线上部署另记。
