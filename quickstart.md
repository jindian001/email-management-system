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
| 账号 | 新建 IMAP/Gmail/Graph 账号、同步、改凭据、暂停/启用、删除 |
| 规则 | 增删启停 + **规则试算**（输入一封邮件看判定与命中规则） |
| 知识库 | 导入（自动切片）、检索测试、删除 |
| 审计 / 反馈 | 审计动作追溯、反馈样本、一键重训 |

右上角输入 `X-API-Key`（仅当后端配置了 `MAILMIND_API_KEY` 时需要），会存在浏览器 localStorage。

### 3.0 先拿到"应用专用密码"

MailMind 不生成这个密码，它是**邮箱服务商**发给你的"客户端专用密码/授权码"，用来替代主密码登录 IMAP/SMTP。
各家入口：

| 邮箱 | 生成位置 | 备注 |
|---|---|---|
| QQ 邮箱 | 设置 → 账号 → POP3/IMAP/SMTP 服务 → 生成授权码 | 16 位，需要短信验证 |
| 163 / 126 | 设置 → POP3/SMTP/IMAP → 开启服务 → 新增授权密码 | |
| Gmail | 先开两步验证 → Google 账号 → 安全性 → 应用专用密码 | 16 位 |
| Outlook / M365 | 安全性 → 高级安全选项 → 应用密码 | 需先开两步验证 |
| iCloud | Apple ID → 登录与安全 → App 专用密码 | |
| 企业邮箱 | 邮箱设置里的"客户端专用密码"，或找 IT | Exchange 可能只支持 OAuth |

Gmail 有两个前提：必须先开启**两步验证**（否则没有"应用专用密码"入口）；Workspace（公司/学校）账号
如果被管理员关闭了 App passwords，就只能改用 OAuth。生成后旧的不会自动失效，需要回同一页面手动删掉旧条目。

如果之前在 **Mac 的「邮件」App** 里配过这个邮箱，可以从钥匙串找回：

```
打开「钥匙串访问」→ 搜索邮箱地址 → 双击条目 → 勾选"显示密码"→ 输入 Mac 登录密码
```

拿到后先用系统自带工具验证一次，能登录再用到 MailMind：

```bash
python3 - <<'PY'
import imaplib
m = imaplib.IMAP4_SSL("imap.qq.com", 993)
print(m.login("you@qq.com", "你的授权码"))
print(m.list())
PY
```

把 host 换成你自己的 IMAP 地址。返回 `('OK', ...)` 就说明密码可用。

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
- 生产上先生成随机密钥再建账号：`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`，
  写进 `.env` 或环境变量，并妥善备份；换了它旧账号的密码就解不开（日志会打 `credential_decrypt_failed`）。
- Gmail：`provider=gmail`，`secret` 填 OAuth access token；Graph 同理（发信走 SMTP）。
- 同步是增量的（IMAP 用 UIDVALIDITY/UID，Gmail 用 historyId，Graph 用 receivedDateTime），重复执行不会产生重复邮件。

### 3.1 接入后要做的 7 件事

**① 把历史邮件分批拉完**

同步接口默认一次 100 封。历史邮件多时重复执行，直到 `fetched` 降为 0：

```bash
curl -s -X POST "localhost:8080/api/v1/accounts/1/sync?limit=500"
```

游标保存在 `accounts.last_uid`，不用手工维护；重复拉取按 `Message-ID` 幂等，不会重复入库。

**② 先看隔离区，处理误杀**

```bash
curl -s localhost:8080/api/v1/quarantine
```

放行会自动把发件域写进白名单：

```bash
curl -s -X POST "localhost:8080/api/v1/quarantine/12/release?add_allowlist=true"
```

重要客户建议提前加白，不要等误杀了再救：

```bash
curl -s -X POST localhost:8080/api/v1/rules \
  -H 'Content-Type: application/json' \
  -d '{"kind":"allowlist","action":"ham","payload":{"domains":["customer.com","partner.cn"]},"priority":1,"description":"重要客户与供应商"}'
```

**③ 建知识库，否则不会起草**

生成回复要求"有依据"（引用必须命中知识片段）。知识库为空时草稿会被护栏拒绝（`no_citation`），
所以先导入 5–10 条 FAQ：

```bash
curl -s -X POST localhost:8080/api/v1/kb/documents \
  -H 'Content-Type: application/json' \
  -d '{"title":"退换货政策","content":"商品签收后 7 天内可无理由退货，运费由买家承担。","source":"faq"}'
```

