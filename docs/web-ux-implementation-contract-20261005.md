# Web 体验实施契约（2026-10-05）

用户已同意执行 [体验改进方案](web-ux-improvement-plan-20261005.md)。工作树为 `codex/web-ux-improvement`，起点 main `4b70f03`。本契约固定公共接口和文件归属；实现、验证、提交及部署按实际结果另记，不将实际家庭反馈或第二期手机验收伪写为完成。

## 公共呈现与模块接口

- 主框架常显六个业务入口，设置置底；13rem 桌面侧栏、一条紧凑全局家庭／学习者上下文，取消整个主区的 `88rem` 限制。单个可选对象直接显示名称；多个对象使用有名称的选择框。模块不再重复大号页面标题、家庭卡片或“当前学习者”卡片；具体资料／记录名称和归属仍须清楚。
- 公共 `components/workspace-tabs.tsx` 提供 `WorkspaceTabs`、`WorkspacePanel`、`WorkspaceHeading`。Tabs 参数为 `id`、`label`、`tabs: {value,label,count?}[]`、`value` 和 `onChange(value)`；Panel 参数为同一 `id`、自身 `value`、当前 `active`。面板保持挂载，以 `hidden` 切换，保留输入；方向键移动焦点，Enter／Space 激活。错误、草稿和冲突在当前操作区可见。
- 主代理拥有 `AppRoute.tab?: string` 及顶层 URL `tab` 参数。模块增加可选 `initialTab?: string`、`onTabChange?: (value: string) => void`，保持既有调用兼容；模块校验自己允许的值，外部 tab 变化同步面板但不重新初始化编辑数据。用户切 Tab 回调主代理，主代理更新当前 URL，不触发离开未保存表单的确认。所有实际数据范围仍由原家庭／学习者／资料 ID 和权限控制。
- 资料模块建议 `pages`／`content`／`solutions`／`tasks`；进度模块 `plans`／`evidence`／`materials`；解析模块 `editor`／`outputs`／`history`。已存在的解析 `initialPanel` 与旧深链接继续兼容。资料选择／搜索等 UI 状态范围正确，不通过 raw ID、JSON 或协议字符串向用户说明。
- 资料入口的 `material`／`q`／`page` 参数保留选中资料、已提交搜索和页码；自动首选资料替换当前 URL，随后切换资料追加浏览器历史，搜索和翻页更新当前 URL。上下文回填读取最新路由，保留同次更新刚写入的资料和 Tab。失效家庭回退或切换家庭时清除原定位；选中资料可在列表当前页之外单独按权限读取。题面和整页阅读分别上报未保存状态，切 Tab 保留输入，销毁编辑区的动作确认后才继续。
- 讲解客户端地址归文档模块，跨模块时清除原资料定位与 Tab。进度工作区使用可选 `onUnsavedChange?: (dirty: boolean) => void` 接入 App 的离页保护，新增及各行操作分别跟踪再聚合；一项保存或明确放弃不清除其他项。切 Tab／状态筛选保留编辑区，刷新或关闭表单在销毁输入前确认；卸载后的迟到请求不清除新模块状态。
- 原有 `ContentWorkspace`、生成和草稿 API、版本绑定、并发／迟到响应规则、请求键及校验保持。公有 `api.getErrorMessage` 已过滤技术响应并保留业务提示；导入解析的严格校验继续执行，但在对应模块将错误表达成可操作中文。不要用宽松解析或吞掉未知内容解决文案问题。

## 原有业务模板

- `features/workspace/page.tsx`／`page.css` 与 API 适配器归主代理。公共样式支持 `workspace-toolbar`、`workspace-actions`、`workspace-columns`、`workspace-table-wrap`、`workspace-reading`，按任务组织版面；不把所有 section／fieldset 包成大卡片。
- 需要模块 Tab 的模板使用一个 `class="workspace-tabs" role="tablist" data-workspace-tabs` 容器；每个原生 `button type="button" role="tab"` 有 `id`、`aria-controls`、`data-workspace-tab="英文短值"`、`aria-selected`。对应 `section` 有 `id`、`role="tabpanel"`、`aria-labelledby`、`data-workspace-panel`。
- 服务端默认不隐藏这些 section，保留直接访问旧业务 URL 的人工流程；工作台适配器按当前 tab 渐进增强。公共代码负责焦点、切换、URL 回调，并自动打开错误、锚点或恢复字段所在面板。worker 不添加自己的页面脚本，不改变适配器白名单或提交接口。
- 来源和操作表单保持 CSRF、原动作、名称与取值、版本绑定及权限条件。原图／作答详情用对照版面；每次记录和修订仍分别呈现。只修改呈现不产生迁移，不改变导出文件的数学内容或渲染器。

## 责任与验证

| 执行者 | 唯一可写范围 | 输出与必要验证 |
| --- | --- | --- |
| 主代理 | App、路由、公共组件／样式／api／types、通用草稿、WorkspacePage／适配器、公共模板、知识题库／打印入口／设置、脚本与文档 | 公共契约、七入口、跨模块流程、完整差异及独立验收 |
| Luna6-A | `frontend/src/features/materials/`、`content/`、`solutions/` | 资料列表与对照编辑、解析面板、导入文案；相关模块测试 |
| Luna6-B | `frontend/src/features/evidence/`、`app/web/templates/learning/` | 作答列表／详情与评价来源对照、紧凑总览；相关模块测试 |
| Luna6-C | `frontend/src/features/progress/`、`app/study/templates/study/` | 进度三 Tab、计划表格／筛选／详情及历史；相关模块测试 |

worker 不是唯一修改者，不回退他人编辑，不修改共有文件；共享接口需求先报告主代理。模块内测试可改，跨模块 App／浏览器／Django 测试由主代理处理。worker 不提交、推送、部署、安装依赖或操作线上数据；临时证据只写自己的被忽略目录。每个 bounded task 由一名指定 `luna6-worker`（`gpt-6-luna`）执行，三个非重叠任务可以并行。

复用与当前锁文件一致的已安装依赖，不新增 UI 框架。主代理先验证公共组件与导航，再启动三模块并行；并行结束后完整审查、独立跑前端与构建、必要 HTTP／浏览器及相关专项。实际家庭试用需实际反馈，Word 实开与真实模型仍单列；手机专项属于第二期。
