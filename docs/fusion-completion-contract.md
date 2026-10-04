# 融合缺口补齐契约

2026-10-04。用户同意继续补齐原方案核心集成，允许一个 luna6-worker 与主代理并行；先完成本机实现、完整实际差异审查和独立验收。保留已有未提交代码；本轮不提交／push、升级 36、NAS 发布、真实资料迁移或真实模型外发。历史首版 PASS 不替代本批验收。

## 分工与顺序

| 切片 | 主代理所有权 | Luna6 所有权 | 验收 |
| --- | --- | --- | --- |
| C-01 进度与复习闭环 | app/api/progress.py、progress_views.py、urls.py；tests/api | frontend 的进度／复习页面、App、api、types 与行为测试 | 真实来源计数、未知与撤回、知识／题型去重、计划完成必须绑定真实作答；跨家庭／viewer／CSRF／过期与重放 |
| C-02 同页内容核对 | 原生内容／阅读 API 与测试 | 原图、区域、题干／知识／答案核对界面 | 原图 SHA、原图整数坐标、一次明确确认、历史与未知、旧版本拒绝；不要求手填 ID 或 JSON |
| C-03 来源工具与批次准备 | 工具交换、工作流／AI 编排与测试；先冻结补充接口 | 新任务准备／阶段重做交互（收到契约后开始） | 不猜旧索引，输入／阶段产物可追溯，模型关闭人工可用；批次限额、取消／迟到、过期、按阶段恢复 |
| C-04 集成验收与文档 | 全部实际差异、隔离后端／浏览器／五册／容器及文档 | 修复各自前端问题 | 实现、运行、人工未验、提交和部署分别记录；原任务仍有未验条件时不标全部完成 |

前端交接前主代理不修改 frontend；一个 Luna6 先完成 C-01，随后接收已冻结的 C-02／03 接口。后端与前端可以并行，互相不覆盖文件。主代理负责最终真实集成验收。

## C-01 API（冻结）

沿用 `/api/v1/`、`schema_version: swb.api.v1`、同源 session／CSRF、private/no-store、家庭权限与既有错误规则；新增 GET 不写业务记录，不调用模型。计数不代表掌握。

`GET progress/?household=id` 返回：

- scope={household_id, metric_version:"progress.v1", as_of:"YYYY-MM-DD"}。
- counts={material_count,page_count,pages_complete,pages_unread,pages_need_retake,questions_confirmed,questions_pending,open_workflows,completed_workflows}。
- materials=[{id,title,page_count,pages_complete,pages_unread,pages_need_retake,questions_confirmed,questions_pending,material_url}]，最多 200；total 为真实资料数。

`GET learners/:learnerID/progress/?household=id` 返回 scope（增加 learner_id），groups=[{id,kind,label,question_count,attempt_count,independent_success_count,unknown_evidence_count,source_counts,node_url}]。kind 为 knowledge／method／question_type；只根据当前已确认的关系和真实有效作答聚合。同题多个评价不多计；没有作答显示未测，不推断掌握；独立成功沿用已有判定，保留全部历史入口。

分组中的作答必须绑定该关联所固定的精确题目修订；旧题目版本的作答仍保留在历次记录，不混入更新后题干的节点进度。

`GET learners/:learnerID/schedules/?household=id` 返回 scope、counts={pending,overdue,completed,cancelled}、items=[{id,question_id,question_text,goal,prompt_plan,due_date,state,target_stale,context,detail_url,history,attempt_choices}]。state 为 planned／rescheduled／completed／cancelled，逾期由当前实际日期与 due_date 判断；完成数只统计已保存且关联真实作答的完成事件。

- history=[{revision_no,action,due_date,reason,attempt_revision_id,actual_date,recorded_at}]，未知实际日期为 null，录入时间单独显示。
- attempt_choices=[{revision_id,label,actual_date,source_kind}]；由既有计划服务提供当前有效且精确版本匹配的作答，前端不自行拼选项。
- context 为原生计划的版本上下文，前端原样回传，不显示内部身份。

`GET learners/:learnerID/schedules/options/?household=id` 返回 questions=[{revision_id,label}]、context（既有创建上下文）。

`POST learners/:learnerID/schedules/?household=id` 输入 {question_revision_id,due_date,goal,prompt_plan,reason,expected,request_key}，expected 来自 options.context；返回 {schedule_id}（原生数值 PK）。

`POST schedules/:id/actions/` 输入 {action,expected,reason,request_key,due_date?,goal?,prompt_plan?,attempt_revision_id?}；action 只允许 rescheduled／completed／cancelled，返回 {schedule_id}。禁止点击即完成；必须明确选择服务端返回的真实作答。调用既有版本化业务服务，保持完整历史、精确幂等、权限与过期检查。

## C-02 API（冻结）

同页核对使用服务端来源凭据，不要求输入 ID、哈希或 JSON。

