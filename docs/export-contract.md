# A2 打印契约与渲染验收

更新日期：2026-10-02（Asia/Shanghai）。本机离线渲染子集已实现并由主代理验收；Web 导出、数据库权限及完整备份属于后续任务。实现入口为 [app/exports](../app/exports/__init__.py)，当前不依赖 Django 启动或数据库。

2026-10-04 扩展：生成器 a2.v3 增加带 PNG／矢量来源和用途声明的教学图；人工五册入口及成套 ZIP 已接入源码，详见 [SOP 实施契约](sop-flow-implementation-20261004.md)。后续已接入题面／解析图 Web、追加版本及五册图示冻结，当前验收见 [几何实施记录](geometry-workflow-20261004.md)。本文以下保留 A2 历史验收口径，不能代替真实几何五册或 MS Word 验收。

## 题图与历史兼容扩展（2026-10-09）

新导出使用`study-workbench.print.v0.2`／生成器`a2.v5`，增加`source_image`题图块：原有本地PNG键、裁图SHA、确切来源、替代文字和宽度之外，要求简短`source_label`。PDF／Word正文显示“题图”和资料／原题号／来源区域；完整区域修订及原图SHA保留在内容快照与Word图片元数据中，权限及字节校验不变。

题面或知识排版中，整行`[[figure:2|原文]]`明确选择题图；`[[image:2|原文]]`继续表示公式图片回退，不自动猜测图片内容。两者只引用同一修订已有、坐标明确的来源区域，去标记后的正文必须一致；独立练习仍须逐版本确认图片不含作答、提示或方法。原图不修改，已有题目要改标记时追加修订。

旧`print.v0.1`输入和快照仍可读取，规范JSON及内容ID保持原版本。新旧快照分别校验，生成器指纹改变会另建文件，不覆盖历史PDF／Word；不会自动重写已有题目或五册。Microsoft Word实际打开与正式学习者验收另记。

## 输入与用途

`study-workbench.print.v0.1` 输入包含文档 ID、标题、用途、显式分页与块、来源 ID／SHA-256／审核状态／可选修订 ID。内容快照 ID 为规范 JSON 的 SHA-256。块有明确角色；支持段落、标题、小字、重点／提醒／连接／勘误、表格、最多六组的固定版式地图、公式、留白及公式图片。

| 用途 | 内容边界 |
| --- | --- |
| `knowledge_summary` | 知识总结和方法说明 |
| `classification_index` | 分类索引和反查表 |
| `evidence_report` | 历史证据说明；不产生新的掌握判断 |
| `independent_practice` | 只允许 `title`、`instruction`、`question`、`answer_space` 角色；答案、方法、分类、评价和含义不明的 body 角色拒绝 |
| `parent_answers` | 家长答案及观察记录，与复测材料单独生成 |

角色检查不能理解所有文字，也不能替代内容审核；调用方不能把提示改名为 question 来绕过语义要求。B2 接数据库时须从已审核修订构造输入，核对家庭权限、依赖及原图中的答案／提示；A2 不实现这条发布路径。

历史适配只读取已完成的五份 v3 `content.json`，经清单哈希校验，保存原字节、历史 PDF／Word、规范输入及出处。地图的六组固定标签进入适配器；历史个人评价内容只在被忽略的私有 JSON 中。旧 v2／v3 Python 脚本没有执行，v2 路径与内容不再是新生成器的运行依赖。

五份旧内容统一为 `legacy_unreviewed`，页脚显示“历史未审核”和内容快照短 ID。历史印刷勘误、已有手写判断按原文本保留；本轮数学核对没有把这些材料发布为新的题目修订、学习者作答、评价或掌握事件。来源不明、空白、提示和课堂记录的业务边界仍由[核心契约](core-data-contract.md)及[持久化契约](persistence-contract.md)约束。

## 公式、文字与版式

