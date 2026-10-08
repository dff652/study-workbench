---
version: alpha
name: Study Workbench
description: 中文家庭学习工作台，以真实学习任务和可追溯证据为中心。
colors:
  background: "oklch(1 0 0)"
  foreground: "oklch(0.129 0.042 264.695)"
  card: "oklch(1 0 0)"
  card-foreground: "oklch(0.129 0.042 264.695)"
  popover: "oklch(1 0 0)"
  popover-foreground: "oklch(0.129 0.042 264.695)"
  primary: "oklch(0.208 0.042 265.755)"
  primary-foreground: "oklch(0.984 0.003 247.858)"
  secondary: "oklch(0.968 0.007 247.896)"
  secondary-foreground: "oklch(0.208 0.042 265.755)"
  muted: "oklch(0.968 0.007 247.896)"
  muted-foreground: "oklch(0.54 0.046 257.417)"
  accent: "oklch(0.968 0.007 247.896)"
  accent-foreground: "oklch(0.208 0.042 265.755)"
  destructive: "oklch(0.577 0.245 27.325)"
  destructive-foreground: "#ffffff"
  border: "oklch(0.929 0.013 255.508)"
  input: "oklch(0.929 0.013 255.508)"
  ring: "oklch(0.704 0.04 256.788)"
  chart-1: "oklch(0.646 0.222 41.116)"
  chart-2: "oklch(0.6 0.118 184.704)"
  chart-3: "oklch(0.398 0.07 227.392)"
  chart-4: "oklch(0.828 0.189 84.429)"
  chart-5: "oklch(0.769 0.188 70.08)"
  dark-background: "oklch(0.129 0.042 264.695)"
  dark-foreground: "oklch(0.984 0.003 247.858)"
  dark-card: "oklch(0.14 0.04 259.21)"
  dark-card-foreground: "oklch(0.984 0.003 247.858)"
  dark-popover: "oklch(0.208 0.042 265.755)"
  dark-popover-foreground: "oklch(0.984 0.003 247.858)"
  dark-primary: "oklch(0.929 0.013 255.508)"
  dark-primary-foreground: "oklch(0.208 0.042 265.755)"
  dark-secondary: "oklch(0.279 0.041 260.031)"
  dark-secondary-foreground: "oklch(0.984 0.003 247.858)"
  dark-muted: "oklch(0.279 0.041 260.031)"
  dark-muted-foreground: "oklch(0.704 0.04 256.788)"
  dark-accent: "oklch(0.279 0.041 260.031)"
  dark-accent-foreground: "oklch(0.984 0.003 247.858)"
  dark-destructive: "oklch(0.704 0.191 22.216)"
  dark-destructive-foreground: "oklch(0.129 0.042 264.695)"
  dark-border: "oklch(1 0 0 / 10%)"
  dark-input: "oklch(1 0 0 / 15%)"
  dark-ring: "oklch(0.551 0.027 264.364)"
  dark-chart-1: "oklch(0.488 0.243 264.376)"
  dark-chart-2: "oklch(0.696 0.17 162.48)"
  dark-chart-3: "oklch(0.769 0.188 70.08)"
  dark-chart-4: "oklch(0.627 0.265 303.9)"
  dark-chart-5: "oklch(0.645 0.246 16.439)"
  status-success: "#f0fdf4"
  status-success-foreground: "#166534"
  status-success-border: "#86efac"
  status-warning: "#fefce8"
  status-warning-foreground: "#854d0e"
  status-warning-border: "#fde047"
  status-danger: "#fff1f2"
  status-danger-foreground: "#9f1239"
  status-danger-border: "#fda4af"
  dark-status-success: "#052e16"
  dark-status-success-foreground: "#86efac"
  dark-status-success-border: "#166534"
  dark-status-warning: "#422006"
  dark-status-warning-foreground: "#fde68a"
  dark-status-warning-border: "#a16207"
  dark-status-danger: "#450a0a"
  dark-status-danger-foreground: "#fca5a5"
  dark-status-danger-border: "#991b1b"
typography:
  page:
    fontFamily: 'Inter, "Noto Sans SC", system-ui, sans-serif'
    fontSize: "24px"
    lineHeight: "1.3"
    fontWeight: 600
  section:
    fontFamily: 'Inter, "Noto Sans SC", system-ui, sans-serif'
    fontSize: "18px"
    lineHeight: "1.3"
    fontWeight: 600
  body:
    fontFamily: 'Inter, "Noto Sans SC", system-ui, sans-serif'
    fontSize: "15px"
    lineHeight: "1.55"
    fontWeight: 400
  small:
    fontFamily: 'Inter, "Noto Sans SC", system-ui, sans-serif'
    fontSize: "13px"
    lineHeight: "1.55"
    fontWeight: 400
  metric:
    fontFamily: 'Inter, "Noto Sans SC", system-ui, sans-serif'
    fontSize: "30px"
    lineHeight: "1.3"
    fontWeight: 600
rounded:
  control: "0.625rem"
spacing:
  unit: "0.25rem"
  compact: "0.5rem"
  field: "0.75rem"
  panel: "1rem"
  section: "1.5rem"
  page: "2rem"
  workspace: "90rem"
  settings: "66rem"
  reading: "60rem"
