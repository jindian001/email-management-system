import { useState } from "react";
import { api } from "../api";
import { DataTable, Field, Tag } from "../components/ui";
import { useToast } from "../components/Toast";
import { useLoad } from "../hooks";
import type { Rule, RuleTestResult } from "../types";

const KINDS = [
  "allowlist",
  "blocklist",
  "keyword",
  "header",
  "auth",
  "sender_reputation",
  "category",
  "subject_regex",
];
const ACTIONS = ["spam", "ham", "tag", "route"];

export function RulesPage() {
  const toast = useToast();
  const list = useLoad(() => api<Rule[]>("rules"));
  const [form, setForm] = useState({ kind: "blocklist", action: "spam", payload: "", description: "" });
  const [probe, setProbe] = useState({ from: "", subject: "", body: "" });
  const [result, setResult] = useState<RuleTestResult | null>(null);
  const [testError, setTestError] = useState("");

  const create = async () => {
    let payload: Record<string, unknown> = {};
    if (form.payload.trim()) {
      try {
        payload = JSON.parse(form.payload) as Record<string, unknown>;
      } catch {
        toast("payload 不是合法 JSON", "err");
        return;
      }
    }
    try {
      await api("rules", {
        method: "POST",
        body: {
          kind: form.kind,
          action: form.action,
          payload,
          description: form.description,
        },
      });
      toast("规则已创建，立即生效", "ok");
      setForm({ ...form, payload: "", description: "" });
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const toggle = async (rule: Rule) => {
    try {
      await api("rule", { params: { id: rule.id }, method: "PATCH", body: { enabled: !rule.enabled } });
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const remove = async (rule: Rule) => {
    if (!window.confirm(`确认删除规则 #${rule.id}？`)) return;
    try {
      await api("rule", { params: { id: rule.id }, method: "DELETE" });
      toast("已删除", "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const runTest = async () => {
    setTestError("");
    try {
      const response = await api<RuleTestResult>("rulesTest", {
        method: "POST",
        body: { from_addr: probe.from, subject: probe.subject, body: probe.body },
      });
      setResult(response);
    } catch (exc) {
      setResult(null);
      setTestError(String(exc));
    }
  };

  return (
    <>
      <div className="card">
        <div className="label" style={{ marginBottom: 10 }}>
          规则试算（只计算不落库，用于调阈值）
        </div>
        <div className="row">
          <Field label="发件人">
            <input
              placeholder="promo@spam.cn"
              value={probe.from}
              onChange={(event) => setProbe({ ...probe, from: event.target.value })}
            />
          </Field>
          <Field label="主题">
            <input
              placeholder="恭喜中奖"
              value={probe.subject}
              onChange={(event) => setProbe({ ...probe, subject: event.target.value })}
            />
          </Field>
        </div>
        <Field label="正文">
          <textarea
            placeholder="立即点击 http://1.2.3.4/x 领取 10000 元"
            value={probe.body}
            onChange={(event) => setProbe({ ...probe, body: event.target.value })}
          />
        </Field>
        <div className="row">
          <button className="act primary" onClick={runTest}>
            试算判定
          </button>
          <span className="muted">返回 spam 分数/动作、命中规则与特征快照</span>
        </div>
        {testError ? <div className="err">{testError}</div> : null}
        {result ? (
          <pre>{JSON.stringify(
            {
              spam: result.spam,
              category: result.classification.category,
              hits: (result.rule_hits || []).map((hit) => hit.desc || hit.kind),
              features: result.features,
            },
            null,
            2,
          )}</pre>
        ) : null}
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 10 }}>
          新增规则
        </div>
        <div className="row">
          <Field label="类型" width={170}>
            <select value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value })}>
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
          </Field>
          <Field label="动作" width={120}>
            <select
              value={form.action}
              onChange={(event) => setForm({ ...form, action: event.target.value })}
            >
              {ACTIONS.map((action) => (
                <option key={action} value={action}>
                  {action}
                </option>
              ))}
            </select>
          </Field>
          <Field label="payload（JSON）">
            <input
              placeholder='{"domains":["spam.cn"]}'
              value={form.payload}
              onChange={(event) => setForm({ ...form, payload: event.target.value })}
            />
          </Field>
          <Field label="描述">
            <input
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </Field>
          <button className="act primary fixed" onClick={create}>
            新增
          </button>
        </div>
      </div>

      {list.error ? <div className="card err">加载失败：{list.error}</div> : null}
      <DataTable<Rule>
        loading={list.loading}
        rows={list.data || []}
        rowKey={(rule) => rule.id}
        empty="暂无规则"
        columns={[
          { key: "id", title: "ID", render: (rule) => rule.id },
          { key: "kind", title: "类型", render: (rule) => <Tag>{rule.kind}</Tag> },
          {
            key: "action",
            title: "动作",
            render: (rule) => (
              <Tag tone={rule.action === "spam" ? "spam" : rule.action === "ham" ? "ham" : ""}>
                {rule.action}
              </Tag>
            ),
          },
          {
            key: "payload",
            title: "内容",
            render: (rule) => <span className="mono">{JSON.stringify(rule.payload)}</span>,
          },
          { key: "priority", title: "优先级", render: (rule) => rule.priority },
          { key: "desc", title: "描述", render: (rule) => rule.description },
          {
            key: "actions",
            title: "操作",
            render: (rule) => (
              <>
                <button className="act" onClick={() => toggle(rule)}>
                  {rule.enabled ? "禁用" : "启用"}
                </button>
                <button className="act danger" onClick={() => remove(rule)}>
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
