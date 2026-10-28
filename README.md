# MailMind · 智能邮箱管理系统

邮件 **自动分类**、**垃圾邮件过滤**、**自动回复** 三件套的可运行实现。
设计依据见 [exp.md](exp.md)（架构、选型、实施步骤、评测方案、实现偏差记录）。

- 后端：Python 3.11+ / FastAPI / SQLAlchemy / Celery
- 接入：IMAP、Gmail API、Microsoft Graph（读取）；SMTP / Gmail API（发送）
- 存储：PostgreSQL（生产）/ SQLite（测试）；对象存储支持本地目录、内存、S3/MinIO
- 模型：纯 Python TF-IDF + 朴素贝叶斯（零依赖、确定性）+ 规则引擎 + LLM 复核与起草
- 前端：无构建管理台（`/ui/`，index.html + app.js + style.css），直接调用 REST API

## 数据库迁移

```bash
make migrate                                  # alembic upgrade head
# 或直接： PYTHONPATH=src .venv/bin/python -m alembic upgrade head
```

初始迁移见 `migrations/versions/`，与 ORM 模型保持一致（有测试守护）。

## 快速开始

```bash
# 1) 环境
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"

# 2) 跑测试（223 个，全部离线，不需要邮箱/网络/Redis）
make test

# 3) 生成演示数据（内存账号 + 知识库 + 3 封样例邮件）
make demo

# 4) 启动
make serve
# 管理台： http://127.0.0.1:8080/ui/
# OpenAPI: http://127.0.0.1:8080/docs
```

### 三分钟走通一遍完整链路

```bash
# 建账号（provider=memory 便于本地演示；真实账号用 imap，并配置 imap_host/secret）
curl -s -X POST localhost:8080/api/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"email":"support@example.com","provider":"memory"}'

# 导入知识库
curl -s -X POST localhost:8080/api/v1/kb/documents \
  -H 'Content-Type: application/json' \
  -d '{"title":"退换货政策","content":"商品签收后 7 天内可无理由退货，运费由买家承担。"}'

# 投递一封咨询邮件（自动分类 → 生成回复草稿）
curl -s -X POST localhost:8080/api/v1/accounts/1/ingest \
  -H 'Content-Type: application/json' \
  -d '{"raw":"From: tom@customer.com\nTo: support@example.com\nSubject: 退货咨询\nMessage-ID: <m1@customer.com>\n\n我买的东西想退货，运费谁承担？"}'

# 查看待审核草稿 → 审核通过并发送
curl -s localhost:8080/api/v1/replies?status=pending_review
curl -s -X POST localhost:8080/api/v1/replies/1/approve \
  -H 'Content-Type: application/json' -d '{"reviewer_id":"ops"}'
```

## 管理台（`/ui/`）

9 个页面，全部走真实 API，不需要前端构建：

| 页面 | 能力 |
|---|---|
| 总览 | 邮件量/垃圾率/待审/隔离数，分类与判定分布条形图，最近邮件 |
| 收件箱 | 搜索（主题/正文/发件人）、状态与类别过滤、游标分页、判定标签、一键 AI 起草 |
| 邮件详情 | 正文、附件、判定分数与**命中原因**、分类得分、草稿状态、同会话列表、下载原始 EML |
| 隔离区 | 放行并自动加白名单、删除、查看详情 |
| 自动回复审核 | 改草稿 → 通过发送 / 拒绝，显示引用与风险标记 |
| 账号 | 新建 IMAP/Gmail/Graph/演示账号（凭据加密）、同步、删除、同步时间 |
| 规则 | 增删启停 + **规则试算**（输入一封邮件看判定与命中规则） |
| 知识库 | 导入（自动切片）、检索测试、删除 |
| 审计 / 反馈 | 审计动作过滤与详情 JSON、反馈样本列表（重训数据来源） |

## 核心设计