components:
  popover:
    backgroundColor: "{colors.popover}"
    textColor: "{colors.popover-foreground}"
    typography: "{typography.body}"
  accent:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    typography: "{typography.body}"
  muted:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.body}"
  destructive-button:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.destructive-foreground}"
    typography: "{typography.body}"
  reading:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  primary-button:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  secondary-button:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  muted-text:
    backgroundColor: "{colors.background}"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  success:
    backgroundColor: "{colors.status-success}"
    textColor: "{colors.status-success-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  warning:
    backgroundColor: "{colors.status-warning}"
    textColor: "{colors.status-warning-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  danger:
    backgroundColor: "{colors.status-danger}"
    textColor: "{colors.status-danger-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  dark-popover:
    backgroundColor: "{colors.dark-popover}"
    textColor: "{colors.dark-popover-foreground}"
    typography: "{typography.body}"
  dark-accent:
    backgroundColor: "{colors.dark-accent}"
    textColor: "{colors.dark-accent-foreground}"
    typography: "{typography.body}"
  dark-muted:
    backgroundColor: "{colors.dark-muted}"
    textColor: "{colors.dark-muted-foreground}"
    typography: "{typography.body}"
  dark-destructive-button:
    backgroundColor: "{colors.dark-destructive}"
    textColor: "{colors.dark-destructive-foreground}"
    typography: "{typography.body}"
  dark-reading:
    backgroundColor: "{colors.dark-background}"
    textColor: "{colors.dark-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  dark-card:
    backgroundColor: "{colors.dark-card}"
    textColor: "{colors.dark-card-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  dark-primary-button:
    backgroundColor: "{colors.dark-primary}"
    textColor: "{colors.dark-primary-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  dark-secondary-button:
    backgroundColor: "{colors.dark-secondary}"
    textColor: "{colors.dark-secondary-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  dark-muted-text:
    backgroundColor: "{colors.dark-background}"
    textColor: "{colors.dark-muted-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  dark-success:
    backgroundColor: "{colors.dark-status-success}"
    textColor: "{colors.dark-status-success-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  dark-warning:
    backgroundColor: "{colors.dark-status-warning}"
    textColor: "{colors.dark-status-warning-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  dark-danger:
    backgroundColor: "{colors.dark-status-danger}"
    textColor: "{colors.dark-status-danger-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
---
## Overview

学习工作台是中文家庭学习与资料整理工作区。学生首先看见当前学习者、题目和下一步；家长能够对照原图整理、查看每次作答与修订，并找到生成成果。原图、题目、真实作答、人工评价和复测关联保留各自身份。

## Colors

颜色以已部署的语义主题为基础；浅色弱化文字略加深以满足浅灰背景对比度，危险按钮分别定义亮／暗文字颜色。`dark-`前缀是本项目对深色模式的明确映射约定，生成器去掉前缀写入`.dark`，不是上游隐式主题功能。成功颜色仅表达已确认或已完成的操作状态；未知、待核对、待复测及错误必须有文字。图表、边框与焦点颜色不能因为规范lint通过就视为实际界面通过。

## Typography

正文15px、辅助13px、页标题24px、模块18px、核心数字30px。中文系统字体作为后备，不下载远程字体。正文行高1.55；公式不缩小到难以阅读，长名称允许换行。字号遵从实际角色，不把所有辅助信息都放大为标题。

## Layout

常规工作区最大90rem，设置66rem，连续阅读60rem，均受可用空间限制。间距采用4、8、12、16、24、32px。1280、1440、1920与200%缩放必须可完成连续任务。模块自然高度；来源图与编辑可并排，小窗口变纵向；大型表格仅局部滚动。作用域、导航和操作区稳定，已有内容优先，创建表单按需展开。

## Elevation & Depth

使用边框、背景与空间建立层级，避免大量同权重卡片和机械等高留白。重要任务优先，完整来源和解释展开后阅读。载入、失败、首次空白、筛选无结果、缺证据、未评价分别呈现原因和合适动作。

## Shapes

基础圆角10px，状态标签包含可读文字，按钮与主要操作区域至少44px高。颜色不是识别状态的唯一方式；主操作、次操作和危险操作明确分开。

## Components

同一页面只突出当前任务的主操作，支持键盘焦点与明确保存反馈。组件宣告的文字背景组合接受对比度检查，其余实际状态由浏览器检查。表格行详情与行内按钮不能互相误触；关闭表单、切页、取消离开和失败重试保持输入。

- 学习总览：当前对象 → 下一步与最近成果 → 范围摘要 → 展开的证据。
- 资料整理：资料列表 → 当前页与原图 → 整理／核对／生成；草稿与可练习题明确区分。
- 知识与题库：少量常用筛选 → 可扫描题目行 → 题目与来源；学生参考答案默认收起。
- 学习档案：已有学习者与记录优先；各次作答、前次关联、条件与修订分别可追溯。
- 进度与复测：今天／近期／逾期的任务与明确开始动作；资料处理进度属于资料整理。
- 文档中心：用途、格式、版本、检查与生成状态明确；最近成果可以直接找到。
- 设置：家庭成员及权限、模型与预算、外发与保留各有清晰作用域，不显示伪造活动或权限。

## Do's and Don'ts

一次独立成功、完成计划、生成答案不等于长期掌握；没有重复错误不等于表现良好。关闭AI仍能完成人工主流程，未知历史不补造，资料错误与学习者错误分开。

主题通过本项目生成器映射到现有CSS变量，禁止把上游导出直接覆盖主题。Web设计规范不改变打印规范、业务权限和正式数据。完整产品原则与验收继续以[整改主基线](docs/reviews/learning-system-ux-remediation-baseline-20261006.md)及[目标用户验收](docs/reviews/learning-system-target-user-acceptance-20261007.md)为准；截图、CLI、工程测试与真实用户结果分别登记。
