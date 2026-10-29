# MailMind · 智能邮箱管理系统

邮件 **自动分类**、**垃圾邮件过滤**、**自动回复** 三件套的可运行实现。
设计依据见 [exp.md](exp.md)（架构、选型、实施步骤、评测方案、实现偏差记录）。

- 后端：Python 3.11+ / FastAPI / SQLAlchemy / Celery
- 接入：IMAP、Gmail API、Microsoft Graph（读取）；SMTP / Gmail API（发送）
- 存储：PostgreSQL（生产）/ SQLite（测试）；对象存储支持本地目录、内存、S3/MinIO
- 模型：纯 Python TF-IDF + 朴素贝叶斯（零依赖、确定性）+ 规则引擎 + LLM 复核与起草
- 前端：React 19 + TypeScript + Vite 管理台（源码 `web/`，构建产物由 FastAPI 托管在 `/ui/`）

## 数据库迁移

```bash
make migrate
PYTHONPATH=src .venv/bin/python -m alembic upgrade head
```

初始迁移见 `migrations/versions/`，与 ORM 模型保持一致（有测试守护）。

## 快速开始

> ⚠️ 命令块不含行内注释。macOS 默认的 zsh 未开启 `interactive_comments`，
> 把 `# 说明` 一起粘贴会被当成参数（`unrecognized arguments: # ...`）。

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
make test
make demo
make serve
```

依次是：建虚拟环境并安装、跑测试（全部离线）、生成演示数据、启动服务。
管理台 <http://127.0.0.1:8080/ui/>，OpenAPI <http://127.0.0.1:8080/docs>。

### 三分钟走通一遍完整链路

建账号（`provider=memory` 便于本地演示；真实账号用 `imap` 并配置 `imap_host`/`secret`）：

```bash
curl -s -X POST localhost:8080/api/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"email":"support@example.com","provider":"memory"}'
```

导入知识库：

```bash
curl -s -X POST localhost:8080/api/v1/kb/documents \
  -H 'Content-Type: application/json' \
  -d '{"title":"退换货政策","content":"商品签收后 7 天内可无理由退货，运费由买家承担。"}'
```

投递一封咨询邮件（自动分类 → 生成回复草稿）：

```bash
curl -s -X POST localhost:8080/api/v1/accounts/1/ingest \
  -H 'Content-Type: application/json' \
  -d '{"raw":"From: tom@customer.com\nTo: support@example.com\nSubject: 退货咨询\nMessage-ID: <m1@customer.com>\n\n我买的东西想退货，运费谁承担？"}'
```

查看待审核草稿，然后审核通过并发送：

```bash
curl -s localhost:8080/api/v1/replies?status=pending_review
curl -s -X POST localhost:8080/api/v1/replies/1/approve \
  -H 'Content-Type: application/json' -d '{"reviewer_id":"ops"}'
```

## 管理台（`/ui/`）

React + TypeScript + Vite 构建，产物随仓库发布（无需装 node 即可运行）；9 个页面全部走真实 API：

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

### 0. 一封邮件的一生

```
① 拉取    IMAP UID SEARCH/FETCH（或 Gmail history / Graph receivedDateTime）
             └─► 原始 .eml 按 sha256 落对象存储（内容寻址，天然去重）
② 解析    MIME 拆解 → 头部解码 → 正文纯文本化 → 附件元数据 → 会话归并
             └─► mails 表（status=parsed）
③ 特征    归一化/反混淆/URL/PII + 发件人信誉 + 认证结果 → FeatureBundle
④ 过滤    白名单 → 强规则 → 朴素贝叶斯 → 模糊区 LLM 复核 → 三档动作
             └─► mail_verdicts（含命中原因）
⑤ 分类    规则 → 朴素贝叶斯 → 低置信度 LLM 兜底
             └─► category + 各类得分 + 理由