| 公式节点 | 意义 | PDF／Word 输出 |
| --- | --- | --- |
| `t` | 字符串 | 可见文本／OMML 文本 |
| `r` | 横排子节点 | 横向组合／OMML 序列 |
| `f` | 分子、分母 | 真分数线／可编辑 `m:f` |
| `u` | 底式、上标 | 上标／可编辑 `m:sSup` |
| `d` | 底式、下标 | 下标／可编辑 `m:sSub` |

未知节点、错误子节点数、过深嵌套和未知块明确失败。公式不缩小到低于 9.8 pt；宽度不足报错。段落仅支持平衡的 b、br、super、font 六位颜色／底色，拒绝外部资源、链接、回调和处理指令。段落中的 Unicode 上标数字转为保留上标样式的 ASCII 数字。中文与数学字体分别检查实际字符覆盖，缺字在输出前失败。

不支持的公式须由调用方显式提供 `formula_image`：本地 PNG 路径键、字节 SHA、来源修订说明、替代文本、打印宽度。验证根目录内路径、哈希、像素／字节上限，并显示“公式图片”及“公式来源”；不会自动把坏公式变成图片或空白。A2 合成用例已验证此回退，历史五份输入均使用支持范围内的原生公式。

PDF 保留 A4、原边距、字号、重点颜色、表格表头、地图尺寸与分数几何。固定地图标签和表格宽度超限失败；意外自动换页造成实际页数与输入不符时失败。Word 保留原生公式、重点颜色、表格表头和显式分页，留白块现在也保存为书写区域；页脚 PAGE／NUMPAGES 字段在办公软件中更新。PDF 实际页数经过验证，Word 最终分页仍受接收端字体、办公软件及字段更新影响。

## 字体、依赖与私有快照

依赖版本固定于 [requirements.txt](../requirements.txt)。渲染模块导入时不读取字体或注册字体；调用时传入三个字体路径，字体注册名称绑定文件哈希。中文子集根据输入实际字符生成，从显式 Noto Sans CJK SC Regular／Bold TTC face 2 转为 ReportLab 可用的二次曲线 TTF，保留字宽并改名为 `Study Workbench Sans SC`。数学使用未改动的 DejaVu Serif TTF。Word 指定原始完整字体族 `Noto Sans CJK SC`，没有向 Word 嵌入字体，接收端需有该字体或接受回退。

字体来源 SHA、face、字符集、派生字体 SHA、改名及许可文件 SHA 随私有包保存。两份许可见 [Noto OFL](../licenses/Noto-OFL.txt)、[DejaVu 完整版权说明](../licenses/DejaVu-fonts.txt)；来源、组件及后续容器打包边界见[第三方声明](third-party-notices.md)。未安装系统字体，也未将字体二进制放入源码。

| 输出 | 内容与规则 |
| --- | --- |
| `data/export-inputs/v3/<包 ID>/` | 五份原 JSON、历史 PDF／Word、五份规范输入、来源清单、三字体及两许可、packet.json；0700 目录／0600 文件 |
| `exports/a2-v3/<文档 ID>-<导出 ID>/` | document.pdf、document.docx、content.json、snapshot.json；0700／0600 |
| `exports/a2-v3/verification-20261002-accepted/` | 本轮结构检查、数学核对、历史／新 PDF 预览、逐页正文差异统计及主代理目视记录；私有且 Git 忽略 |

导出 ID 绑定规范内容、用途、来源／审核状态、生成器版本、导出模块代码 SHA、依赖版本及字体配置／哈希。页脚短 ID 是内容快照 ID，完整生成环境及输出文件 SHA 见 snapshot.json。相同输入只复用通过文件哈希和完整性核对的旧输出；修改内容、状态、用途、代码或字体生成新目录。坏旧输出报冲突，不覆盖。新输出在私有暂存目录生成，Word 等后续失败或输入在生成期间变化时移除该暂存目录，不留下已发布的半份输出。

