# skill 与 Workbench 草稿交换 v1／v2

## 2026-10-04 完整伴随输出与图示增量

新增 v2 与 v1 并存。另一 skill 仓库 `export_content_records.py` 从同批明确的多题草稿自动生成命名空间题目、节点、答案及关联，图示附真实 PNG／PDF／SVG 字节、哈希和精确原图区域；不需要逐条手写 records。Workbench 合并工具保留原五册包，通过明确伴随映射验证旧 diagram 的 width_mm／no_hint_confirmed，然后一次确认调用原生教学图版本服务。整个数据库／新图示文件批次失败回滚，已有同哈希资源保留。具体封闭字段、512 KiB 资源／1 MiB 包限制、来源与幂等规则及授权交付任务见 [完整集成契约](skill-integration-completion-20261004.md)。公式位图未建立明确原生对应时仍拒绝，不静默丢图；未知坐标仍需核定。原照片只通过已有上传入口，不嵌入资产交换包。

以下 v1 描述保留既有兼容行为和前轮历史边界；其中“未修改另一仓库／旧图示后续项”描述前轮状态，不是 v2 的当前能力。

## 既有 v1 规则与前轮实施记录

2026-10-04 核心补齐新增纯本机 `scripts/produce_skill_records.py`：输入明确的 `swb.material-draft.v1`（proposal、原题号与原图整数框）及 `swf.sources.v1`，输出完整 `swb.skill-records.v1` 题目、知识／方法／题型、关联及可选答案伴随文件，再交给既有 `prepare_skill_exchange.py`。工具无数据库或网络；输出目录必须 0700、文件 0600，不覆盖已有文件。未知题干仍为 null。它不能从旧索引或五册散文推测内容，也没有改动独立 skill 仓库；旧图示资产自动生产仍是后续兼容项。字段与批次入口见 [核心补齐契约](fusion-completion-contract.md)。

本机工具输出通过 `swb.skill-import.v1` 导入资料任务，不直接操作生产数据库。仅同一资料的已有原图页可以映射，必须指定 page_id 与实际原图 sha256，不根据同图哈希自动选择资料页。区域为原图整数 [left,top,right,bottom]，看不清、未知辅助图或缺失坐标需要补齐后再输入，拒绝静默丢弃。

顶层字段：schema_version、sources（1～100）、records（0～300），可选 packet、ledger、catalog、tool_inputs。完整 JSON 原样保留在私有数据库；1 MiB 上限、重复键、非有限数、未支持字段拒绝。每个 source 为 {id,page_id,sha256}。每个 record 为 {id,kind,data}；id 是本输入唯一的局部身份，保存结果映射到 Workbench 稳定身份及精确修订。重复相同 request_key 返回原任务，冲突拒绝；确认同一任务重放不新建版本、不恢复撤回版本。

| kind | data 字段 | 原生输出 |
|---|---|---|
| question | printed_text、original_number、sources；可选 display_markup、image_print_confirmed | 题目与原图区域精确版本，人工确认 |
| knowledge | definition、sources；可选 conditions、common_errors、display_markup | 知识条目与区域精确版本 |
| method | name、sources；可选 conditions、steps、notes | 方法与区域精确版本 |
| question_type | name、sources；可选 structural_features、conditions | 题型与区域精确版本 |
| answer | question（局部题目 ID）、body、basis；可选 formulas | 家长答案独立版本与确认依据 |
| link | question、node（局部 ID）、role（知识 applies／方法 primary 或 auxiliary／题型 belongs） | 双向可追溯的精确关联 |
| observation | sources；可选 legibility、notes | 原图笔迹观察；作者、日期均 unknown，不生成作答或掌握 |

sources 区域为 [{source_id,bbox}]。conditions／steps 等逐行字段使用换行文本，与原生服务一致。所有确认由原生服务校验完整性、数学展示、来源及权限，整个包原子成功或回滚。原图不改变；人工确认 reason 保存到审计。题目、答案、节点和关联只创建本输入的新身份，修订已有内容使用已有带版本凭据的业务入口，避免凭号覆盖旧题。

可选 packet 保留 skill 的 swf.packet.v1 和 5 个 swf.print.v1 文档；使用 Workbench 统一的封闭数学／markup／用途验证器校验兼容投影，原包不修改。图片／diagram 等尚不兼容的资产契约明确拒绝，需先以原生可追溯图版本准备，不能假称共享渲染器已完成。packet 中的审核状态不当作原生内容发布或真实学习事件。ledger／catalog 原样保存，不能从描述推断掌握。

当前 skill 的旧 `swf.workbench-export.v1` 只含索引骨架，不能满足本契约；应由工具或人工提供结构化 records 伴随文件。五册正文无法可靠自动拆出全部题干、答案、节点与真实作答。因此此接口提供完整显式内容接入，旧 skill 的自动伴随输出和历史数据迁移仍需独立开发与授权；本轮不修改另一仓库。

## 本机伴随合并工具（当前同时接收 v1／v2）

`scripts/prepare_skill_exchange.py` 不读取数据库、不调用模型或联网。输入 `swf.sources.v1`、`swf.catalog.v1`、`swf.packet.v1`，另提供显式内容伴随文件 v1（schema_version、records）或 v2（另含 assets）及 `swb.skill-page-map.v1`（schema_version、pages）。pages 每项为 {source_id,page_id,sha256}，清单中的每个来源必须明确映射，包括未知辅助图；不能靠同图哈希猜页。工具先验证输入批次、目录与来源摘要、图示字节／映射和五册用途，再生成对应版本的待确认交换包，保留原工具输入与 records 摘要。页面在创建任务前仅在本机预览，创建后将整包保存到家庭服务器，内容核对确认后进入题库。

```sh
# 输入和输出均使用 Git 忽略的私有目录；output 必须是尚不存在的文件。
.venv/bin/python scripts/prepare_skill_exchange.py \
  --sources data/skill-batch/sources.local.json \
  --catalog data/skill-batch/catalog.local.json \
  --packet data/skill-batch/packet.local.json \
  --records data/skill-batch/records.local.json \
  --mapping data/skill-batch/page-map.local.json \
  --output data/skill-batch/exchange.local.json
```

输出父目录预先设为 0700，工具以 0600 排他创建文件，不覆盖原输出。可选 `--ledger` 原样保留工具账本；账本中的审核不替代家庭确认，也不生成学习事件。这个工具完成显式伴随合并，不自动从五册散文、旧索引或孩子笔迹推断完整 records。
