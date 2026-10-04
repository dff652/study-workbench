# Skill 完整伴随输出与交付任务

2026-10-04，用户授权按顺序完成：完整伴随内容与图示、代表性本机批次、统一 review／提交／手动 push、36 一致性备份与空实例恢复后升级。真实模型由用户后续配置；Android／MS Word 实体结果不能用模拟替代。不自动发布 NAS 成果或迁移全部历史照片。

## 冻结的增量契约

- 保留 `swb.skill-records.v1`／`swb.skill-import.v1`。新增 v2 在原字段上增加必填 `assets` 对象；完整包仍限 1 MiB。原照片只通过已有上传入口入库，不放进资产包。超限明确拒绝，分批处理。
- skill 输入 `swf.workbench-content.v1`：`schema_version`、`batch_id`、`questions`、`diagrams`。questions 每项 `{id,draft}`，draft 是已有 `swb.material-draft.v1`；完整题干、节点、答案来自明确结构化整理内容，未知仍为 null。工具为每题命名空间自动生成题目、节点、答案及关联，无需逐个手写 records。不从五册散文、旧索引或笔迹猜内容。
- diagrams 每项 `{id,question,placement,png_key,vector_key,source,alt,conditions,width_points,min_label_points,independent_safe,basis}`。question 是 questions 的局部 ID，source 是 `{source_id,bbox}`，必须等于该题的一个已知原图区域。PNG 与 PDF／SVG 是本机明确配对成果，独立题面必须明确无提示；解析图放在 answer，不进入无提示复测。
- v2 伴随输出 `{schema_version,records,assets}`。diagram record 的 data 为 `{question,placement,png_asset,vector_asset,source,alt,conditions,width_points,min_label_points,independent_safe,basis}`，question 引用生成的局部题目 record。assets 为相对 key → `{sha256,media_type,base64}`，支持 image/png、image/svg+xml、application/pdf。最多 32 个，验证真实字节、哈希、路径、图片解码及矢量安全；不访问网络。确认调用原生教学图修订服务，原图区域由服务器生成，保留全部图版本。
- 五册旧 diagram 的 width_mm／no_hint_confirmed 只作兼容投影；必须匹配本输入图示伴随记录与真实 PNG／矢量资产。原 packet 保留，原生五册从已确认记录重新生成。未建立明确原生对应的 formula_image／其他资源拒绝，不静默删图，也不把旧审核状态当作发布。
- 相同 request_key 的创建／确认重放不重复；不同任务创建新内容身份，不靠题号覆盖历史。整个确认与图示文件写入原子成功或回滚。

## 实施范围与验收

| 顺序 | 所有权与输出 | 验收 |
|---|---|---|
| 1 | 一个 luna6-worker：skill 新纯转换脚本及其测试；主代理：本契约、Workbench 交换／原生图示事务、前端解析 | v1 回归；v2 确定性、未知／哈希／坐标／越权／失败回滚／重复导入 |
| 2 | 主代理：私有代表性批次与隔离验收报告 | 知识↔题目↔原图、图示进入五册、独立册无解析提示；历史作答／评价分开，不虚构孩子掌握；实际 PDF／Word 版式 |
| 3 | 主代理完整差异检查及独立 verifier；更新项目状态并统一源码交付 | 测试／构建、公开边界扫描、准确提交范围及远程 SHA；另一 skill 仓库已有未提交工作保持 |
| 4 | 主代理：36 私有一致性备份／恢复、候选升级与验收 | 原记录／私有文件／CA 保持；严格 TLS、账号／版本／更新记录及业务路径；保留回退点 |

此表的四项工程任务已顺序完成。源码 c4aa96f／skill c947710 已手动 push；36 运维 26 项／真实 HTTPS 浏览器 14 组、前后配套备份实际空实例恢复及 CA 保留通过。完整回执见 [DEV_STATE](../DEV_STATE.md)与[本轮 review](reviews/skill-delivery-20261004.md)。Android、MS Word、真实模型与家庭效果继续作为人工验收项，不写成完成。
