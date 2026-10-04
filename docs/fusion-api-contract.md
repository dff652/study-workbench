# 融合 API 与统计契约 v1

日期：2026-10-04。实施接口前缀 `/api/v1/`，前端 `/app/`，同源 Django 会话；不采用演示 token、Clerk、客户端持久化学习缓存或默认公开注册。旧登录 `/accounts/login/?next=/app/` 与人工页面继续可用。

同一 v1 的增量接口见 [核心补齐契约](fusion-completion-contract.md)：资料／节点进度、原生复测计划、同页题面／答案／关联确认、空白待补、独立勘误、整页阅读列表及固定 material 准备阶段。下面保留首版路由与口径，不作为全部当前路由清单。

所有 JSON 响应带 `schema_version: "swb.api.v1"`；错误形如 `{"schema_version":"swb.api.v1","error":{"code":"unauthorized","message":"请先登录。"}}`。未登录 401，无权或未知对象 404，输入错误 400，过期／冲突 409；所有私有响应 `private, no-store`。写操作 POST 且有 CSRF。GET 不创建任务或正式内容。

| GET 路由 | 响应 |
| --- | --- |
| `session/` | `user: {username}`、`households: [{id,name,role}]`、`csrf_token`；未登录返回 401，由前端显示旧登录入口 |
| `learners/?household=<id>` | `items: [{id,display_name,grade,profile_url,report_url}]`；没有学习者返回空数组 |
| `learners/<id>/overview/?household=<id>` | `scope`、`metrics`、`findings`、`links`；可附 date_from／date_to（YYYY-MM-DD）与 source_kind |
| `learners/<id>/attempts/?household=<id>&page=1&page_size=20` | 同上过滤；`items`、`total`、`page`、`page_size`，上限 100 |

`scope`：household_id、learner_id、date_from、date_to、source_kind、metric_version=`evidence.v1`。有日期区间时只对已确认实际日期过滤，未知日期单列，不用上传或录入时间替代。来源枚举为 independent_answer／assisted_answer／classroom_note／copied_work／unknown，与现有 SourceKind 一致。

`metrics`：attempt_count（有效真实事件数）、question_count（稳定题目去重数）、source_counts（来源枚举到次数）、unknown_date_count（所选来源中未知日期数）、independent_success_count（沿用已有成功证据规则）、independent_success_rate（未冻结可判分母时 null）、rate_state、repeated_error_count、insufficient_evidence_count。统计只计算 active 当前作答；同次多评价不多计一次，记录列表保留撤回事件和历次评价。未知日期即使被日期过滤排除，仍单列数量并说明。

`findings`：observed_correct_methods、insufficient_evidence、repeated_errors、known_actual_date_intervals，均为现有证据报告中的可追溯结果。`links`：profile_url、report_url、schedule_url。

作答 `items` 沿用 evidence_report 中的 JSON 行：attempt_id、attempt_revision_id、attempt_kind／标签、source_kind／标签、independence／标签、prompt_status／标签、prompts、actual_date_state、actual_date、legibility／标签、answer_text、state、question_id、question_revision_id、question_text、independent_success、sources、assessments；补充 attempt_url、question_url、previous_attempt_id。每次评价有精确版本、current／published 和五维依据／unknown；前端不计算掌握百分比。

前端空值显示未记录／未测，网络失败显示可重试；取消切换前的旧请求，查询缓存仅内存、登出／家庭切换清理。所有来源和业务链接使用后端返回的同源 URL，不拼接任意外部地址。

后续材料／知识／工作流／确认／打印接口在同文件追加；未定义的接口不由 worker 猜测，主代理提供明确输入输出后再实现。

## 构建身份与任务 API（本轮实现契约）

`GET /api/v1/about/`：version=`0.2.0-dev`、release_state=`development`、source_revision（构建时明确注入，否则 unknown）、build_date（未注入为 null）、changelog=[{version,date,changes:[text]}]、help_url。开发版本不能显示已正式发布。

所有下述路径以 `/api/v1/` 为前缀，同一认证／no-store／错误规则；写入必须带 session CSRF。JSON POST 字段封闭、1 MiB 上限、重复键和非有限数拒绝；客户端 request_key 使用随机 UUID，失败重试同一输入保留 key。

| 方法／路径 | 输入 → 输出 |
|---|---|
| GET materials/?household=id | items=[{id,title,page_count,created_at,material_url,prepare_url}]、total；最多 200，超过时明确提示使用原资料入口 |
| POST materials/create/ | {household_id,title,request_key} → material（上述行） |
| GET materials/:id/ | material、pages=[{id,position,sha256,width,height,page_url,preview_url}]、readiness、jobs（最新 50） |
| POST materials/:id/upload/ | multipart file + request_key（CSRF header） → page_id、duplicate；一次一个原图；保留原有上传验证 |
| POST materials/:id/workflows/ | {request_key,learner_id?:stableID,proposal?:swb.skill-import.v1} → job |
| GET workflows/:id/ | job、records、sources、readiness、links、events |
| POST workflows/:id/actions/ | {action,expected:job.context,request_key,reason?,checks?} → job；过期拒绝、精确幂等 |
| GET workflows/:id/download/ | 仅 complete：私有五册 ZIP，重新校验所有哈希 |

`job`：id、material_id、state、context={version,source_stamp}、created_at、updated_at、error_code|null、record_count、result={learner_id|null,mapping?:localID→nativeIDs,packet_id?:hash}。

`readiness`：ready、gaps（阻塞题干／答案／题面无提示检查）、content_gaps（知识／方法／题型待补）、questions=[{question_id,revision_id,number,text,confirmed,answer_ready}]。

`links`：material_url、prepare_url、ai_url（现有配置／任务）、preview_url（已生成）、download_url（通过输出检查后）。`events`：version、action、details、created_at，追加历史。

阶段：needs_review → **confirm**（一次核对整包，reason 必填；全部原生保存并确认同一事务）→ ready → **queue** → queued → worker running → output_check → **check_output**（checks={pdf:true,docx:true,purposes:true}，reason 必填）→ complete。可 **cancel**（终态除外）；failed 可 **resume**，输入版本变化须建立新任务。running 30 分钟未完成标记 interrupted，人工恢复；GET 不执行任务、不请求模型。渲染失败有 error_code，保留输入及历史，迟到 worker 不能恢复已取消任务。

skill 交换契约详见 [skill-exchange-contract.md](skill-exchange-contract.md)。前端提供本地 JSON 交换包选择、逐项文本／来源预览及一次确认；不以“粘贴脚本”替代日常上传，原图编辑及复杂公式继续链接已有业务页。未提供 proposal 的任务整理现有已确认资料，模型关闭可完成。AI 操作沿用已有授权／预算／来源范围与保存并确认入口，任务主流程不要求必须调用模型。