```
IMAP/Gmail/Graph ──► 解析(MIME) ──► 特征工程 ──► 垃圾级联判定 ──► 分类 ──► 回复策略 ──► 检索+生成 ──► 护栏 ──► 审核/发送
                                      │              │             │
                                      │       规则 → NB → LLM   consult/billing/…
                                      ▼
                              PostgreSQL(元数据) + 对象存储(原始 EML)
```

1. **垃圾过滤是级联的**：白名单 → 强规则（黑名单/认证/信誉）→ TF-IDF+NB → 模糊区 LLM 复核 → 三档动作
   （`pass` / `tag` 打标照常投递 / `quarantine` 隔离）。**误杀率优先于召回率**。
2. **分类三层**：规则（发件人/关键词）→ 朴素贝叶斯 → 低置信度走 LLM few-shot。
3. **自动回复默认"AI 起草 + 人工审核"**：必须同时满足 RFC 3834 全部反回环检查、类别白名单、
   24h 冷却、线程深度限制、免打扰时段；生成必须有 KB 引用，护栏可拒绝或转人工。
4. **一切可回放**：原始 EML 按内容哈希存对象存储，模型升级后可用 `mailmind train` + 重处理重跑历史邮件。

## REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查（公开） |
| POST/GET/DELETE | `/api/v1/accounts` `/api/v1/accounts/{id}` | 账号管理 |
| POST | `/api/v1/accounts/{id}/ingest` | 投递一封原始邮件（联调/回放） |
| POST | `/api/v1/accounts/{id}/sync` | 增量同步（provider=memory 时需注入 MemoryConnector 测试替身） |
| GET | `/api/v1/mails` | 列表，支持 `account_id/status/category/spam_action/q/page/size/cursor`（返回 `next_cursor`） |
| GET | `/api/v1/mails/{id}` `/raw` `/thread` | 详情 / 原文下载 / 会话 |
| POST | `/api/v1/mails/{id}/feedback` | 反馈（spam / category / reply_quality） |
| POST | `/api/v1/mails/{id}/reply/draft` | 按需 AI 起草 |
| POST | `/api/v1/mails/{id}/reply/send` | 最新草稿一步审核并发送 |
| GET/POST | `/api/v1/quarantine` `/{id}/release` `/{id}/delete` | 隔离区 |
| GET/POST | `/api/v1/replies` `/{id}/approve` `/{id}/reject` | 审核队列 |
| GET/POST/PATCH/DELETE | `/api/v1/rules` | 黑白名单/关键词/认证/信誉/分类路由 |
| GET/POST/DELETE | `/api/v1/kb/documents` `GET /api/v1/kb/search` | 知识库 |
| POST | `/api/v1/rules/test` | 规则试算：给一封邮件，返回判定/命中规则/特征（不落库） |
| POST | `/api/v1/admin/retrain` | 用反馈数据重训并热替换模型 |
| GET | `/api/v1/audit` `/api/v1/feedback` | 审计日志 / 反馈样本 |
| GET | `/api/v1/metrics/overview` | 运营指标 |

鉴权：配置 `MAILMIND_API_KEY` 后，所有非 health 接口需要 `X-API-Key` 头。

## 配置

