# A1b-I 旧索引导入契约

日期：2026-10-02（Asia/Shanghai）。用户同意实施旧 81 条索引的可追溯导入；最终运行结果见 [DEV_STATE](../DEV_STATE.md)。这是本机私有文件及隔离 PostgreSQL 的验收，不代表 Web、完整题库、恢复或容器化应用交付。

## 输入与输出

输入使用既有 `docs/source-inventory.local.json` 指定的来源，校验大小及 SHA-256 后读取 23 张 JPEG、v3 `question_catalog.json` 和脚本中的 `GROUPS` 字面量。只用 AST 读取分组定义，不执行旧脚本。其他 PDF／Word、NAS 资料及渲染脚本不迁移，不重复全量盘点。

输出为私有 `data/originals/<sha256>.jpg` 和 `data/imports/<家庭与数据集摘要>/`。照片逐字节复制，不旋转、不裁切、不去笔迹；记录原始像素宽高。JPEG 使用 [Pillow Image.open/load](https://pillow.readthedocs.io/en/stable/reference/Image.html) 只读解码，单文件上限 32 MiB、像素上限 4000 万。首次创建的目录 `0700`、文件 `0600`；拒绝开放权限的数据目录和离开指定根目录的路径。全部私人内容被现有 Git 忽略规则覆盖。

| 包内文件 | 内容及用途 |
| --- | --- |
| `catalog.source.json` | 原索引 JSON 字节副本，保留九个原字段 |
| `groups.json` | 由原脚本字面量提取的六组名称，不运行脚本 |
| `bundle.json` | 带稳定 ID、修订哈希、父子与来源引用的核心关系包 |
| `manifest.json` | 来源校验值、像素元数据、原行顺序及 ID 对照、预期／实际数量、来源摘要 |
| `verification.local.json` | 主代理真实索引验收的聚合结果；只有验收成功才写入 |

包是这批旧索引的可复现输入，不能替代完整数据库备份。数据库审核、后续修订、学习者记录及完整文件生命周期不包含在此归档中。

## 映射与未知

| 来源 | 保存方式 |
| --- | --- |
| 81 条索引、61 个根题号 | 81 条原行记录＋91 个 Question：10 个父节点由题号层级补出，明确为无原索引行的容器 |
| `book/num` | 命名空间内的稳定题目身份；解析 `N`、`N(k)`、`N(k)-m`，父子关系固定具体修订 |
| `photo` | 按六位 token 精确匹配照片，斜杠顺序保留；整图引用并标 `region_missing`，不虚构坐标 |
| 六个 `group` | 六个草稿 Method 名称；内容为空，81 个主关联保留，明确数字前缀的 `aux` 形成 18 个辅助关联 |
| `feature/method/tag/tip/aux` | 在原行 `raw` 中逐字段保留；特征摘要不是完整题干，旧提示不是实际发生的提示事件 |
| 23 张照片 | 23 个 SourceImage 和 23 个未知 SourceObservation；22 张有索引引用，剩余 1 张不虚构题目关联 |

所有 Question 的原题干、工作题干为空，缺口为 `printed_text/working_text/region_coordinates/attempt_source`。父容器的整图证据为自身与后代照片的有序并集；原行的 `photo_tokens` 单独保存原始顺序。W1 第 8 题的两张照片顺序保持。

未知观察不确认作者、可读性、实际日期或学习者身份；清单登记时间与包准备时间均不是作答日期。不新增学习者、逐次作答、评价、知识条目、独立题型或勘误，不自动发布，也不根据分类、笔迹或提示推断掌握。讲义勘误及孩子错误仍需分别收集证据、审核和追加版本。

## 原子性与追溯

本机准备使用私有文件锁；完整校验后原子公开包目录，异常只清理自己新增的临时文件和照片副本。已存在的内容寻址文件只核对，不覆盖。重复准备保留原包时间与修订哈希；原清单或来源改变时同一数据集明确冲突，使用新的数据集键另行处理，不静默替换。

数据库入口 [import_prepared](../app/imports/services.py) 再次比对原 JSON 字节和原行，重建映射并校验关系包，避免文件校验后发生内存修改。锁定家庭后验证当前有效 owner／reviewer 权限，在一个事务内追加领域记录、幂等请求凭据、LegacyImportBatch 和 81 个 LegacyIndexEntry。`(household,dataset_key)` 唯一；相同来源摘要重试返回原批次、新增数为零；来源不同拒绝。重试不会回退后来的题目修订或原索引固定引用。viewer 可查，不能导入；停用或家庭外账号不能写，重试仍检查权限。

导入批次与原行在 PostgreSQL 禁止 UPDATE／DELETE。插入原行必须匹配批次清单中的原序号、字段及引用，题目／方法引用另有家庭与类型防线。原始内容语义、文件哈希和完整包映射由受支持的入口校验，直接 ORM 维护不能替代该入口。

[legacy_trace](../app/imports/services.py) 按家庭与数据集查询册别／题号、照片 token 和主／辅助组。`entries` 返回原行与直接照片顺序；`questions` 返回固定修订及整图证据，包含补出的父节点。`index_state=draft`，与正式已审核的 published_trace 分开。没有索引引用的照片返回来源记录、空题目集合，保留未知。

## 命令与验收边界

在项目根目录，以现有私有清单准备：

```bash
.venv/bin/python scripts/import_legacy_catalog.py prepare --household study-family --dataset g5-20261001-v3
.venv/bin/python scripts/import_legacy_catalog.py validate --package data/imports/4e571556d8649c5b49f6572e
.venv/bin/python scripts/run_persistence_tests.py --legacy-package data/imports/4e571556d8649c5b49f6572e --data-root data
```

最后一条只用自有临时 PostgreSQL：禁用网络、无发布端口、tmpfs 数据目录，覆盖调用者 SWB 配置；先跑全部合成测试及迁移正反向，再实际导入本机这批索引并重复执行。结束删除数据库、容器与 socket，私有包和照片副本保留。真实验证脚本拒绝缺少私有归属标记的数据库。

`import` 子命令用于另行指定的数据库，必须显式提供 SWB 环境变量、现有家庭及 `--actor-id`；不会创建账号／家庭或部署服务。本轮没有对常驻数据库执行导入，没有留存应用数据库。

验收覆盖：81 原行和九字段、61 根题／91 节点、23 图片哈希、99 方法关联、23 未知观察；全部节点及原图双向查询、跨页顺序、重复无新增、后续修订不回退、并发只一个批次、晚期失败完整回滚、权限及原生来源防覆盖。真实图像只验证字节、可解码性和尺寸，未识别数学内容、作者或空白状态。

## 文件所有权与下一步

一个 `luna6-worker / gpt-6-luna` 负责 `app/imports/{__init__,catalog}.py` 与 `tests/imports/{__init__,test_catalog}.py` 的纯转换。主代理负责 package／模型／两份迁移／事务与追溯、CLI／隔离验收脚本、其余导入测试、依赖／配置衔接及文档；审查全部实际差异并独立运行验收。原 A1a 领域契约和 fixture 保持。

随后另获授权的 A2 已提取现有渲染器，明确公式／字体并核对五份旧文档，实际范围与 Word 分页限制见[打印契约](export-contract.md)。随后 B1 已实现新人工资料的上传／框选／审核页面，见[人工 Web 契约](manual-web-contract.md)；旧索引的完整知识管理界面待 B2a 接入，不将旧摘要当作题干。各阶段授权边界见[实施分工](implementation-plan.md)，不自动进入下一阶段或部署。