用检索确认能召回：

```bash
curl -s "localhost:8080/api/v1/kb/search?q=退货 运费&top_k=3"
```

**④ 先 review，再 auto**

默认 `review`：只起草、人工点通过。观察 1–2 周草稿质量后再打开自动发送：

```bash
export MAILMIND_AUTO_REPLY_SEND_MODE=auto
export MAILMIND_AUTO_REPLY_MIN_CONFIDENCE=0.85
```

能自动回复的类别默认 `consult` / `aftersale` / `booking`，用 `MAILMIND_AUTO_REPLY_CATEGORIES` 调整。

**⑤ 配好自己的发信信誉**

回复能不能送达取决于你域名的 SPF / DKIM / DMARC、PTR 与出口 IP 一致性。这一步不在代码里，
但不做的话自动回复大概率进对方垃圾箱。程序侧已内置 `Auto-Submitted: auto-replied` 防回环。

**⑥ 用"规则试算"校准阈值**

```bash
curl -s -X POST localhost:8080/api/v1/rules/test \
  -H 'Content-Type: application/json' \
  -d '{"from_addr":"promo@example.com","subject":"限时优惠","body":"点击 http://1.2.3.4/x 领取"}'
```

返回 spam 分数/动作、命中规则与特征快照。误杀多就调高 `MAILMIND_SPAM_PASS_THRESHOLD` 或加白；
漏杀多就补关键词/黑名单。

**⑦ 日常闭环**

- 每天看：总览 → 隔离区 → 自动回复审核
- 有误判：点"是垃圾/非垃圾"，再到「反馈」页点"立即重训"（等价于 `mailmind train`）
- 排查：审计页按动作过滤，带 trace_id
- 看指标：垃圾率、草稿采纳率、隔离放行率

### 3.2 接入后常见的特殊情况

| 情况 | 怎么处理 |
|---|---|
| 换了邮箱密码，或 Gmail/Graph 的 token 过期 | 管理台账号页点「改凭据」，或 `curl -X PATCH localhost:8080/api/v1/accounts/1 -H 'Content-Type: application/json' -d '{"secret":"新密码"}'`；不用删账号 |
| 想临时停止同步 | 账号页点「暂停」，或 PATCH `{"status":"paused"}` |
| 历史邮件太多 | 分批 sync（`limit=500` 重复调用）；单封上限 25 MB，超大邮件会跳过 |
| 只同步了收件箱 | 每个账号一个 `config.folder`；要同步已发送/垃圾箱就另建账号指向该文件夹 |
| 担心自己回给自己形成回环 | 已按 RFC 3834 拦截 Auto-Submitted / Precedence / List-Id / 退信 / no-reply，并限制 24h 冷却与线程深度 |
| 同一封邮件重复到达 | 按 `Message-ID` 幂等，不会重复入库 |
| 回复没发出去 | 默认 review；或命中冷却/免打扰；或草稿被护栏拒绝（看邮件详情里的 `risk_flags`） |
| 想换 `MAILMIND_SECRET_KEY` | 换后旧凭据解不开（日志 `credential_decrypt_failed`），需恢复旧 key 或用新 key 重录密码 |

### 3.3 开启接口鉴权（可选）

`MAILMIND_API_KEY` 是**接口层的共享密钥**（请求头 `X-API-Key`），与邮箱密码、LLM Key 都不是一回事。
留空 = 不校验（仅适合本机开发）；只要服务对局域网/公网开放就应该设置。

生成一个随机 key：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

写进 `.env`（或 export 环境变量）：

```
MAILMIND_API_KEY=刚才生成的那串
```

