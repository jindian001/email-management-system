"use strict";

/* ------------------------------------------------------------------ 状态 */

const state = {
  tab: "overview",
  auditAction: "",
  inbox: { q: "", status: "", category: "", size: 20, cursor: null, stack: [], page: 1 },
};

const CATEGORIES = [
  "consult", "billing", "notice", "marketing", "social",
  "internal", "recruiting", "complaint", "spam", "other",
];
const STATUSES = [
  ["", "全部状态"], ["quarantined", "隔离中"], ["classified", "已分类"],
  ["pending_review", "待审核"], ["replied", "已回复"], ["deleted", "已删除"],
];

/* ------------------------------------------------------------------ 工具 */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmt = (iso) => {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN", { hour12: false });
};

const pct = (v) => `${Math.round((Number(v) || 0) * 100)}%`;

function apiKey() { return localStorage.getItem("mailmind-key") || ""; }

function authHeaders(extra = {}) {
  const headers = Object.assign({}, extra);
  const key = apiKey();
  if (key) headers["X-API-Key"] = key;
  return headers;
}

async function api(path, options = {}) {
  const opts = Object.assign({}, options);
  opts.headers = authHeaders(Object.assign({}, options.headers || {}));
  if (opts.body && typeof opts.body !== "string") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
    throw new Error(`${res.status} ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return res.json();
}

function toast(message, type = "") {
  const box = document.createElement("div");
  box.className = type;
  box.textContent = message;
  $("#toast").appendChild(box);
  setTimeout(() => box.remove(), 4200);
}

function modal(title, bodyHtml) {
  const root = $("#modal-root");
  root.innerHTML = `
    <div class="overlay">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h3>${esc(title)}</h3>
          <button class="modal-close" aria-label="关闭">×</button>
        </div>
        <div class="modal-body">${bodyHtml}</div>
      </div>
    </div>`;
  const onEsc = (event) => { if (event.key === "Escape") close(); };
  function close() {
    document.removeEventListener("keydown", onEsc);
    root.innerHTML = "";
  }
  $(".modal-close", root).onclick = close;
  $(".overlay", root).onclick = (event) => { if (event.target.classList.contains("overlay")) close(); };
  document.addEventListener("keydown", onEsc);
  return root;
}

const verdictTags = (v) => {
  if (!v) return '<span class="tag muted">未判定</span>';
  const spam = v.spam_label === "ham"
    ? '<span class="tag ham">ham</span>'
    : `<span class="tag spam">${esc(v.spam_label)} ${Number(v.spam_score || 0).toFixed(2)}</span>`;
  const actionCls = v.spam_action === "quarantine" ? "tag warn" : "tag";
  return `${spam}<span class="tag">${esc(v.category)}</span><span class="${actionCls}">${esc(v.spam_action)}</span>`;
};

const bars = (obj, total) => {
  const entries = Object.entries(obj || {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return '<div class="muted">暂无数据</div>';
  const max = Math.max(total || 0, ...entries.map(([, v]) => v), 1);
  return `<div class="barlist">${entries.map(([k, v]) => `
    <div class="item"><span>${esc(k)}</span>
      <div class="bar"><span style="width:${Math.round((v / max) * 100)}%"></span></div>
      <span class="muted">${v}</span></div>`).join("")}</div>`;
};

/* ------------------------------------------------------------------ 顶栏 */

async function refreshHeader() {
  try {
    const h = await api("/api/v1/health");
    $("#mode").textContent = `LLM: ${h.llm_provider} · 回复: ${h.auto_reply_mode}`;
    $("#health").textContent = `服务 ${h.status}`;
    $("#health").className = "badge " + (h.status === "ok" ? "ok" : "bad");
  } catch (e) {
    $("#health").textContent = "服务不可用";
    $("#health").className = "badge bad";
  }
}

/* ------------------------------------------------------------------ 页面：总览 */

async function pageOverview() {
  const [m, recent] = await Promise.all([
    api("/api/v1/metrics/overview"),
    api("/api/v1/mails?size=5"),
  ]);
  const rows = recent.items.map((mail) => `
    <tr class="clickable" data-mail="${mail.id}">
      <td>${esc(mail.from_addr)}<div class="muted">${fmt(mail.received_at)}</div></td>
      <td>${esc(mail.subject)}<div class="snippet">${esc(mail.snippet)}</div></td>
      <td>${verdictTags(mail.verdict)}</td>
      <td><span class="tag muted">${esc(mail.status)}</span></td>
    </tr>`).join("");

  $("#view").innerHTML = `
    <div class="grid">
      <div class="card"><div class="num">${m.mails_total}</div><div class="label">邮件总数</div></div>
      <div class="card"><div class="num">${pct(m.spam_rate)}</div><div class="label">垃圾邮件占比</div></div>
      <div class="card"><div class="num">${m.quarantine_pending}</div><div class="label">隔离区待处理</div></div>
      <div class="card"><div class="num">${m.review_pending}</div><div class="label">待审核回复</div></div>
      <div class="card"><div class="num">${m.feedback_total}</div><div class="label">反馈样本</div></div>
    </div>
    <div class="card">
      <div class="label" style="margin-bottom:10px">分类分布</div>
      ${bars(m.by_category)}
    </div>
    <div class="card">
      <div class="label" style="margin-bottom:10px">垃圾判定分布</div>
      <div>${Object.entries(m.by_spam_action || {}).map(([k, v]) =>
        `<span class="tag ${k === "quarantine" ? "warn" : ""}">${esc(k)} ${v}</span>`).join("") || "暂无数据"}</div>
    </div>
    <div class="card">
      <div class="label" style="margin-bottom:10px">最近邮件</div>
      <table><thead><tr><th>发件人</th><th>主题</th><th>判定</th><th>状态</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" class="empty">暂无邮件，先跑 mailmind demo</td></tr>'}</tbody></table>
    </div>`;
  $$("[data-mail]").forEach((row) => row.onclick = () => openMail(Number(row.dataset.mail)));
}

/* ------------------------------------------------------------------ 页面：收件箱 */

function inboxQuery() {
  const f = state.inbox;
  const params = new URLSearchParams({ size: String(f.size) });
  if (f.q) params.set("q", f.q);
  if (f.status) params.set("status", f.status);
  if (f.category) params.set("category", f.category);
  if (f.cursor) params.set("cursor", f.cursor);
  return params.toString();
}

async function pageInbox() {
  const f = state.inbox;
  const data = await api(`/api/v1/mails?${inboxQuery()}`);
  const rows = data.items.map((mail) => `
    <tr class="clickable" data-mail="${mail.id}">
      <td>${esc(mail.from_addr)}<div class="muted">${fmt(mail.received_at)}</div></td>
      <td>${esc(mail.subject)}<div class="snippet">${esc(mail.snippet)}</div></td>
      <td>${verdictTags(mail.verdict)}</td>
      <td><span class="tag muted">${esc(mail.status)}</span></td>
      <td>
        <button class="act" data-draft="${mail.id}">AI 起草</button>
        <button class="act" data-spam="${mail.id}">是垃圾</button>
        <button class="act" data-ham="${mail.id}">非垃圾</button>
      </td>
    </tr>`).join("");

  $("#view").innerHTML = `
    <div class="card">
      <div class="row">
        <input class="grow" id="fq" placeholder="搜索主题 / 正文 / 发件人" value="${esc(f.q)}" />
        <select class="fixed" id="fstatus" style="width:130px">${STATUSES.map(([v, label]) =>
          `<option value="${v}" ${f.status === v ? "selected" : ""}>${label}</option>`).join("")}</select>
        <select class="fixed" id="fcategory" style="width:130px">
          <option value="">全部类别</option>
          ${CATEGORIES.map((c) => `<option value="${c}" ${f.category === c ? "selected" : ""}>${c}</option>`).join("")}
        </select>
        <button class="act primary fixed" id="fsearch">查询</button>
        <button class="act fixed" id="freset">重置</button>
      </div>
    </div>
    <table><thead><tr><th>发件人</th><th>主题</th><th>判定</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="empty">没有匹配的邮件</td></tr>'}</tbody></table>
    <div class="row" style="margin-top:12px">
      <button class="act fixed" id="prev" ${f.stack.length ? "" : "disabled"}>← 上一页</button>
      <button class="act fixed" id="next" ${data.next_cursor ? "" : "disabled"}>下一页 →</button>
      <span class="muted">第 ${f.page} 页 · 共 ${data.total} 封</span>
    </div>`;

  const search = () => {
    state.inbox.q = $("#fq").value.trim();
    state.inbox.status = $("#fstatus").value;
    state.inbox.category = $("#fcategory").value;
    state.inbox.cursor = null;
    state.inbox.stack = [];
    state.inbox.page = 1;
    render();
  };
  $("#fsearch").onclick = search;
  $("#fq").addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
  $("#freset").onclick = () => {
    state.inbox = { q: "", status: "", category: "", size: f.size, cursor: null, stack: [], page: 1 };
    render();
  };
  $("#prev").onclick = () => {
    if (!state.inbox.stack.length) return;
    state.inbox.cursor = state.inbox.stack.pop();
    state.inbox.page = Math.max(1, state.inbox.page - 1);
    render();
  };
  $("#next").onclick = () => {
    if (!data.next_cursor) return;
    state.inbox.stack.push(state.inbox.cursor);
    state.inbox.cursor = data.next_cursor;
    state.inbox.page += 1;
    render();
  };

  bindMailRows();
}

function bindMailRows() {
  $$("[data-mail]").forEach((row) => {
    row.onclick = (event) => {
      if (event.target.closest("button")) return;
      openMail(Number(row.dataset.mail));
    };
  });
  $$("[data-draft]").forEach((btn) => btn.onclick = async (event) => {
    event.stopPropagation();
    try {
      const draft = await api(`/api/v1/mails/${btn.dataset.draft}/reply/draft`, { method: "POST" });
      toast(`草稿已生成（${draft.status}，置信度 ${Number(draft.confidence).toFixed(2)}）`, "ok");
      openMail(Number(btn.dataset.draft));
    } catch (e) { toast(e.message, "err"); }
  });
  $$("[data-spam]").forEach((btn) => btn.onclick = async (event) => {
    event.stopPropagation();
    await sendFeedback(btn.dataset.spam, "spam");
  });
  $$("[data-ham]").forEach((btn) => btn.onclick = async (event) => {
    event.stopPropagation();
    await sendFeedback(btn.dataset.ham, "ham");
  });
}

async function sendFeedback(mailId, label, reopen = false) {
  try {
    await api(`/api/v1/mails/${mailId}/feedback`, {
      method: "POST", body: { task: "spam", label: { label } },
    });
    toast(`已标记为 ${label}`, "ok");
    if (reopen) openMail(mailId); else render();
  } catch (e) { toast(e.message, "err"); }
}

/* ------------------------------------------------------------------ 邮件详情 */

async function openMail(id) {
  let mail;
  let thread = null;
  try {
    mail = await api(`/api/v1/mails/${id}`);
    thread = await api(`/api/v1/mails/${id}/thread`).catch(() => null);
  } catch (e) {
    toast(e.message, "err");
    return;
  }
  const v = mail.verdict || {};
  const reasons = (v.spam_reasons || []).map((r) =>
    `<li>${esc(r.desc || r.kind || r.type)}${r.detail && Object.keys(r.detail).length
      ? ` <code class="mono">${esc(JSON.stringify(r.detail))}</code>` : ""}</li>`).join("");
  const scores = Object.entries(v.category_scores || {}).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const attachments = (mail.attachments || []).map((a) => `
    <tr><td>${esc(a.filename)}</td><td>${esc(a.content_type)}</td>
      <td>${a.size_bytes} B</td>
      <td>${a.is_risky ? '<span class="tag spam">可疑</span>' : ""}</td></tr>`).join("");
  const drafts = (mail.drafts || []).map((d) => `
    <div class="card" style="padding:12px">
      <div class="muted">草稿 #${d.id} · ${esc(d.status)} · 置信度 ${Number(d.confidence).toFixed(2)}
        · 引用 ${(d.citations || []).join(",") || "无"} · 风险 ${(d.risk_flags || []).join(",") || "无"}</div>
      <pre class="body">${esc(d.body)}</pre>
      ${d.status === "pending_review" ? `
        <button class="act primary" data-approve="${d.id}" data-mail="${mail.id}">审核通过并发送</button>
        <button class="act danger" data-reject="${d.id}">拒绝</button>` : ""}
    </div>`).join("");

  const threadList = thread && thread.count > 1
    ? `<div style="margin-top:14px"><div class="label">同会话 ${thread.count} 封</div>
        <div>${thread.mails.map((t) => `
          <button class="act" data-thread-mail="${t.id}">#${t.id} ${esc(t.subject || "(无主题)")}</button>`).join("")}</div></div>`
    : "";

  modal(mail.subject || `邮件 #${mail.id}`, `
    <dl class="kv">
      <dt>发件人</dt><dd>${esc(mail.from_name)} &lt;${esc(mail.from_addr)}&gt;</dd>
      <dt>收件人</dt><dd>${(mail.to_addrs || []).map(esc).join(", ") || "-"}</dd>
      <dt>时间</dt><dd>${fmt(mail.received_at)}</dd>
      <dt>状态</dt><dd><span class="tag muted">${esc(mail.status)}</span></dd>
      <dt>Message-ID</dt><dd class="mono">${esc(mail.message_id)}</dd>
    </dl>

    <div class="card">
      <div class="label" style="margin-bottom:8px">判定</div>
      <div>${verdictTags(v)}</div>
      <div class="bar" style="margin:10px 0"><span style="width:${Math.round((v.spam_score || 0) * 100)}%"></span></div>
      <ul class="muted">${reasons || "<li>无命中规则</li>"}</ul>
      <div style="margin-top:10px">${bars(Object.fromEntries(scores))}</div>
    </div>

    <div class="card">
      <div class="label" style="margin-bottom:8px">正文</div>
      <pre class="body">${esc(mail.text_body) || "(空)"}</pre>
    </div>

    ${attachments ? `<div class="card"><div class="label">附件</div>
      <table><tbody>${attachments}</tbody></table></div>` : ""}
    ${drafts ? `<div class="card"><div class="label" style="margin-bottom:8px">回复草稿</div>${drafts}</div>` : ""}

    <div class="row">
      <button class="act primary fixed" id="m-draft">AI 起草</button>
      <button class="act fixed" id="m-spam">标记垃圾</button>
      <button class="act fixed" id="m-ham">标记非垃圾</button>
      <button class="act fixed" id="m-raw">下载 EML</button>
    </div>
    ${threadList}`);

  $("#m-draft").onclick = async () => {
    try {
      const draft = await api(`/api/v1/mails/${mail.id}/reply/draft`, { method: "POST" });
      toast(`草稿已生成（${draft.status}）`, "ok");
      openMail(mail.id);
    } catch (e) { toast(e.message, "err"); }
  };
  $("#m-spam").onclick = () => sendFeedback(mail.id, "spam", true);
  $("#m-ham").onclick = () => sendFeedback(mail.id, "ham", true);
  $("#m-raw").onclick = () => downloadRaw(mail.id);
  $$("[data-approve]").forEach((btn) => btn.onclick = async () => {
    try {
      const res = await api(`/api/v1/replies/${btn.dataset.approve}/approve`, {
        method: "POST", body: { reviewer_id: "ops" },
      });
      toast(res.ok ? "已发送" : `发送失败：${res.error}`, res.ok ? "ok" : "err");
      openMail(mail.id);
    } catch (e) { toast(e.message, "err"); }
  });
  $$("[data-reject]").forEach((btn) => btn.onclick = async () => {
    try {
      await api(`/api/v1/replies/${btn.dataset.reject}/reject`, {
        method: "POST", body: { reviewer_id: "ops", reason: "人工判断不合适" },
      });
      toast("已拒绝", "ok");
      openMail(mail.id);
    } catch (e) { toast(e.message, "err"); }
  });
  $$("[data-thread-mail]").forEach((btn) => btn.onclick = () => openMail(Number(btn.dataset.threadMail)));
}

async function downloadRaw(id) {
  try {
    const res = await fetch(`/api/v1/mails/${id}/raw`, { headers: authHeaders() });
    if (!res.ok) throw new Error(`${res.status} 下载失败`);
    const blob = await res.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `mail-${id}.eml`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (e) { toast(e.message, "err"); }
}

/* ------------------------------------------------------------------ 页面：隔离区 */

async function pageQuarantine() {
  const data = await api("/api/v1/quarantine?size=50");
  const rows = data.items.map((mail) => `
    <tr class="clickable" data-mail="${mail.id}">
      <td>${esc(mail.from_addr)}<div class="muted">${fmt(mail.received_at)}</div></td>
      <td>${esc(mail.subject)}<div class="muted">${(mail.verdict?.spam_reasons || [])
        .map((r) => esc(r.desc || r.kind || r.type)).join(" · ")}</div></td>
      <td>${Number(mail.verdict?.spam_score || 0).toFixed(3)}</td>
      <td>
        <button class="act primary" data-release="${mail.id}">放行并加白</button>
        <button class="act danger" data-del="${mail.id}">删除</button>
      </td>
    </tr>`).join("");
  $("#view").innerHTML = `
    <table><thead><tr><th>发件人</th><th>主题 / 原因</th><th>分数</th><th>操作</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="4" class="empty">隔离区为空 🎉</td></tr>'}</tbody></table>`;
  bindMailRows();
  $$("[data-release]").forEach((btn) => btn.onclick = async (event) => {
    event.stopPropagation();
    try {
      await api(`/api/v1/quarantine/${btn.dataset.release}/release?add_allowlist=true`, { method: "POST" });
      toast("已放行，并把发件域加入白名单", "ok");
      render();
    } catch (e) { toast(e.message, "err"); }
  });
  $$("[data-del]").forEach((btn) => btn.onclick = async (event) => {
    event.stopPropagation();
    if (!confirm("确认删除这封隔离邮件？")) return;
    await api(`/api/v1/quarantine/${btn.dataset.del}/delete`, { method: "POST" });
    toast("已删除", "ok");
    render();
  });
}

/* ------------------------------------------------------------------ 页面：审核 */

async function pageReview() {
  const data = await api("/api/v1/replies?status=pending_review&size=50");
  if (!data.items.length) {
    $("#view").innerHTML = '<div class="card empty">没有待审核的回复草稿</div>';
    return;
  }
  $("#view").innerHTML = `
    <div class="card">
      <label class="field"><span>审核人</span><input id="reviewer" value="ops" style="max-width:220px" /></label>
    </div>` + data.items.map((d) => `
    <div class="card">
      <div class="muted">草稿 #${d.id} · 邮件 #${d.mail_id} · 意图 ${esc(d.intent)}
        · 置信度 ${Number(d.confidence).toFixed(2)} · ${esc(d.model)}</div>
      <h3 style="margin:6px 0">${esc(d.subject)}</h3>
      <textarea data-body="${d.id}">${esc(d.body)}</textarea>
      <div class="row" style="margin-top:10px">
        <button class="act primary fixed" data-approve="${d.id}">审核通过并发送</button>
        <button class="act danger fixed" data-reject="${d.id}">拒绝</button>
        <button class="act fixed" data-open-mail="${d.mail_id}">查看原邮件</button>
        <span class="muted">引用 ${(d.citations || []).join(",") || "无"} · 风险 ${(d.risk_flags || []).join(",") || "无"}</span>
      </div>
    </div>`).join("");

  const reviewer = () => ($("#reviewer")?.value || "ops").trim() || "ops";
  $$("[data-approve]").forEach((btn) => btn.onclick = async () => {
    const id = btn.dataset.approve;
    const body = $(`[data-body="${id}"]`).value;
    try {
      const res = await api(`/api/v1/replies/${id}/approve`, {
        method: "POST", body: { reviewer_id: reviewer(), body },
      });
      toast(res.ok ? "已发送" : `发送失败：${res.error}`, res.ok ? "ok" : "err");
      render();
    } catch (e) { toast(e.message, "err"); }
  });
  $$("[data-reject]").forEach((btn) => btn.onclick = async () => {
    try {
      await api(`/api/v1/replies/${btn.dataset.reject}/reject`, {
        method: "POST", body: { reviewer_id: reviewer(), reason: "人工判断不合适" },
      });
      toast("已拒绝", "ok");
      render();
    } catch (e) { toast(e.message, "err"); }
  });
  $$("[data-open-mail]").forEach((btn) => btn.onclick = () => openMail(Number(btn.dataset.openMail)));
}

/* ------------------------------------------------------------------ 页面：账号 */

async function pageAccounts() {
  const accounts = await api("/api/v1/accounts");
  const rows = accounts.map((a) => `
    <tr>
      <td>${a.id}</td>
      <td>${esc(a.email)}<div class="muted">${esc(a.display_name || "")}</div></td>
      <td><span class="tag">${esc(a.provider)}</span></td>
      <td><span class="tag ${a.status === "active" ? "ham" : "warn"}">${esc(a.status)}</span></td>
      <td class="mono">${a.last_uid} / ${a.uid_validity}</td>
      <td class="muted">${fmt(a.last_synced_at)}</td>
      <td>
        <button class="act" data-sync="${a.id}">同步</button>
        <button class="act danger" data-rm="${a.id}">删除</button>
      </td>
    </tr>`).join("");

  $("#view").innerHTML = `
    <div class="card">
      <div class="label" style="margin-bottom:10px">新建账号</div>
      <div class="row">
        <label class="field grow"><span>邮箱</span><input id="a-email" placeholder="me@company.com" /></label>
        <label class="field fixed" style="width:150px"><span>类型</span>
          <select id="a-provider">
            <option value="imap">IMAP</option>
            <option value="gmail">Gmail API</option>
            <option value="graph">Microsoft Graph</option>
            <option value="memory">memory（演示）</option>
          </select></label>
        <label class="field grow"><span>密码 / Access Token</span><input id="a-secret" type="password" placeholder="应用专用密码或 OAuth token" /></label>
      </div>
      <div class="row">
        <label class="field grow"><span>IMAP host</span><input id="a-imap" placeholder="imap.company.com" /></label>
        <label class="field fixed" style="width:110px"><span>端口</span><input id="a-imap-port" value="993" /></label>
        <label class="field grow"><span>SMTP host</span><input id="a-smtp" placeholder="smtp.company.com" /></label>
        <label class="field fixed" style="width:110px"><span>端口</span><input id="a-smtp-port" value="587" /></label>
      </div>
      <div class="row">
        <button class="act primary fixed" id="a-create">创建</button>
        <span class="muted">密码/Token 会用 MAILMIND_SECRET_KEY 加密存储；演示账号选 memory 后可用「投递」接口灌邮件</span>
      </div>
    </div>
    <table><thead><tr><th>ID</th><th>邮箱</th><th>类型</th><th>状态</th><th>游标</th><th>最近同步</th><th>操作</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="7" class="empty">还没有账号</td></tr>'}</tbody></table>`;

  $("#a-create").onclick = async () => {
    const provider = $("#a-provider").value;
    const config = {};
    if ($("#a-imap").value) config.imap_host = $("#a-imap").value.trim();
    if ($("#a-imap-port").value) config.imap_port = Number($("#a-imap-port").value);
    if ($("#a-smtp").value) config.smtp_host = $("#a-smtp").value.trim();
    if ($("#a-smtp-port").value) config.smtp_port = Number($("#a-smtp-port").value);
    try {
      await api("/api/v1/accounts", {
        method: "POST",
        body: {
          email: $("#a-email").value.trim(),
          provider,
          config,
          secret: $("#a-secret").value,
        },
      });
      toast("账号已创建", "ok");
      render();
    } catch (e) { toast(e.message, "err"); }
  };
  $$("[data-sync]").forEach((btn) => btn.onclick = async () => {
    btn.disabled = true;
    try {
      const res = await api(`/api/v1/accounts/${btn.dataset.sync}/sync`, { method: "POST" });
      toast(`同步完成：拉取 ${res.fetched}，入库 ${res.ingested}，重复 ${res.duplicates}，失败 ${res.failed}`, "ok");
      render();
    } catch (e) {
      toast(e.message, "err");
      btn.disabled = false;
    }
  });
  $$("[data-rm]").forEach((btn) => btn.onclick = async () => {
    if (!confirm("删除账号会级联删除其邮件，确认？")) return;
    await api(`/api/v1/accounts/${btn.dataset.rm}`, { method: "DELETE" });
    toast("已删除", "ok");
    render();
  });
}

/* ------------------------------------------------------------------ 页面：规则 */

async function pageRules() {
  const rules = await api("/api/v1/rules");
  const rows = rules.map((r) => `
    <tr>
      <td>${r.id}</td>
      <td><span class="tag">${esc(r.kind)}</span></td>
      <td><span class="tag ${r.action === "spam" ? "spam" : r.action === "ham" ? "ham" : ""}">${esc(r.action)}</span></td>
      <td class="mono">${esc(JSON.stringify(r.payload))}</td>
      <td>${r.priority}</td>
      <td>${esc(r.description || "")}</td>
      <td>
        <button class="act" data-toggle="${r.id}" data-on="${r.enabled}">${r.enabled ? "禁用" : "启用"}</button>
        <button class="act danger" data-rule-del="${r.id}">删除</button>
      </td>
    </tr>`).join("");

  $("#view").innerHTML = `
    <div class="card">
      <div class="label" style="margin-bottom:10px">规则试算（只计算不落库，用于调阈值）</div>
      <div class="row">
        <input class="grow" id="rt-from" placeholder="发件人，如 promo@spam.cn" />
        <input class="grow" id="rt-subject" placeholder="主题，如 恭喜中奖" />
      </div>
      <div style="height:8px"></div>
      <textarea id="rt-body" placeholder="正文，例如：立即点击 http://1.2.3.4/x 领取 10000 元"></textarea>
      <div class="row" style="margin-top:10px">
        <button class="act primary fixed" id="rt-run">试算判定</button>
        <span class="muted">返回 spam 分数/动作、命中规则与分类结果</span>
      </div>
      <pre id="rt-out" style="display:none"></pre>
    </div>

    <div class="card">
      <div class="label" style="margin-bottom:10px">新增规则</div>
      <div class="row">
        <select class="fixed" id="r-kind" style="width:170px">
          ${["allowlist", "blocklist", "keyword", "header", "auth", "sender_reputation", "category", "subject_regex"]
            .map((k) => `<option value="${k}">${k}</option>`).join("")}
        </select>
        <select class="fixed" id="r-action" style="width:120px">
          ${["spam", "ham", "tag", "route"].map((a) => `<option value="${a}">${a}</option>`).join("")}
        </select>
        <input class="grow" id="r-payload" placeholder='payload JSON，如 {"domains":["spam.cn"]}' />
        <input class="grow" id="r-desc" placeholder="描述" />
        <button class="act primary fixed" id="r-create">新增</button>
      </div>
    </div>

    <table><thead><tr><th>ID</th><th>类型</th><th>动作</th><th>内容</th><th>优先级</th><th>描述</th><th>操作</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="7" class="empty">暂无规则</td></tr>'}</tbody></table>`;

  $("#rt-run").onclick = async () => {
    const out = $("#rt-out");
    try {
      const res = await api("/api/v1/rules/test", {
        method: "POST",
        body: {
          from_addr: $("#rt-from").value,
          subject: $("#rt-subject").value,
          body: $("#rt-body").value,
        },
      });
      out.style.display = "block";
      out.textContent = JSON.stringify({
        spam: res.spam,
        category: res.classification.category,
        hits: (res.rule_hits || []).map((h) => h.desc || h.kind),
        features: res.features,
      }, null, 2);
    } catch (e) {
      out.style.display = "block";
      out.textContent = `试算失败：${e.message}`;
    }
  };
  $("#r-create").onclick = async () => {
    try {
      await api("/api/v1/rules", {
        method: "POST",
        body: {
          kind: $("#r-kind").value,
          action: $("#r-action").value,
          payload: JSON.parse($("#r-payload").value || "{}"),
          description: $("#r-desc").value,
        },
      });
      toast("规则已创建，立即生效", "ok");
      render();
    } catch (e) { toast(e.message, "err"); }
  };
  $$("[data-toggle]").forEach((btn) => btn.onclick = async () => {
    await api(`/api/v1/rules/${btn.dataset.toggle}`, {
      method: "PATCH", body: { enabled: btn.dataset.on !== "true" },
    });
    render();
  });
  $$("[data-rule-del]").forEach((btn) => btn.onclick = async () => {
    if (!confirm("确认删除该规则？")) return;
    await api(`/api/v1/rules/${btn.dataset.ruleDel}`, { method: "DELETE" });
    toast("已删除", "ok");
    render();
  });
}

/* ------------------------------------------------------------------ 页面：知识库 */

async function pageKb() {
  const docs = await api("/api/v1/kb/documents");
  const rows = docs.items.map((d) => `
    <tr>
      <td>${d.id}</td>
      <td>${esc(d.title)}</td>
      <td>${esc(d.content).slice(0, 160)}…</td>
      <td><span class="tag">${esc(d.source)}</span></td>
      <td><button class="act danger" data-kb-del="${d.id}">删除</button></td>
    </tr>`).join("");

  $("#view").innerHTML = `
    <div class="card">
      <div class="label" style="margin-bottom:10px">导入知识（按空行自动切片）</div>
      <input id="kb-title" placeholder="标题，如「退换货政策」" />
      <div style="height:8px"></div>
      <textarea id="kb-content" placeholder="知识内容"></textarea>
      <div class="row" style="margin-top:10px">
        <button class="act primary fixed" id="kb-create">导入</button>
        <input class="grow" id="kb-q" placeholder="检索测试：输入一句话" />
        <button class="act fixed" id="kb-search">检索</button>
      </div>
      <pre id="kb-result" style="display:none"></pre>
    </div>
    <table><thead><tr><th>ID</th><th>标题</th><th>内容</th><th>来源</th><th>操作</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="empty">知识库为空</td></tr>'}</tbody></table>`;

  $("#kb-create").onclick = async () => {
    try {
      const res = await api("/api/v1/kb/documents", {
        method: "POST",
        body: { title: $("#kb-title").value, content: $("#kb-content").value, source: "faq" },
      });
      toast(`已导入，切成 ${res.chunks} 个片段`, "ok");
      render();
    } catch (e) { toast(e.message, "err"); }
  };
  $("#kb-search").onclick = async () => {
    const q = $("#kb-q").value.trim();
    if (!q) return;
    const res = await api(`/api/v1/kb/search?q=${encodeURIComponent(q)}&top_k=5`);
    const out = $("#kb-result");
    out.style.display = "block";
    out.textContent = JSON.stringify(res.items, null, 2);
  };
  $$("[data-kb-del]").forEach((btn) => btn.onclick = async () => {
    if (!confirm("确认删除该知识片段？")) return;
    await api(`/api/v1/kb/documents/${btn.dataset.kbDel}`, { method: "DELETE" });
    toast("已删除", "ok");
    render();
  });
}

/* ------------------------------------------------------------------ 页面：审计 */

async function pageAudit() {
  const action = state.auditAction || "";
  const data = await api(`/api/v1/audit?limit=100${action ? `&action=${encodeURIComponent(action)}` : ""}`);
  const rows = data.items.map((item) => `
    <tr class="clickable" data-audit='${esc(JSON.stringify(item))}'>
      <td class="muted">${fmt(item.created_at)}</td>
      <td>${esc(item.actor)}</td>
      <td><span class="tag">${esc(item.action)}</span></td>
      <td>${esc(item.target)}</td>
      <td class="mono muted">${esc(item.trace_id)}</td>
    </tr>`).join("");
  $("#view").innerHTML = `
    <div class="card">
      <div class="row">
        <input class="grow" id="audit-action" placeholder="按动作前缀过滤，如 mail. / reply. / quarantine." value="${esc(action)}" />
        <button class="act primary fixed" id="audit-search">查询</button>
      </div>
    </div>
    <table><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>trace</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="empty">暂无审计记录</td></tr>'}</tbody></table>`;
  $("#audit-search").onclick = () => {
    state.auditAction = $("#audit-action").value.trim();
    render();
  };
  $$("[data-audit]").forEach((row) => row.onclick = () => {
    const item = JSON.parse(row.dataset.audit);
    modal(`审计 #${item.id}`, `<pre>${esc(JSON.stringify(item, null, 2))}</pre>`);
  });
}

/* ------------------------------------------------------------------ 页面：反馈 */

async function pageFeedback() {
  const data = await api("/api/v1/feedback?limit=100");
  const rows = data.items.map((item) => `
    <tr>
      <td>${item.id}</td>
      <td>${item.mail_id}</td>
      <td><span class="tag">${esc(item.task)}</span></td>
      <td>${esc(item.source)}</td>
      <td class="mono">${esc(JSON.stringify(item.label))}</td>
      <td>${item.weight}</td>
      <td class="muted">${fmt(item.created_at)}</td>
    </tr>`).join("");
  $("#view").innerHTML = `
    <div class="card muted">反馈会以 3 倍权重进入训练集；点「重训」或在终端执行 <code class="mono">mailmind train</code> 生效。</div>
    <table><thead><tr><th>ID</th><th>邮件</th><th>任务</th><th>来源</th><th>标签</th><th>权重</th><th>时间</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="7" class="empty">暂无反馈</td></tr>'}</tbody></table>`;
}

/* ------------------------------------------------------------------ 路由 */

const PAGES = {
  overview: pageOverview,
  inbox: pageInbox,
  quarantine: pageQuarantine,
  review: pageReview,
  accounts: pageAccounts,
  rules: pageRules,
  kb: pageKb,
  audit: pageAudit,
  feedback: pageFeedback,
};

function markActive() {
  $$("#tabs button").forEach((btn) =>
    btn.classList.toggle("active", btn.dataset.tab === state.tab));
}

async function render() {
  const view = $("#view");
  view.innerHTML = '<div class="card empty">加载中…</div>';
  markActive();
  await refreshHeader();
  try {
    await (PAGES[state.tab] || pageOverview)();
  } catch (e) {
    view.innerHTML = `<div class="card err">加载失败：${esc(e.message)}${
      String(e.message).startsWith("401") ? "（请在上方填入 X-API-Key）" : ""}</div>`;
  }
}

function go(tab) {
  state.tab = PAGES[tab] ? tab : "overview";
  if (location.hash !== `#${state.tab}`) {
    location.hash = state.tab;  // 由 hashchange 触发 render，避免重复请求
  } else {
    render();
  }
}

/* ------------------------------------------------------------------ 启动 */

$("#apikey").value = apiKey();
$("#apikey").addEventListener("change", (e) => {
  localStorage.setItem("mailmind-key", e.target.value.trim());
  toast("API Key 已保存", "ok");
  render();
});
$("#refresh").onclick = () => render();
$$("#tabs button").forEach((btn) => btn.onclick = () => go(btn.dataset.tab));
window.addEventListener("hashchange", () => {
  state.tab = (location.hash || "#overview").slice(1);
  render();
});

state.tab = (location.hash || "#overview").slice(1);
if (!PAGES[state.tab]) state.tab = "overview";
render();