2026-10-05 的 PC／companion 增量将生成器升为 `a2.v4`，页脚改为中文状态及页码；完整快照身份仍保留在 `snapshot.json`，上文短 ID 描述为 v3 历史输出。新增独立 `companion_image` PNG 块仅允许家长答案；旧配对教学图、公式和用途约束继续执行，具体见 [PC 解析契约](pc-companion-contract.md)。

这是本机打印文件快照，并非数据库 `ExportSnapshot` 的完整修订关联，也不是 `ArchiveManifest` 备份：`archive_complete=false`。没有保存全部学习档案／审核／删除历史，不宣称可在空实例恢复全项目。

## 运行与验收

项目 `.venv` 安装依赖后，本机明确指定已有字体：

```bash
.venv/bin/python scripts/export_legacy_packet.py \
  --cjk-regular /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
  --cjk-bold /usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc \
  --math-font /usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf
```

默认只读取本机忽略清单，输出路径可配置，禁止与原来源目录重叠。此命令不启动 Web 或数据库，不读取孩子照片。私有包可以复制后经 `load_packet` 验证，渲染接口只需规范文档与字体；新渲染器不依赖原历史代码的绝对路径。

```bash
.venv/bin/python -m unittest discover -s tests/exports -p 'test_*.py' -v
.venv/bin/python scripts/verify_exports.py \
  --packet data/export-inputs/v3/a2de7c998a188e720061a802 \
  --report-root exports/a2-v3/verification-新的检查目录
```

实际环境：Python 3.12.3；本机已有 Poppler 24.02.0 的 pdfinfo／pdffonts／pdftotext／pdftoppm，后者用于 Word 地图和本地页面预览。所有命令使用参数数组与超时，没有通过 shell 拼接用户输入。报告目录须新建，以保留历史检查记录。后续 D1 再确定镜像中的工具／字体供应与许可；本轮没有应用镜像构建。

本轮最终验收：20 项渲染／契约／快照／字体测试通过；既有 26 领域＋8 索引转换＋7 私有包用例回归通过。五份 PDF 页数 8／12／5／2／2，共 29 页；字界、A4 尺寸、嵌入字体与换页通过。五份新 Word 的 62 个可编辑 OMML 与历史 Word、输入公式树逐项一致，正文／表格文字逐块一致，ZIP CRC、显式分页及动态页码字段通过。

主代理查看全部 29 页预览，并放大核对五处非零正文图像差异：24 页正文像素完全相同，5 页因富文本 run 规范化有局部字距／位置差异，数学符号及文字内容保留，无裁切、遮挡或意外换页。页脚因新增状态／版本标记单独处理。62 个公式结构及数学内容已人工核对；8 道复测题独立重算、220 个有限取值恒等式检查及新定义 G 的迭代样例通过，这些检查不等同自动证明系统或孩子掌握评价。

A2 当时尚未运行办公软件。2026-10-03 主代理另用隔离的 LibreOffice 7.4.7.2 Writer＋Math 验收五份 Word：8／12／5／2／2 页，共 29 页；原生分式 canary、字界及逐页目视均通过，原文件未改写。私有报告为 `artifacts/word-verification/59d1c17391f64dbfbdef946983b178b7/verification.local.json`。Microsoft Word 尚未实测，接收端字体替代仍可影响分页。Web 打印、数据库修订及用途隔离见[业务契约](business-web-contract.md)，联合恢复见[容器说明](container-deployment.md)。

可复验环境由 [Dockerfile.word-verifier](../Dockerfile.word-verifier) 构建，仅用于离线重排，不进入服务镜像。运行 [verify_word_layout.py](../scripts/verify_word_layout.py) 时显式提供镜像标签、所有者和 A2 来源报告；网络关闭、输入只读、输出使用新私有目录。Writer 的 Math 组件必须安装：验收曾发现缺失时 OMML 被静默留空，已用原生分式 canary 阻止此类误通过。工具不自动批准目视检查，报告先标 pending。