重启服务后验证：

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:8080/api/v1/mails
curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: 你的key" localhost:8080/api/v1/mails
```

第一条应返回 `401`，第二条 `200`。管理台右上角填入同一个 key 后按回车或点「保存」，之后所有请求会自动带
（保存在浏览器 localStorage）。没填时页面顶部会出现黄色提示条「该服务已启用接口鉴权」。

不确定服务端到底有没有开启鉴权，直接看健康检查：

```bash
curl -s localhost:8080/api/v1/health
```

返回里的 `"auth": "enabled"` 或 `"disabled"` 就是当前真实状态（key 只在进程启动时读取，改了必须重启）。

它保护的是"能读能写"的所有业务接口：邮件列表/正文、发送回复、放行隔离、改规则、重训、删账号。
不需要 key 的只有 `/api/v1/health`、`/ui/**` 静态资源和 OpenAPI 文档。

注意它不是"邮箱密码加密密钥"（那是 `MAILMIND_SECRET_KEY`），也不是"大模型 Key"（`MAILMIND_LLM_API_KEY`）。

需要注意：

- 目前是**单个共享 key**，没有角色/权限区分，审计里的操作者来自请求体（如 `reviewer_id`），不是 key 身份。
- 轮换 = 改环境变量 + 重启，所有客户端（管理台、脚本）同步换新 key。
- 启用前请确保走 HTTPS（反向代理终止即可），否则 key 明文传输。
- 不需要 key 的路径：`/api/v1/health`（探针）、`/ui/**`（静态资源）、`/docs` 与 `/openapi.json`
  （不想暴露接口结构就在反代里拦掉后两个）。

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

更新账号凭据（token 过期、改密码时用）：

```bash
curl -s -X PATCH localhost:8080/api/v1/accounts/1 \
  -H 'Content-Type: application/json' \
  -d '{"secret":"新的应用专用密码"}'
```

依次是：演示数据、换端口启动、用反馈重训、验证 LLM、导入一封 .eml、同步 IMAP 账号。

### 6.1 查看配置

```bash
mailmind config
mailmind config --json
```

输出当前**生效**的配置，密钥只显示前 4 位（便于核对是不是同一个，又不至于泄漏）。

配置来源优先级从高到低：

| 来源 | 位置 |
|---|---|
| 环境变量 | `MAILMIND_*`，只在启动服务的那个 shell 生效 |
| `.env` 文件 | 项目根目录（`~/Documents/助手/.env`），不存在就用默认值 |
| 代码默认值 | `src/mailmind/core/config.py`（也是完整的配置项清单） |

模板和示例值看 `.env.example`；Docker 部署时容器内的变量看 `docker-compose.yml` 的 `environment` 段，
`docker compose config` 可以展开渲染后的最终值。

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

当前基线：**320 passed, 1 skipped**。跳过的是需要真实 PostgreSQL 的用例，配置后可开启：

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
| 忘了应用专用密码 | 去邮箱服务商后台重新生成（见 3.0），或从 macOS 钥匙串找回；MailMind 里可用「改凭据」更新 |
| `unrecognized arguments: # ...` / `command not found: #` | 命令带了行内注释，只复制 `#` 之前的部分；或先 `setopt interactive_comments` |
| 配了 LLM 但仍显示 `template` | 没设 `MAILMIND_LLM_API_KEY`，或 `PROVIDER` 不是 `openai`；先跑 `mailmind llm-check` |
| `llm-check` 报 400 | 服务端拒绝了请求，**看 `fallback_error` 里的响应体**：`Model Not Exist` 是模型名错；`base_url` 与供应商不匹配；或 JSON mode 不被支持 |
| `llm-check` 报 401 | API Key 错误/过期，或该服务需要额外的鉴权头 |
| `llm-check` 报 timeout / connection | `BASE_URL` 写错、本地模型没起、或需要代理 |
| 报 `model not found` | `MAILMIND_LLM_MODEL` 与服务端实际模型名不一致（Ollama 要带 tag，如 `qwen2.5:7b`） |
| `curl` 返回 `000` | 不是 HTTP 码，是**连不上**：服务没起、端口不对或被杀掉了。先 `lsof -i :8080` 看监听，再 `make serve` |
| 接口 401 | 配了 `MAILMIND_API_KEY`，请求要带 `X-API-Key`（管理台右上角填写），见 3.3 |
| 管理台一直提示加载失败 401 | 后端开了鉴权但页面没填 key；在顶部黄色提示条或右上角输入框填入后回车即可 |
| `/ui` 打不开 | 必须访问 `/ui/`（带尾斜杠）；没构建就先 `make web` |
| sync 返回 400 | `provider=memory` 需要注入连接器；imap 账号要填 `config.imap_host` |
| 回复没自动发 | 默认 `review` 模式，去「自动回复审核」点通过；或命中冷却/免打扰 |
| 改了 `MAILMIND_SECRET_KEY` 后收不到信 | 旧凭据解不开，需重建账号或恢复原密钥 |
| 账号/邮件突然不见了 | `var/` 是数据目录，被删/被清空就会回到初始状态；确认没人执行过 `rm -rf var`，必要时从备份恢复 |