⑥ 回复闸门 RFC 3834 反回环 + 类别白名单 + 冷却 + 免打扰 + 线程深度
⑦ 检索    BM25 + 向量余弦混合召回 → 重排 → top5 知识片段
⑧ 起草    LLM（或模板）生成结构化草稿（含 citations）→ 护栏校验
⑨ 处置    自动发送 / 人工审核 / 拒绝，全程写审计
⑩ 回流    人工反馈 → 训练集 → 重训 → 影子/灰度
```

下面按步骤展开。每一步都对应 `src/mailmind/` 里的具体模块，括号内是文件位置。

---

### 1. 拉取邮件（`connectors/imap_connector.py` + `services/ingest.py`）

**IMAP 增量同步算法**：

1. `SELECT INBOX`（只读），从响应里取 `UIDVALIDITY`；
2. `uid_validity` 与库里记录不一致 → 视为服务端重建了 UID 空间，**全量重扫**（`reset=True`）；
3. 否则 `UID SEARCH UID {last_uid+1}:*`；
4. 过滤掉 `<= last_uid` 的项（`UID n:*` 在 n 超界时会回送最后一封，这是经典坑）；
5. 排序后按 `limit` 分页，`UID FETCH (UID RFC822 FLAGS INTERNALDATE)`；
6. 返回 `FetchPage(messages, uid_validity, last_uid, reset)`，由 `IngestService.sync_account` 逐封入库；
7. 全部成功/失败统计完后，更新 `accounts.last_uid / uid_validity / last_synced_at` 并提交。

**入库去重与存储**（`IngestService.ingest_raw`）：

- 超过 `max_mail_bytes`（默认 25 MB）直接拒绝，避免拖垮解析；
- 幂等键是 **`(account_id, message_id)`**：同一封邮件重复投递/重复同步只会返回 `duplicate`；
- 原始邮件按 `sha256` 命名写入对象存储（`raw/ab/<sha>.eml`），同一内容不会存两份；
- 附件只存元数据（文件名/类型/大小/sha256/是否危险）+ 对象键，不落库二进制。

Gmail 用 `historyId` 作游标（history 过期返回 404 → 同样走 `reset`）；Graph 用最新邮件的
`receivedDateTime` 时间戳作游标。三者共用同一个 `last_uid` 整型列。

---

### 2. 解析：从字节到 `ParsedMail`（`pipeline/parse.py`）

用标准库 `email`（`policy.default`）解析，失败也**不抛异常**，只记录 `parse_warnings`。

**头部**：

| 处理 | 说明 |
|---|---|
| 编码 | `decode_header` + `make_header` 处理 RFC 2047（`=?utf-8?b?...?=`）|
| From | `parseaddr`，失败时正则兜底；地址统一小写 |
| Message-ID | 缺失时用 `sha256(raw)` 合成（保证幂等键始终存在）|
| Date | `parsedate_to_datetime`，统一转成 UTC aware；非法值记录 warning |
| 认证结果 | 解析 `Authentication-Results`，取最靠接收端的 `spf/dkim/dmarc` |
| 其他 | `List-Id`、`Precedence`、`Auto-Submitted`、`Return-Path`、`Received` 跳数 |

**正文**：

1. 遍历所有 MIME part（跳过 multipart 容器）；
2. `text/plain` 逐个解码后拼接；`text/html` 单独收集；
3. 没有纯文本时才把 HTML 转文本——`html.parser` 跳过 `script/style/head`，块级标签转换行；
4. 字符集按 `part charset → utf-8 → gb18030 → big5 → latin-1` 依次尝试，全失败用 `replace` 兜底。

**附件**：`filename` 或 `Content-Disposition: attachment` 判定；计算 sha256；按扩展名标记危险
（`exe/scr/js/vbs/bat/lnk/iso/docm/xlsm` 等）并识别双扩展名（`invoice.pdf.exe`）。

**会话归并**（`pipeline/thread.py`）：取 `References[0]` → 否则 `In-Reply-To[0]` → 否则自己的
`Message-ID`，统一哈希成 `thread_id`。这样"根邮件"和它的回复天然落到同一会话，不需要回查数据库。

**归一化与特征预处理**（`pipeline/normalize.py`）：

- `NFKC` 统一全/半角、去掉零宽字符、压缩空白；
- 反混淆：`v1agra` → `viagra`（仅对含字母且含可映射字符的 token，降低误伤）；
- 抽 URL：识别 IP 直连、短链、punycode（同形字钓鱼）；
- PII 打码：手机号/身份证/银行卡/邮箱，仅用于送 LLM 前的脱敏；
- 引用/签名剥离工具（`strip_quoted`/`clean_body`）已提供，但当前流水线**不做剥离**，保留全文给模型，
  这是已知取舍（见文末"已知边界"）。

---

### 3. 特征工程（`pipeline/features.py`）

所有判定共享同一个 `FeatureBundle`，保证规则、模型、LLM 看到的是同一份事实：

| 组别 | 典型字段 |
|---|---|
| 身份/头部 | `from_domain`、`reply_to_mismatch`、`return_path_mismatch`、`message_id_domain_mismatch`、`received_hops`、`date_in_future` |
| 认证 | `spf/dkim/dmarc` 结果、`auth_failures` 计数 |
| 发件人信誉 | 历史命中数 `sender_seen`、垃圾占比 `sender_spam_ratio`、首次出现距今天数 |
| 内容 | 长度、大写比例、感叹号/货币符号密度、诱导词命中数、纯图片邮件 |
| URL | 数量、域名集合、IP 直连数、短链数、punycode 数 |
| 附件 | 数量、危险文件列表 |
| 会话 | 是否回复、引用层数、是否群发（`List-Id`/`Precedence`）、收件人数 |

发件人信誉由 `ProcessingService._sender_stats` 现算：排除当前这封，统计同账号同发件人的历史邮件数与
其中被判 `spam` 的比例。

---

### 4. 垃圾邮件过滤：级联 + 三档动作（`ml/spam.py`）

```
规则命中白名单 ──────────────────────────────► ham（score 0.01）
规则命中黑名单/认证失败/信誉差/主题正则 ─────► spam（score 0.99，直接隔离）
        │
        └─► L1：朴素贝叶斯 p(spam) 与启发式分数取 max
                 │
                 ├─ 关键词规则命中：分数下限 0.85
                 └─ 0.20 ≤ score ≤ 0.80（模糊区）：调 LLM 复核，0.5×模型分 + 0.5×LLM 概率
                         │
                         ▼
                  score ≥ 0.95 → quarantine（隔离，可找回）
                  0.70 ≤ score < 0.95 → tag（打标，照常投递）
                  score < 0.70 → pass