- `GET materials/:id/content/`：{context:{source_stamp},questions:[{id,revision_id,number,printed_text,working_text,sources,confirmed,answer,edit_context,question_url}],nodes:[{id,kind,label,node_url}]}。sources=[{page_id,bbox}] 的 bbox 为原图整数坐标；answer 为 null 或 {body,formulas,basis,confirmed}。原始照片通过既有页 preview_url 显示。
- `POST materials/:id/content/`：{expected,request_key,reason,checked,question_id?,printed_text,original_number,sources,answer?,nodes?}；checked 必须 true。sources=[{page_id,bbox}]；answer={body,formulas,basis}；nodes=[{kind,data}]，知识 definition／conditions／common_errors，方法 name／conditions／steps／notes，题型 name／conditions／structural_features。最多三个节点，全部沿用所选来源；新节点与该题创建原生精确关联。question_id 为空创建；非空修订必须属于此资料且精确上下文未变。回答与节点可留空待补。返回 {question_id,revision_id}；原子保存与明确确认，重复请求不重复产生版本。
- `POST materials/:id/content/draft/`：{expected,request_key,reason,question_id?,printed_text,original_number,sources}；明确保存待补题面，允许 printed_text 为空，不要求勾选内容确认；仅保存来源和未确认题目草稿，不保存答案／节点／作答或发布。返回 {question_id,revision_id}。expected 同为顶层 content.context。新前端必须提供“保存待补草稿”按钮，看不清内容不得为了保存而补猜题干。
- `POST materials/:id/erratum/`：{expected,question_id,corrected_text,basis,checked,reason,request_key}，通过原生勘误记录、确认、应用和题目确认事务；返回 {question_id,revision_id,erratum_revision_id}。印刷原文保留；不创建学习者错误或评价。
- `GET pages/:id/reading/`：{context,current,history}；current=null 或 {reading,coverage,partitions,pending_items,basis,revision_no,recorded_at}；partitions=[{kind,bbox}] 原图坐标，pending_items 为文本列表（空列表表示无待补）。history 保存每次阅读修订；API 列表由原生追加记录的逐行文本转换。
- `POST pages/:id/reading/`：{expected,request_key,reading,coverage,partitions,pending_items,basis}；允许 kind=theory/question/diagram/handwriting/unknown；未知区、待补或未读不能宣告 complete。返回原生阅读回执。

前端应把原图选框、来源页、题干、可选家长答案、可选知识／方法／题型和待补项放在资料工作区；明确区分转写修正与讲义勘误，笔迹区域不会自动成为真实作答。旧业务详情作为历史／高级编辑入口保留。

## C-03 批次内容准备 API（冻结）

新增 material 模型任务：单次请求准备所选题目区域的印刷题干、最多三个知识／方法／题型节点和可选家长答案；输出仅为草稿，不含学习者、日期、作答或评价。响应 proposal={printed_text:string|null,missing_fields:string[],nodes:[{kind,data}],answer:null|{body,formulas,basis}}，与 C-02 字段相同。看不清题干必须 null 并列入 missing_fields；模型不能决定来源坐标。来源由用户对照原图明确选择，空白题干原生草稿仅用于固定模型来源，不能导出或计为已确认。

- `GET workflows/:id/preparation/`：{job,config:{enabled,outbound_scope,max_requests,max_seconds,budget_usd},stages:[{id,state,question_id,sources,proposal,can_confirm,expected,error_code,record_count,created_at}],limits:{used_requests,max_requests,max_seconds}}。id 为真实 ModelRun；state 沿用 queued/running/awaiting_review/failed/cancelled/stale/applied，历史保留；expected 是原样回传的 job／来源版本／结果摘要上下文。模型关闭时页面显示人工核对入口。
- `POST workflows/:id/preparation/`：{expected,request_key,sources,question_id?,reason}；expected 为 job.context；sources=[{page_id,bbox}]，必须明确整数框。新题目创建未确认空白来源草稿；重做原阶段传已有 question_id，固定其来源；成功返回 {job,stage_id}。只有未交付 ready/needs_review 工作流可以准备；原始来源包已存在待确认 records 时先完成该包。绑定首个模型配置版本，整个批次累计最多四次请求（包括失败、取消和重做），最长期限 600 秒，配置的全局调用／预算限制同时生效，重做不重置限额。
- `POST workflows/:id/preparation/:stage_id/confirm/`：{expected,request_key,reason,checked,printed_text,original_number,sources,answer?,nodes?}；人工核对所选模型草稿，可修正内容但不能替换本阶段来源；原子保存并确认题干、答案、节点和关联，绑定原模型结果摘要与精确来源版本；返回 {job,question_id,revision_id}。
- `POST workflows/:id/preparation/:stage_id/cancel/`：{expected,request_key,reason}，只取消该模型阶段，历史和其他阶段保留；返回 {job}。整批取消同时取消未应用阶段；过期／已取消批次不能发送或接收迟到结果，来源变化须重新创建任务。

GET 不发送模型；准备 POST 是明确执行请求，由现有 worker 执行，使用已配置并明确授权的选定图像范围。当前会话只用合成 provider 验证，不实际外发。前端按用户刷新读取结果，不自动重试付费请求；阶段重做、核对、取消放在资料任务中，不需要跳到旧 AI 页面。

显式结构化 material proposal 可经纯本机 `produce_skill_records.py` 自动生成完整 records 伴随文件；从五册散文或旧索引推测完整题库仍禁止。图片／旧 skill diagram 资产的生产迁移不属于本批；保留拒绝与待补，不能据此宣布所有历史格式已兼容。
