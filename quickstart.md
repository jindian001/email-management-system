# MailMind 快速上手

智能邮箱管理系统：**垃圾过滤 + 自动分类 + 自动回复**。后端 FastAPI，管理台 React + Vite。
完整设计与实现说明见 [exp.md](exp.md)，工程与接口清单见 [README.md](README.md)。

> ⚠️ 命令块里不放行内注释。macOS 默认的 **zsh 未开启 `interactive_comments`**，
> 粘贴 `mailmind llm-check   # 说明` 这种带注释的命令会把 `# 说明` 当成参数，
> 报 `unrecognized arguments: # ...`。只复制命令本身，或先执行 `setopt interactive_comments`。

---

## 1. 三条命令跑起来

```bash
cd ~/Documents/助手
make install
make demo
make serve
```

- `make install`：建 `.venv` 并安装依赖（可重复执行）
- `make demo`：演示账号 + 知识库 + 3 封样例邮件（可重复执行，不会重复入库）
- `make serve`：默认 8080

打开 <http://127.0.0.1:8080/ui/>，`/docs` 是 OpenAPI 在线调试。

> 不想激活虚拟环境时，等价命令是 `PYTHONPATH=src .venv/bin/python -m mailmind.cli demo`。

演示数据会呈现三种典型结果：

| 样例 | 结果 |
|---|---|
| 顾客问退货 | 分类 `consult` → 自动生成回复草稿（待审核）|
| 中奖 + IP 链接 | 判 `phishing` → 进隔离区，不回复 |
| 9 月对账单 | 分类 `billing` → 归档，不自动回复 |

## 2. 管理台（9 个页面）

| 页面 | 用来做什么 |
|---|---|
| 总览 | 邮件量、垃圾率、待审/隔离数、分类与判定分布 |
| 收件箱 | 搜索、状态/类别过滤、游标翻页、一键 AI 起草 |
| 邮件详情 | 正文、附件、**判定分数与命中原因**、草稿、同会话、下载原始 EML |
| 隔离区 | 放行（自动加白名单）、删除 |
| 自动回复审核 | 改草稿 → 通过发送 / 拒绝 |
| 账号 | 新建 IMAP/Gmail/Graph 账号、同步、删除 |
| 规则 | 增删启停 + **规则试算**（输入一封邮件看判定与命中规则） |
| 知识库 | 导入（自动切片）、检索测试、删除 |
| 审计 / 反馈 | 审计动作追溯、反馈样本、一键重训 |

右上角输入 `X-API-Key`（仅当后端配置了 `MAILMIND_API_KEY` 时需要），会存在浏览器 localStorage。

## 3. 接自己的邮箱

```bash
curl -s -X POST localhost:8080/api/v1/accounts \
  -H 'Content-Type: application/json' -d '{
    "email": "me@company.com",
    "provider": "imap",
    "config": {
      "imap_host": "imap.company.com", "imap_port": 993, "use_ssl": true,
      "smtp_host": "smtp.company.com", "smtp_port": 587, "smtp_tls": true
    },
    "secret": "邮箱应用专用密码（不是登录密码）"
  }'
```

同步一次：

```bash
curl -s -X POST localhost:8080/api/v1/accounts/1/sync
```

- `secret` 用 `MAILMIND_SECRET_KEY` 派生的密钥加密存储，**建账号后不要再改这个值**。
- Gmail：`provider=gmail`，`secret` 填 OAuth access token；Graph 同理（发信走 SMTP）。
- 同步是增量的（IMAP 用 UIDVALIDITY/UID，Gmail 用 historyId，Graph 用 receivedDateTime），重复执行不会产生重复邮件。

## 4. 打开自动发送（可选）

```bash
export MAILMIND_AUTO_REPLY_SEND_MODE=auto
export MAILMIND_AUTO_REPLY_MIN_CONFIDENCE=0.85
```

第一行默认是 `review`（只起草、人工点通过）；第二行是自动发送所需的最低置信度。

即使开了 `auto`，以下情况仍强制转人工：SPF/DKIM 失败、类别不在白名单、对方是自动回复/退信/邮件列表、
24h 内已回过、线程深度 >3、免打扰时段、无知识库引用、含价格承诺或个人信息。

## 5. 接入真实 LLM（可选）

默认 `MAILMIND_LLM_PROVIDER=template`：**不调用任何模型**，用检索到的知识片段拼回复（离线、可复现）。
要换成真实模型，走 OpenAI 兼容协议即可：

```bash
export MAILMIND_LLM_PROVIDER=openai
export MAILMIND_LLM_BASE_URL=https://api.deepseek.com/v1
export MAILMIND_LLM_MODEL=deepseek-chat
export MAILMIND_LLM_API_KEY=sk-xxx
```

上面 `BASE_URL` 与 `MODEL` 默认就是 DeepSeek；换成别的服务只改这两项（见下表）。