全部通过 `MAILMIND_` 前缀环境变量覆盖（见 [.env.example](.env.example)），关键项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `MAILMIND_DATABASE_URL` | `sqlite+pysqlite:///./var/mailmind.db` | 生产用 `postgresql+psycopg://...` |
| `MAILMIND_API_KEY` | 空 | 生产必须设置 |
| `MAILMIND_SECRET_KEY` | dev 值 | 邮箱凭据加密密钥，生产必须改 |
| `MAILMIND_SPAM_PASS_THRESHOLD` | 0.70 | ≥ 该值打标 |
| `MAILMIND_SPAM_QUARANTINE_THRESHOLD` | 0.95 | ≥ 该值隔离 |
| `MAILMIND_AUTO_REPLY_SEND_MODE` | `review` | `review` 人工审核 / `auto` 高置信自动发送 |
| `MAILMIND_AUTO_REPLY_COOLDOWN_HOURS` | 24 | 同一发件人冷却期 |
| `MAILMIND_QUIET_HOURS_START/END` | 空 | 免打扰时段，如 `22:00` / `08:00` |
| `MAILMIND_LLM_PROVIDER` | `template` | `template` 离线确定性 / `openai` 兼容 DeepSeek 等 |
| `MAILMIND_COOLDOWN_BACKEND` | `memory` | `redis` 时多实例共享冷却，Redis 不可用自动降级 |
| `MAILMIND_API_RATE_LIMIT_PER_MINUTE` | 0 | >0 时按 `X-API-Key`/IP 限流，超限 429 |
| `MAILMIND_STORAGE_BACKEND` | `local` | `local` / `memory` / `s3`（需 `pip install 'mailmind[s3]'`） |
| `MAILMIND_S3_BUCKET` / `S3_PREFIX` / `S3_ENDPOINT_URL` / `S3_REGION` | 空 | S3 或 MinIO 参数 |

## 目录结构

```
src/mailmind/
├── core/        配置、日志（trace_id）、凭据加密
├── db/          ORM 模型（9 张表）、会话
├── connectors/  IMAP / Gmail / Graph / SMTP / 内存实现 / 工厂
├── pipeline/    MIME 解析、归一化、PII、特征、会话归并
├── ml/          分词、NB、规则、垃圾级联、分类、embedding、LLM、护栏、种子语料
├── reply/       放行策略、混合检索、RAG 生成、发送
├── services/    接入、处理链、查询、知识库、训练、审计
├── tasks/       Celery 应用与任务
├── api/         FastAPI 应用、依赖、路由
└── static/      管理台单页
migrations/      Alembic 迁移（alembic.ini 在仓库根目录）
tests/           仅本地保留（不推送）
```

## 测试

```bash
make test        # 293 passed, 1 skipped
make lint        # ruff + mypy
```

测试覆盖：解析/MIME/编码、归一化与 PII、特征、规则引擎、朴素贝叶斯、级联判定、分类、
护栏、检索、放行策略（RFC 3834）、生成、发送、接入幂等与 UIDVALIDITY、API 全量、
IMAP/SMTP/Gmail/Graph 协议解析（假 client 与 MockTransport）、任务函数、对象存储（含 S3 Stubber）、
凭据加密、Redis 冷却与 API 限流、游标分页、Alembic 迁移一致性、PostgreSQL DDL 兼容性、管理台静态契约
（tab↔渲染函数、**前端调用 ↔ OpenAPI 路径一致性**、Node 语法校验），以及一个
**召回率/误杀率验收测试**（`tests/test_quality.py`）。

真实 PG 端到端用例默认跳过，配置后启用：

```bash
MAILMIND_TEST_PG_URL=postgresql+psycopg://user:pass@localhost:5432/mailmind_test make test
```

## 部署

```bash
docker compose up --build
# API: http://localhost:8080   管理台: http://localhost:8080/ui/
```

生产清单：PostgreSQL（pgvector 镜像已就绪）、Redis（Celery broker）、域名 SPF/DKIM/DMARC、
`MAILMIND_API_KEY` 与 `MAILMIND_SECRET_KEY`、备份策略、告警（队列积压/同步延迟/误杀突增）。

## 已知边界

- 未做多租户行级权限（单实例单组织），接入多租户需在 `Account` 上加 `tenant_id` 并加全局过滤。
- 检索为 BM25 + 哈希向量混合（万级知识库足够），更大规模应换 pgvector/BGE-M3 + 重排模型。
- 自动回复默认不会真正"自动发出去"：`MAILMIND_AUTO_REPLY_SEND_MODE=review` 时必须人工点通过。
- 更多偏差与踩坑记录见 [exp.md 附录 C](exp.md)。