```

**启发式打分**（没有模型时也能用，权重刻意保守）：

| 信号 | 加分 |
|---|---|
| 诱导词 ≥2 / =1 | +0.22 / +0.08 |
| IP 直连链接 | +0.25 |
| 短链 / punycode | +0.12 / +0.15 |
| 危险附件 | +0.28 |
| 伪造显示名 / Reply-To 不一致 | +0.15 / +0.12 |
| 认证失败 ≥2 / =1 | +0.30 / +0.15 |
| 无 Received 头 / 日期在未来 | +0.10 / +0.15 |
| 大段全大写 / 纯图片且极短 | +0.10 / +0.12 |
| **回复线程** / 老联系人（垃圾率<5%） | **−0.25 / −0.20** |

**为什么是三档而不是二分类**：漏一封垃圾用户几乎无感，误杀一封客户合同是事故。`tag` 档让"可疑"的邮件
仍然送达，只是打上标记；`quarantine` 档的邮件用户随时可以在隔离区找回。

**可解释**：每条判定都落 `spam_reasons`，形如：

```json
{
  "spam_score": 0.97,
  "spam_action": "quarantine",
  "reasons": [
    {"type": "rule", "kind": "blocklist", "desc": "发件域在黑名单", "detail": {"domain": "bulk-spam.cn"}},
    {"type": "model", "model": "spam-nb-v1", "top_tokens": ["中奖", "领取", "限时"]}
  ]
}
```

`phishing` 标签在"隔离 + 命中 IP/punycode/认证失败/可疑显示名"时给出，便于运营区分钓鱼与营销。

---

### 5. 自动分类（`ml/classify.py`）

默认类别：`consult`（咨询）、`aftersale`（售后）、`booking`（预约）、`billing`（账单财务）、
`notice`（通知公告）、`marketing`（营销推广）、`social`（社交）、`internal`（内部）、
`recruiting`（招聘）、`complaint`（投诉）、`spam`（垃圾）、`other`。

三层判定：

1. **规则优先**：库里 `kind=category` 的规则（关键词 → 类别）命中即定类，覆盖发件域、账单号、`List-Id` 这类强特征；
2. **朴素贝叶斯**：字 unigram + bigram 的 TF 加权多项式 NB，输出各类概率；最高分 ≥ 0.60 直接采用；
3. **LLM 兜底**：置信度不足或类别为 `other` 时，带类别定义做 few-shot 分类，只有返回合法类别且置信度 ≥ 0.5 才采用。

已被判为垃圾的邮件不再做业务分类，直接记 `spam`（避免"营销垃圾被分到 consult 然后自动回复"）。

判定结果落 `mail_verdicts.category / category_scores / category_reason`，管理台能看到各类得分。
类别决定后续动作：只有白名单类别（默认 `consult/aftersale/booking`）才会进入自动回复流程。

---

### 6. 回复策略：放行闸门（`reply/policy.py`）

按顺序检查，**任一不满足就跳过并记录原因码**：

| 顺序 | 检查 | 不通过原因码 |
|---|---|---|
| 1 | 全局开关 `auto_reply_enabled` | `disabled` |
| 2 | 不是垃圾邮件 | `spam` |
| 3 | 类别在 `auto_reply_categories` 白名单 | `category_not_allowed` |
| 4 | 对方不是自动回复（`Auto-Submitted` 非 `no`） | `auto_submitted` |
| 5 | 不是群发/邮件列表（`Precedence`、`List-Id`、`List-Unsubscribe`） | `bulk_or_list` |
| 6 | 不是退信（`Return-Path: <>`、mailer-daemon/postmaster） | `bounce` |
| 7 | 发件人本地部分不是 no-reply/noreply/donotreply 等 | `noreply_address` |
| 8 | 会话深度 ≤ 3（引用链长度） | `thread_too_deep` |
| 9 | 没有危险附件 | `risky_attachment` |
| 10 | 不在免打扰时段 | `quiet_hours` |
| 11 | 同一发件人 24h 内没被自动回复过（Redis/内存冷却） | `rate_limited` |

设计要点：**检查是只读的，冷却名额只在真正发送成功后才占用**，避免"检查通过但护栏拒绝"白白吃掉额度。

---

### 7. 知识库检索（`reply/retrieval.py` + `services/kb.py`）

**入库**：文档按空行切段，超过 512 字的段落按窗口滑动（重叠 80 字），每个片段单独存一行
`kb_documents`，并预计算向量。

**召回（混合检索）**：

```
query = 主题 + 正文（截断 1200 字）
├─ BM25：中文字 unigram+bigram 分词，k1=1.5, b=0.75 → 归一化到 0..1
└─ 向量：确定性 hash 签名投影（256 维），余弦相似度
混合分 = 0.5 × BM25_norm + 0.5 × cosine
```

取 top-20，再按"查询词覆盖率 0.3 + 混合分 0.7"重排，保留 top-5；低于 `retrieval_min_score`（0.15）的丢弃。

**为什么用 hash 向量而不是 BGE-M3**：离线可跑、零依赖、结果确定，便于测试复现。接口按
`Embedder` 协议定义，换成 BGE-M3 只需替换一个类（见 `exp.md` 附录 C）。

---

### 8. LLM 起草 + 护栏（`reply/generator.py` + `ml/llm.py` + `ml/guardrails.py`）

**模型选择**：`MAILMIND_LLM_PROVIDER=template` 时用本地模板（从检索到的片段拼回复，不联网、可复现）；
`openai` 时走 OpenAI 兼容的 `/chat/completions`（默认 DeepSeek `deepseek-chat`），失败自动降级回模板。

**Prompt 结构**：

```
system: 你是企业客服…只能使用【知识片段】中的事实；不确定时 need_human=true；
        不承诺价格/折扣/交付时间；语言跟随来信