自检（关键一步，发一条最小请求，不成功就不用往下走）：

```bash
mailmind llm-check
```

期望输出（`ok: true` 即接入成功）：

```json
{
  "ok": true,
  "gateway": "openai:deepseek-chat+fallback",
  "elapsed_ms": 820.5,
  "intent": "consult",
  "citations": [1],
  "body_preview": "您好，商品签收后 7 天内可无理由退货……",
  "fallback_error": ""
}
```

改完重启 `make serve`。之后在管理台「自动回复审核」里，草稿的 `model` 字段会显示 `openai:deepseek-chat`；
仍是 `template` 说明没生效（见文末排错）。

常用组合（`base_url` + `model` 两者要匹配服务端实际模型名）：

| 服务 | `MAILMIND_LLM_BASE_URL` | `MAILMIND_LLM_MODEL` |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 本地 vLLM | `http://127.0.0.1:8000/v1` | `qwen2.5-7b-instruct` |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5:7b` |

两个可选参数：

```bash
export MAILMIND_LLM_MAX_RETRIES=1
export MAILMIND_LLM_JSON_MODE=true
```

前者是失败重试次数（默认 1）；后者在服务支持 `response_format=json_object` 时打开，输出更稳。
模型调用失败（超时/4xx/5xx/返回非 JSON）会自动降级到 template；4xx 不重试、5xx 与 429 会重试，不会中断收信与回复链路；
降级原因会出现在 `llm-check` 的 `fallback_error` 和日志 `llm_fallback` 里。

## 6. 常用命令

```bash
mailmind demo
mailmind serve --port 8090
mailmind train
mailmind llm-check
mailmind ingest --account-id 1 --file invoice.eml
mailmind sync --account-id 1 --limit 200
```

依次是：演示数据、换端口启动、用反馈重训、验证 LLM、导入一封 .eml、同步 IMAP 账号。

## 7. 前端开发 / 重新构建

仓库已包含构建产物（`src/mailmind/static/`），直接 `make serve` 即可。改前端后：

```bash
make web
```

热更新开发（`/api` 代理到 8080）：

```bash
cd web
pnpm dev
```

访问 <http://127.0.0.1:5173/ui/>。接口路径统一登记在 `web/src/api-paths.json`，新增接口时先加清单，
测试会校验它是否存在于 OpenAPI。

## 8. 测试

```bash
make test
make lint
```

当前基线：**310 passed, 1 skipped**。跳过的是需要真实 PostgreSQL 的用例，配置后可开启：

```bash
MAILMIND_TEST_PG_URL=postgresql+psycopg://user:pass@localhost:5432/mailmind_test make test
```

## 9. Docker 部署

```bash
docker compose up --build
```

前端多阶段构建 + API + PostgreSQL + Redis + worker，启动前自动执行数据库迁移。

## 10. 数据与重置

| 路径 | 内容 |
|---|---|
| `var/mailmind.db` | SQLite（生产改 `MAILMIND_DATABASE_URL` 指向 PG） |
| `var/raw/` | 原始 .eml（按 sha256 存放，可重放） |
| `var/models/` | `spam_model.json` / `category_model.json` |

重置：`rm -rf var && make demo`。

## 11. 常见问题

| 现象 | 处理 |
|---|---|
| `mailmind: command not found` | `source .venv/bin/activate`，或用 `make` |
| `unrecognized arguments: # ...` / `command not found: #` | 命令带了行内注释，只复制 `#` 之前的部分；或先 `setopt interactive_comments` |
| 配了 LLM 但仍显示 `template` | 没设 `MAILMIND_LLM_API_KEY`，或 `PROVIDER` 不是 `openai`；先跑 `mailmind llm-check` |
| `llm-check` 报 400 | 服务端拒绝了请求，**看 `fallback_error` 里的响应体**：`Model Not Exist` 是模型名错；`base_url` 与供应商不匹配；或 JSON mode 不被支持 |
| `llm-check` 报 401 | API Key 错误/过期，或该服务需要额外的鉴权头 |
| `llm-check` 报 timeout / connection | `BASE_URL` 写错、本地模型没起、或需要代理 |
| 报 `model not found` | `MAILMIND_LLM_MODEL` 与服务端实际模型名不一致（Ollama 要带 tag，如 `qwen2.5:7b`） |
| 接口 401 | 配了 `MAILMIND_API_KEY`，请求带 `X-API-Key`（管理台右上角填写）|
| `/ui` 打不开 | 必须访问 `/ui/`（带尾斜杠）；没构建就先 `make web` |
| sync 返回 400 | `provider=memory` 需要注入连接器；imap 账号要填 `config.imap_host` |
| 回复没自动发 | 默认 `review` 模式，去「自动回复审核」点通过；或命中冷却/免打扰 |
| 改了 `MAILMIND_SECRET_KEY` 后收不到信 | 旧凭据解不开，需重建账号或恢复原密钥 |
