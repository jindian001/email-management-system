import { useState } from "react";
import { api } from "../api";
import { DataTable, Field, Tag, formatTime } from "../components/ui";
import { useToast } from "../components/Toast";
import { useLoad } from "../hooks";
import type { Account, SyncResult } from "../types";

const PROVIDERS = ["imap", "gmail", "graph", "memory"];

export function AccountsPage() {
  const toast = useToast();
  const list = useLoad(() => api<Account[]>("accounts"));
  const [form, setForm] = useState({
    email: "",
    provider: "imap",
    secret: "",
    imapHost: "",
    imapPort: "993",
    smtpHost: "",
    smtpPort: "587",
  });

  const create = async () => {
    const config: Record<string, unknown> = {};
    if (form.imapHost) config.imap_host = form.imapHost.trim();
    if (form.imapPort) config.imap_port = Number(form.imapPort);
    if (form.smtpHost) config.smtp_host = form.smtpHost.trim();
    if (form.smtpPort) config.smtp_port = Number(form.smtpPort);
    try {
      await api("accounts", {
        method: "POST",
        body: {
          email: form.email.trim(),
          provider: form.provider,
          config,
          secret: form.secret,
        },
      });
      toast("账号已创建", "ok");
      setForm({ ...form, email: "", secret: "" });
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const sync = async (account: Account) => {
    try {
      const result = await api<SyncResult>("accountSync", {
        params: { id: account.id },
        method: "POST",
      });
      toast(
        `同步完成：拉取 ${result.fetched}，入库 ${result.ingested}，重复 ${result.duplicates}，失败 ${result.failed}`,
        "ok",
      );
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const updateSecret = async (account: Account) => {
    const secret = window.prompt(
      `为 ${account.email} 输入新的密码 / Access Token（留空表示清除凭据）`,
    );
    if (secret === null) return;
    try {
      await api("account", { params: { id: account.id }, method: "PATCH", body: { secret } });
      toast("凭据已更新", "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const toggleStatus = async (account: Account) => {
    const next = account.status === "active" ? "paused" : "active";
    try {
      await api("account", { params: { id: account.id }, method: "PATCH", body: { status: next } });
      toast(next === "paused" ? "已暂停同步" : "已恢复", "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const remove = async (account: Account) => {
    if (!window.confirm(`删除账号 ${account.email} 会级联删除其邮件，确认？`)) return;
    try {
      await api("account", { params: { id: account.id }, method: "DELETE" });
      toast("已删除", "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  return (
    <>
      <div className="card">
        <div className="label" style={{ marginBottom: 10 }}>
          新建账号
        </div>
        <div className="row">
          <Field label="邮箱">
            <input
              placeholder="me@company.com"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
            />
          </Field>
          <Field label="类型" width={150}>
            <select
              value={form.provider}
              onChange={(event) => setForm({ ...form, provider: event.target.value })}
            >
              {PROVIDERS.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
          </Field>
          <Field label="密码 / Access Token">
            <input
              type="password"
              placeholder="应用专用密码或 OAuth token"
              value={form.secret}
              onChange={(event) => setForm({ ...form, secret: event.target.value })}
            />
          </Field>
        </div>
        <div className="row">
          <Field label="IMAP host">
            <input
              placeholder="imap.company.com"
              value={form.imapHost}
              onChange={(event) => setForm({ ...form, imapHost: event.target.value })}
            />
          </Field>
          <Field label="端口" width={110}>
            <input
              value={form.imapPort}
              onChange={(event) => setForm({ ...form, imapPort: event.target.value })}
            />
          </Field>
          <Field label="SMTP host">
            <input
              placeholder="smtp.company.com"
              value={form.smtpHost}
              onChange={(event) => setForm({ ...form, smtpHost: event.target.value })}
            />
          </Field>
          <Field label="端口" width={110}>
            <input
              value={form.smtpPort}
              onChange={(event) => setForm({ ...form, smtpPort: event.target.value })}
            />
          </Field>
        </div>
        <div className="row">
          <button className="act primary" onClick={create}>
            创建
          </button>
          <span className="muted">
            凭据会用 MAILMIND_SECRET_KEY 加密存储；provider=memory 可配合「投递」接口做演示
          </span>
        </div>
      </div>

      {list.error ? <div className="card err">加载失败：{list.error}</div> : null}
      <DataTable<Account>
        loading={list.loading}
        rows={list.data || []}
        rowKey={(account) => account.id}
        empty="还没有账号"
        columns={[
          { key: "id", title: "ID", render: (account) => account.id },
          {
            key: "email",
            title: "邮箱",
            render: (account) => (
              <>
                {account.email}
                <div className="muted">{account.display_name}</div>
              </>
            ),
          },
          { key: "provider", title: "类型", render: (account) => <Tag>{account.provider}</Tag> },
          {
            key: "status",
            title: "状态",
            render: (account) => (
              <Tag tone={account.status === "active" ? "ham" : "warn"}>{account.status}</Tag>
            ),
          },
          {
            key: "cursor",
            title: "游标",
            render: (account) => (
              <span className="mono">
                {account.last_uid} / {account.uid_validity}
              </span>
            ),
          },
          {
            key: "synced",
            title: "最近同步",
            render: (account) => <span className="muted">{formatTime(account.last_synced_at)}</span>,
          },
          {
            key: "actions",
            title: "操作",
            render: (account) => (
              <>
                <button className="act" onClick={() => sync(account)}>
                  同步
                </button>
                <button className="act" onClick={() => updateSecret(account)}>
                  改凭据
                </button>
                <button className="act" onClick={() => toggleStatus(account)}>
                  {account.status === "active" ? "暂停" : "启用"}
                </button>
                <button className="act danger" onClick={() => remove(account)}>
                  删除
                </button>
              </>
            ),
          },
        ]}
      />
    </>
  );
}
