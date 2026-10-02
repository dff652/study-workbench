# A1b 持久化与审核契约

日期：2026-10-02（Asia/Shanghai）。A1b-P 持久化与审核事务已验收；同日用户另行同意 A1b-I，见[旧索引导入契约](legacy-import-contract.md)。最终运行状态见 [DEV_STATE](../DEV_STATE.md)。这是核心契约的数据库子集，不代表 M1a 或容器化服务已经交付。

## 1. 承载与范围

采用 Django 5.2 LTS、psycopg 3、PostgreSQL 16；依赖精确版本见 [requirements.txt](../requirements.txt)。Django 5.2 的官方延长支持计划至 2028 年 4 月；本轮选择其当前补丁版本 5.2.17。[Django 官方发布与支持表](https://www.djangoproject.com/download/)

复用 Django ORM、迁移、认证账号和事务，定制家庭权限、不可变版本、审核及来源查询。服务使用 `atomic()` 与 PostgreSQL 行锁；所有支持的读写先锁定同一个 Household，家庭内串行处理，跨家庭独立。这适合当前家庭规模；SQLite 不支持这里需要的 `select_for_update()` 行锁语义，不作为并发验收替代。[Django 事务说明](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)、[Django 行锁说明](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)

A1b-P 当时未启动 Web；后续 B1 已实现登录、会话及私有上传／审核页面，见[人工 Web 契约](manual-web-contract.md)。没有管理后台或生产部署。认证账号与学习者档案是不同身份，家长账号不自动成为孩子的作答作者。

## 2. 物理记录与关系

| 模型 | 保存内容与关键约束 |
| --- | --- |
| Household／HouseholdMember | 家庭范围和 Django 账号成员关系；owner／reviewer 可写及审核，viewer 只读；非成员及已停用账号不能访问 |
| ImageRecord | 不变的原图元数据；家庭内稳定 ID、SHA-256 分别唯一；真实文件核验由 A1b-I 私有包及 B1 文件服务承担 |
| EntityRecord | 封闭类别、稳定 ID、不可变身份；家庭／类别／ID 唯一；最新 `head_revision` 与可空 `published_revision` 分开 |
| RevisionRecord | 全局唯一修订 ID、同实体连续版本号、前版外键、封闭类型的 A1a JSON 内容快照、哈希、依赖头向量；区域版本另外有原图外键 |
| RevisionDependency | 不变的精确版本外键；家庭一致且角色与源／目标类别匹配；角色／位置唯一 |
| EvidenceRecord | 精确原图和可空区域版本外键、用途、维度、顺序与缺口；整图缺坐标须明确标记，区域必须属于同一原图且几何有效 |
| ReviewDecision | 不变的审核动作、实际账号、理由、预期内容头、完整依赖向量、前一个审核决定、请求键及时间 |
| ReviewProjection | 可更新的当前审核状态和对应审核决定；已发布指针只允许指向实际 accepted 版本 |
| RequestReceipt | 不变的成功请求凭据；家庭内请求键唯一，记录操作、账号、内容摘要和原结果 |

知识、方法、题型、题目、观察、作答、评价、勘误、区域及三种题目关联使用共享修订表，但类别和可连接的角色是封闭集合，不接受任意图节点。内容由领域层按具体 dataclass 校验；外键、唯一约束及 PostgreSQL 触发器再约束类型、家庭范围、连续版本、指针和不可变记录。[models.py](../app/persistence/models.py)、[数据库触发器](../app/persistence/migrations/0002_postgresql_guards.py)

父题、父方法、作答使用的题目／观察、评价对应的作答／题目／勘误、勘误目标以及三种关联端点均固定到精确修订。每份来源记录另保存原图和区域外键。学习者与逐次作答的稳定身份关系仍保存在经过校验的封闭身份快照中，未将每个内容字段拆成独立列。

## 3. 内容快照与审核分离

A1a 的 `review_state`／`reviewed_by` 属于已封存快照及其哈希。数据库入库后不改写它们；即使输入快照标为 accepted，入库仍建立 draft 投影，不自动发布。实际审核者、动作和状态来自 ReviewDecision／ReviewProjection。

离线 `validate_bundle()`、序列化、反序列化及合并的默认行为保持 A1a 语义。持久化适配显式传 `check_snapshot_reviews=False`：只把离线审核资格检查交给事务服务；类型、哈希、身份、历史、坐标、未知理由和引用完整性仍须通过。该选项不代表审核或授权。这样，实际已审核但内容快照仍为 draft 的勘误能够被新题目版本引用，不需要重写勘误历史或伪造快照状态。[领域校验](../app/domain/validation.py)、[映射](../app/persistence/adapter.py)

历史读取 `read_snapshot_bundle()` 返回原内容快照，只用于追溯。它不包含完整实际审核记录，不能当作数据库归档，也不能把离线快照筛选函数当作实时学习者档案结论。当前索引 `published_trace()` 使用实际已发布指针和审核投影；关联的精确端点也必须仍是当前发布版本。新版本发布后旧关联仍保留在历史，但不会混进当前索引。

## 4. 支持的事务接口

[services.py](../app/persistence/services.py) 提供以下家庭权限入口；直接 ORM 写入仅用于迁移、底层约束测试和受信任维护，不替代业务接口。

| 接口 | 输入 | 输出与失败条件 |
| --- | --- | --- |
| `create_household` | 活跃账号、家庭 ID | 新家庭及 owner 成员关系 |
| `stage_bundle` | 完整的同家庭合成关系包、请求键、`ObjectKey → expected_head` | 追加图像元数据／身份／修订及依赖，返回新增数；不发布；现有实体追加必须提供当前预期头 |
| `review_context` | 账号、家庭、修订 ID | 当前内容头、封存的完整依赖向量、当前审核决定 ID、状态；草稿依赖改变显示 stale |
| `review_revision` | accept／reject／withdraw、理由、预期内容头、完整依赖向量、预期审核决定 ID、请求键 | 追加审核并原子更新投影、发布指针和请求凭据；冲突不留下部分结果 |
| `read_snapshot_bundle` | 账号、家庭 | 所有原内容快照及历史，审核快照字段保持原值 |
| `published_trace` | 账号、家庭、具体知识／方法／题型节点或原图／区域 | 当前题目、节点修订 ID 和按序原图证据，支持双向追溯 |

依赖向量由服务从精确引用及区域递归生成，包含作答、观察、题目、勘误、父级与区域等所有可变实体的当时最新头；不信任调用者选择的子集。自身内容头另外检查，原图和学习者身份不可变。接受时在同一家庭锁内比较全部依赖头；历史作答可引用旧题目版本，但待审核期间任一相关头改变都会使接受请求过期。

审核还比较前一个 ReviewDecision ID；内容头未改变时，并发接受／拒绝也只能有一个请求成功。迟到的接受请求不能覆盖已发生的撤回。每个修订的审核链只能有一个后继，数据库唯一约束采用 PostgreSQL 的 NULLS NOT DISTINCT；运行基线为 PostgreSQL 16。

新草稿及拒绝新草稿保留旧发布版本。撤回当前发布版本清空发布指针，原内容和全部审核历史保留。撤回不要求依赖仍新鲜，否则过期依赖会妨碍移除发布内容；仍须提供原完整向量、当前内容头及审核游标。

接受资格重新检查完整题干、知识定义、答案／过程两个评价维度、已实际审核的勘误，以及关联端点是否实际发布；每个题目修订只能有一个已发布的主方法关联。UNKNOWN 评价有依据和未知理由也能被人工审核，但审核不推断独立掌握，课堂笔记、提示状态、作者未知、空白或不可读字段保持原样。讲义勘误仍独立于孩子评价。

同账号／操作／内容／预期状态的同请求键重试返回原结果，即使头已改变；同请求键改内容、换账号或换操作明确冲突。失败事务不写成功凭据。内容修正通过新修订及独立审核完成，不通过修改旧审核或旧内容完成。

## 5. 开发验证与交付边界

先在项目 `.venv` 安装固定依赖，再运行隔离验证：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/run_persistence_tests.py
```

脚本要求 Docker 可用且指定 PostgreSQL 镜像已在本机缓存；不自动拉取。启动带随机归属标签的临时容器，`network=none`、不映射端口、内存上限 512 MiB、数据库为 tmpfs，仅通过私有临时 Unix socket 访问。覆盖调用者的数据库配置，只使用虚构数据，执行系统检查、迁移无漂移、迁移正反向和完整测试，结束删除自有容器与临时目录。[验证脚本](../scripts/run_persistence_tests.py)

单独使用 `manage.py` 时需显式提供 [配置示例](../.env.example) 的变量，它不会自动读取 `.env`；没有默认数据库地址。合成脚本中的本地 trust 认证与测试密钥仅服务于隔离临时实例，最终服务的配置和部署在 D1 实现。

A1b-P 当时没有读取真实图片或 81 条索引；后续 A1b-I 增加原始 JPEG 私有副本、旧索引包及 LegacyImportBatch／LegacyIndexEntry，真实导入仅在自有临时数据库验证。学习者身份快照仍只追加不可覆盖，可编辑档案版本另行设计。完整备份恢复、资料集／页序、派生图映射、拆合谱系、模型运行、打印快照及资料删除仍未实现。数据库验证不构成应用容器交付；Dockerfile／Compose、浏览器人工流程与 D1 验收仍待后续授权。