user:   【知识片段】
        [1] 退换货政策
        商品签收后 7 天内可无理由退货…
        【来信】
        主题：退货咨询
        正文：我买的东西想退货，运费谁承担？
```

要求模型返回 JSON：`intent / subject / body / confidence / citations / need_human`。

**护栏**（任一硬规则不过就拒绝，软问题转人工）：

| 检查 | 级别 | 说明 |
|---|---|---|
| 正文为空 / 少于 20 字 | 拒绝 | `empty_body` / `too_short` |
| 没有引用 / 引用不在召回结果里 | 拒绝 | `no_citation` / `invalid_citation` |
| 回复里出现身份证/银行卡/手机号 | 拒绝 | `pii_leak:*` |
| 出现价格承诺、折扣、赔偿、合同、保证 | 转人工 | `sensitive_commitment` |
| 来信里含提示注入（"忽略以上指令"等） | 转人工 | `prompt_injection` |
| 超过 2000 字 / 模型自报 need_human | 转人工 | `too_long` / `model_flag` |

**置信度与状态**：`confidence = min(模型自评, 0.5 + 0.5×top1检索分)`。然后：

- 护栏拒绝 → `rejected`（不生成待审草稿）
- 置信度 < 0.60 → `rejected`
- `MAILMIND_AUTO_REPLY_SEND_MODE=review`（默认）→ `pending_review`
- `auto` 且置信度 ≥ 0.85 → 直接发送；否则 `pending_review`

---

### 9. 发送与审计（`reply/sender.py`）

- 组装 MIME：`In-Reply-To: <原 Message-ID>`、`References: 原引用链 + 原 Message-ID`，
  并强制带 `Auto-Submitted: auto-replied`（RFC 3834，防止两个机器人互回）；
- 发送通道按账号选择：账号配了 SMTP → SMTP；`provider=gmail` → Gmail API；否则用注入的发送器（测试/演示）；
- 成功：草稿 `status=sent`、邮件 `status=replied`、标记冷却、写审计（含 `provider_message_id`）；
- 失败：草稿 `status=failed`、写审计，不占用冷却名额（可以人工重试）；
- 人工审核走 `approve`：可改正文（记录 `edited_diff` 供评估"草稿可用率"）后再发。

---

### 10. 状态机、幂等与回放

邮件主状态：`fetched → parsed → classified / quarantined → pending_review → replied`，
失败进 `failed`，软删除进 `deleted`。

- **幂等**：`(account_id, message_id)` 唯一约束 + 内容寻址存储；
- **可回放**：原始 EML 永远可读，`tasks.run_process_mail` 可对单封邮件重跑"过滤 + 分类 + 起草"；
  模型升级后可批量重处理历史邮件；
- **可重训**：人工反馈写入 `feedback`（用户反馈权重 ×3），`mailmind train` 或
  `POST /api/v1/admin/retrain` 重建模型并热替换。

---

### 11. 关键参数速查

| 参数 | 默认 | 含义 |
|---|---|---|
| `spam_pass_threshold` | 0.70 | ≥ 该值打标 |
| `spam_quarantine_threshold` | 0.95 | ≥ 该值隔离 |
| `spam_review_low/high` | 0.20 / 0.80 | 落在此区间才调 LLM 复核 |
| `classifier_review_threshold` | 0.60 | 分类置信度低于此走 LLM |
| `auto_reply_categories` | consult/aftersale/booking | 允许自动回复的类别 |
| `auto_reply_min_confidence` | 0.85 | auto 模式直接发送门槛 |
| `auto_reply_review_min_confidence` | 0.60 | 低于此直接拒绝 |
| `auto_reply_cooldown_hours` | 24 | 同一发件人冷却 |
| `auto_reply_max_thread_depth` | 3 | 会话深度上限 |
| `retrieval_top_k / rerank_k` | 20 / 5 | 召回与重排数量 |
| `retrieval_min_score` | 0.15 | 片段最低相关度 |

## REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查（公开） |
| POST/GET/PATCH/DELETE | `/api/v1/accounts` `/api/v1/accounts/{id}` | 账号管理（PATCH 用于更新凭据/暂停） |
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
| `MAILMIND_SECRET_KEY` | `mailmind-dev-insecure-key` | 邮箱凭据加密密钥；生产必须换随机值，**建账号后不可再变** |
| `MAILMIND_SPAM_PASS_THRESHOLD` | 0.70 | ≥ 该值打标 |
| `MAILMIND_SPAM_QUARANTINE_THRESHOLD` | 0.95 | ≥ 该值隔离 |
| `MAILMIND_AUTO_REPLY_SEND_MODE` | `review` | `review` 人工审核 / `auto` 高置信自动发送 |
| `MAILMIND_AUTO_REPLY_COOLDOWN_HOURS` | 24 | 同一发件人冷却期 |
| `MAILMIND_QUIET_HOURS_START/END` | 空 | 免打扰时段，如 `22:00` / `08:00` |
| `MAILMIND_LLM_PROVIDER` | `template` | `template` 离线确定性 / `openai` 兼容 DeepSeek、Qwen、vLLM、Ollama |
| `MAILMIND_LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | DeepSeek 默认 | 换供应商只改这三个；`mailmind llm-check` 可自检 |
| `MAILMIND_LLM_MAX_RETRIES` | 1 | 调用失败重试次数，最终失败自动降级 template |
| `MAILMIND_LLM_JSON_MODE` | false | 服务支持 `response_format=json_object` 时打开 |
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
└── static/      前端构建产物（由 web/ 生成）
web/             React 19 + TS + Vite 源码（api-paths.json 为接口清单）
migrations/      Alembic 迁移（alembic.ini 在仓库根目录）
tests/           仅本地保留（不推送）
```

## 测试

```bash
make test
make lint
```

测试覆盖：解析/MIME/编码、归一化与 PII、特征、规则引擎、朴素贝叶斯、级联判定、分类、
护栏、检索、放行策略（RFC 3834）、生成、发送、接入幂等与 UIDVALIDITY、API 全量、
IMAP/SMTP/Gmail/Graph 协议解析（假 client 与 MockTransport）、任务函数、对象存储（含 S3 Stubber）、
凭据加密、Redis 冷却与 API 限流、游标分页、Alembic 迁移一致性、PostgreSQL DDL 兼容性、管理台静态契约
（构建产物可访问性、**前端接口清单 ↔ OpenAPI 路径一致性**），以及一个
**召回率/误杀率验收测试**（`tests/test_quality.py`）。

真实 PG 端到端用例默认跳过，配置后启用：

```bash
MAILMIND_TEST_PG_URL=postgresql+psycopg://user:pass@localhost:5432/mailmind_test make test
```

## 部署

```bash
docker compose up --build
```

启动后：API <http://localhost:8080>，管理台 <http://localhost:8080/ui/>。

生产清单：PostgreSQL（pgvector 镜像已就绪）、Redis（Celery broker）、域名 SPF/DKIM/DMARC、
`MAILMIND_API_KEY` 与 `MAILMIND_SECRET_KEY`、备份策略、告警（队列积压/同步延迟/误杀突增）。

## 已知边界

- 未做多租户行级权限（单实例单组织），接入多租户需在 `Account` 上加 `tenant_id` 并加全局过滤。
- 检索为 BM25 + 哈希向量混合（万级知识库足够），更大规模应换 pgvector/BGE-M3 + 重排模型。
- 自动回复默认不会真正"自动发出去"：`MAILMIND_AUTO_REPLY_SEND_MODE=review` 时必须人工点通过。
- 更多偏差与踩坑记录见 [exp.md 附录 C](exp.md)。
