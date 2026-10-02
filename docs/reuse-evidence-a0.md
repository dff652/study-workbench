# A0 候选复用证据：持久化、审核与导出

记录日期：2026-10-02（Asia/Shanghai），本轮补查跨 10-01～10-02。状态：主代理只读源码补查；未安装、克隆或运行候选，未执行其测试。仅获取公开文本源码，未发送本项目照片或个人记录。

本轮沿用已评估的两个固定提交，不重新搜索候选。通过 GitHub API 读取固定提交的完整目录树（均 `truncated=false`），再按符号读取写入、编辑、复习、导出和相关调用方。目录树用于定位，不代表读过全仓源码。源码事实、对本项目的影响和未证实项分别记录；矩阵及路线见[复用评估](build-vs-reuse-assessment.md)。

## 1. Smart Wrong Notebook

固定快照：`wttwins/wrong-notebook@9751f074f713f55add71174ebe4066641ad370f4`。目录树包含 252 个文件条目；关键数据库为 Prisma／SQLite。

| 证据 ID／路径 | 已核实的源码行为 | 对本项目的影响 |
| --- | --- | --- |
| SW-01 持久化：[schema](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/prisma/schema.prisma#L34-L141)、[创建](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/error-items/route.ts#L71-L101) | `KnowledgeTag` 有层级和题目多对多；题目保存 `originalImageUrl`、题干、参考答案、可见错答和错因。创建去重使用两秒窗口和题干前 100 字符 | 分类结构可参考；这不是原图哈希去重，也没有跨页区域、学习者与逐次评价的完整模型 |
| SW-02 人工修改：[详情页](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/error-items/%5Bid%5D/page.tsx#L285-L385)、[PUT](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/error-items/%5Bid%5D/route.ts#L78-L187) | 人工可编辑题干、答案、解析与错答；接口检查所属用户后直接更新 `ErrorItem`，标签使用清空后重连。已读路径没有追加内容修订、审核决定或比较输入版本 | 有人工编辑流程，不能据此认定具备本项目的版本审核事务；须新增修订、审核与冲突处理 |
| SW-03 历史：[练习写入](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/practice/record/route.ts#L18-L31)、[掌握修改](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/error-items/%5Bid%5D/mastery/route.ts#L30-L58) | `PracticeRecord` 追加用户、学科、难度、对错，没有题目外键；`ReviewSchedule` 有题目、复习时间与结果；掌握等级直接更新题目 | 不能说没有历史记录，但这些记录不能代替绑定学习者、题目版本、笔迹和提示的 `Attempt`；掌握等级不能成为证据源 |
| SW-04 未知判断：[状态规则](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/lib/mistake-status.ts#L1-L34)、[保存调用](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/error-items/route.ts#L162-L185) | 状态有 `unknown`，但 `normalizeMistakeStatusForSave` 在错答文本非空时优先返回 `wrong_attempt`；中文将 `not_attempted` 显示为“不会做” | 并非完全没有未知状态；该保存规则仍不能处理来源不明的课堂笔记，空白也不能自动等同于不会，需改写业务规则 |
| SW-05 数据导出／恢复：[JSON 导出](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/export/route.ts#L34-L103)、[导入事务](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/import/route.ts#L147-L340) | 导出用户信息、科目、自定义标签、含标签的题目、复习及练习记录；导入使用事务和 ID 映射。题目按用户／科目／文本去重，复习按题目／排期去重；练习记录逐条新建，没有对应去重分支 | 可参考序列化和关系映射；不能宣称重复导入全部幂等。导出序列化 `originalImageUrl`，可能包含内嵌数据或地址；已读路径没有另行打包图像、校验哈希及内容／评价／审核版本清单，空实例完整恢复未证实 |
| SW-06 打印：[预览页](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/print-preview/page.tsx#L19-L54)、[内容选择](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/print-preview/page.tsx#L238-L288) | 当前题目列表进入浏览器 `window.print()`；答案、解析和标签默认关闭，题干文本也默认关闭，默认回退显示原图 | 可参考打印开关；原图可能仍带手写答案／提示，独立复测不能只靠隐藏字段。未见此路径保存导出版本快照或生成 Word，公式及换页效果未实测 |

补充路径：[分析接口](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/analyze/route.ts#L105-L127)调用图片分析后返回结果；[reanswer 接口](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/src/app/api/reanswer/route.ts#L23-L47)调用模型重新生成答案，并不是追加孩子的再次作答。这里只确认调用职责，不审计供应商实现或模型效果。

授权事实：固定版本 [README](https://github.com/wttwins/wrong-notebook/blob/9751f074f713f55add71174ebe4066641ad370f4/README.md#L238-L240)写明 MIT；本轮完整目录树再次未找到 LICENSE／COPYING 文件。沿用此前“授权文本待核实”的结论，未取得额外授权。当前仅借鉴结构，不复制候选代码。

## 2. 智卷 error_correction

固定快照：`xiaozhejiya/error_correction@b440f2eb3d65c55180a693775a2b41d358eb2a84`。目录树包含 473 个文件条目；关键路径为 Flask 路由、SQLAlchemy 模型及 CRUD。

| 证据 ID／路径 | 已核实的源码行为 | 对本项目的影响 |
| --- | --- | --- |
| ZJ-01 持久化：[模型](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/models.py#L178-L237)、[入库](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/crud/questions.py#L398-L489) | 批次关联题目；保存内容块、公式／图片标记、图片引用、OCR 问题、答案及 `user_answer`；入库检查内容哈希，返回新增／重复计数。题型是字符串，知识标签另表关联 | 有结构化题库基础；内容哈希不等于原照片哈希。稳定题型对象、跨页原图坐标／变换、学习者及作答版本仍需建立 |
| ZJ-02 入库与修改：[save-to-db](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/routes/questions.py#L500-L598)、[题干 PATCH](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/routes/questions.py#L413-L441)、[答案 CRUD](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/crud/questions.py#L761-L803) | 用户选择成功运行或分割记录中的题目，合并前端答案后入库；PATCH 直接重写 `content_json`／`answer`；`update_user_answer` 直接更新单一字段并提交 | 有人工选择入库和编辑，不等于逐版本审核。当前答案路径会替换已有值；需新增独立作答、评价和审核事务 |
| ZJ-03 复习事件：[模型](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/models.py#L390-L405)、[排期写入](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/crud/review.py#L95-L163) | 追加 `ReviewEvent`，保存评级、间隔、时间和目标；同时更新题目或笔记的复习字段，较高评级令 `review_status` 为“已掌握” | 确实有事件历史；它没有此次笔迹、独立性、提示和评价版本，不能把评级或调度状态当成本项目的独立成功依据 |
| ZJ-04 笔记与流程：[笔记模型](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/models.py#L322-L387)、[笔记修改](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/crud/notes.py#L142-L194)、[流程 CRUD](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/crud/workflow_runs.py#L15-L120) | 笔记含 Markdown、原图片路径、OCR 文本、共享标签及复习字段；修改直接替换内容和标签；流程保存类型、状态、供应商、结果目录及数量 | 笔记可作为知识编辑参考，仍需独立知识内容修订和类型化关联。运行记录尚不能证明 prompt／schema／输入依赖版本、费用预留与迟到结果控制已满足 |
| ZJ-05 分割历史：[模型](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/models.py#L282-L296)、[保存与清理](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/db/crud/split_records.py#L15-L73) | `SplitRecord` 保存原图片信息及完整题目 JSON；保存后按用户清理超过 20 条的最旧分割记录 | 不能说完全没有结果快照；这属于受数量限制的分割历史，不是稳定的题目修订、作答及审核档案。长期证据不能依赖该清理策略 |
| ZJ-06 导出：[数据库出口](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/routes/questions.py#L694-L744)、[Markdown 渲染](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/pipeline/utils.py#L64-L200)、[测试源码](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/tests/test_export.py#L32-L60) | 按所选题目生成 Markdown，保留内容块／LaTeX 文本并重写部分图片相对路径；“我的答案／正确答案／解析”输出填写占位符，数据库出口不传入保存的答案或作答历史；测试覆盖选择与文本出现等行为 | 不可宣称可导出已保存家长答案、Word 或完整备份。路径改写不是图片打包，未见该出口包含哈希、区域及版本恢复清单。题型标题可能提供提示，独立复测需另设用途过滤；测试仅阅读，未运行 |

补充路径：[upload 路由](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/routes/upload.py#L786-L1020)含 OCR／分割编排、配额检查及工作流调用；这里只核实入口存在，不把免费额度逻辑认定为本项目的并发金额预算控制。OCR 坐标出现在[结果简化函数](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/backend/pipeline/utils.py#L203-L251)，但未证实所有导入后题目都保留原图哈希、区域版本及可逆变换。

授权依据沿用固定版本 [LICENSE](https://github.com/xiaozhejiya/error_correction/blob/b440f2eb3d65c55180a693775a2b41d358eb2a84/LICENSE)的 AGPL-3.0 文本；本轮没有复制代码或对外发布，采用源码时另核使用与分发方式。

## 3. 结论边界与剩余验证

本次新增的是写入和出口行为的证据，不是可运行原型的结果。以下仍未证实：手机操作、图片访问权限的完整链路、关闭 AI 的全流程、公式与 PDF／Word 实际版式、空实例恢复、并发审核和费用控制、上游升级成本。未读取的其他路径可能有辅助记录，不将局部未见扩大为全仓绝对不存在。

两个候选都具备可借鉴的题目／分类及人工操作能力。已查到的可变题目字段、复习历史和分割快照仍不能满足[核心契约](core-data-contract.md)的双向来源、逐次作答与评价审核不覆盖约束。因此推荐维持组件组合路线；若后续评估整体改造，应以契约场景及完整恢复测试证明改造收益，而非仅追加几列或恢复演示截图。
