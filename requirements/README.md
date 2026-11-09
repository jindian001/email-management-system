# 需求与设计资料

本目录存放 MailMind 的需求文档与示意图，供评审、答辩、交接使用，随仓库一起版本化。

## 目录

| 文件 | 内容 |
|---|---|
| [需求分析.md](需求分析.md) | 背景、目标、干系人、场景、功能/非功能需求、风险、验收指标 |
| [需求说明书.md](需求说明书.md) | 系统边界、角色权限、用例规格、接口/数据/业务规则、追溯矩阵、术语表 |
| `图示/01-用例图.md` | 参与者与用例 |
| `图示/02-组件架构图.md` | 分层组件与依赖方向（UML 组件图） |
| `图示/03-时序图-邮件接入与处理.md` | 从 IMAP 拉取到判定落库 |
| `图示/04-时序图-自动回复审核发送.md` | 检索、起草、护栏、审核、发送 |
| `图示/05-状态图-邮件生命周期.md` | 邮件主状态机（含隔离区放行回路） |
| `图示/06-类图-领域模型.md` | 9 张核心表与关系 |
| `图示/07-活动图-垃圾邮件过滤.md` | 级联判定与三档动作 |
| `图示/08-活动图-分类与回复决策.md` | 分类 → 放行闸门 → 起草/审核 |
| `图示/09-部署图.md` | 容器编排与外部依赖 |
| `图示/10-数据流图.md` | 数据在系统内的流转与存储 |

共 **10 张图**（用例/组件/时序×2/状态/类/活动×2/部署/数据流）。

## 怎么看图

- GitHub、VS Code（装 Markdown Preview Mermaid Support）、Typora、Obsidian 可直接渲染；
- 或把 ```mermaid 代码块贴到 <https://mermaid.live> 查看/导出 PNG、SVG。

## 与代码的对应

| 文档概念 | 代码位置 |
|---|---|
| 接入与同步 | `src/mailmind/connectors/`、`services/ingest.py` |
| 解析与特征 | `pipeline/parse.py`、`pipeline/features.py` |
| 垃圾过滤 / 分类 | `ml/spam.py`、`ml/rules.py`、`ml/classify.py` |
| 回复闸门 / 检索 / 生成 | `reply/policy.py`、`reply/retrieval.py`、`reply/generator.py` |
| 发送与审计 | `reply/sender.py`、`services/audit.py` |
| 接口 | `api/routers/` |
| 数据模型 | `db/models.py`（含 Alembic 迁移） |
