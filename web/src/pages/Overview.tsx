import { useState } from "react";
import { api } from "../api";
import { MailDetail } from "../components/MailDetail";
import { Bars, DataTable, Tag, formatTime, pct } from "../components/ui";
import { useLoad } from "../hooks";
import type { Mail, MailPage, Metrics } from "../types";

export function OverviewPage() {
  const [selected, setSelected] = useState<number | null>(null);
  const metrics = useLoad(() => api<Metrics>("metrics"));
  const recent = useLoad(() => api<MailPage>("mails", { query: { size: 5 } }));

  const m = metrics.data;

  return (
    <>
      {metrics.error ? <div className="card err">指标加载失败：{metrics.error}</div> : null}
      <div className="grid">
        <div className="card">
          <div className="num">{m?.mails_total ?? "-"}</div>
          <div className="label">邮件总数</div>
        </div>
        <div className="card">
          <div className="num">{m ? pct(m.spam_rate) : "-"}</div>
          <div className="label">垃圾邮件占比</div>
        </div>
        <div className="card">
          <div className="num">{m?.quarantine_pending ?? "-"}</div>
          <div className="label">隔离区待处理</div>
        </div>
        <div className="card">
          <div className="num">{m?.review_pending ?? "-"}</div>
          <div className="label">待审核回复</div>
        </div>
        <div className="card">
          <div className="num">{m?.feedback_total ?? "-"}</div>
          <div className="label">反馈样本</div>
        </div>
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 10 }}>
          分类分布
        </div>
        <Bars data={m?.by_category || {}} total={m?.mails_total} />
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 10 }}>
          垃圾判定分布
        </div>
        {Object.entries(m?.by_spam_action || {}).length === 0 ? (
          <div className="muted">暂无数据</div>
        ) : (
          Object.entries(m?.by_spam_action || {}).map(([key, value]) => (
            <Tag key={key} tone={key === "quarantine" ? "warn" : ""}>
              {key} {value}
            </Tag>
          ))
        )}
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 10 }}>
          最近邮件
        </div>
        <DataTable<Mail>
          columns={[
            {
              key: "from",
              title: "发件人",
              render: (mail) => (
                <>
                  {mail.from_addr}
                  <div className="muted">{formatTime(mail.received_at)}</div>
                </>
              ),
            },
            {
              key: "subject",
              title: "主题",
              render: (mail) => (
                <>
                  {mail.subject}
                  <div className="snippet">{mail.snippet}</div>
                </>
              ),
            },
            {
              key: "verdict",
              title: "判定",
              render: (mail) =>
                mail.verdict ? (
                  <>
                    <Tag tone={mail.verdict.spam_label === "ham" ? "ham" : "spam"}>
                      {mail.verdict.spam_label}
                    </Tag>
                    <Tag>{mail.verdict.category}</Tag>
                    <Tag tone={mail.verdict.spam_action === "quarantine" ? "warn" : ""}>
                      {mail.verdict.spam_action}
                    </Tag>
                  </>
                ) : (
                  <Tag tone="muted">未判定</Tag>
                ),
            },
            { key: "status", title: "状态", render: (mail) => <Tag tone="muted">{mail.status}</Tag> },
          ]}
          rows={recent.data?.items || []}
          rowKey={(mail) => mail.id}
          onRowClick={(mail) => setSelected(mail.id)}
          loading={recent.loading}
          empty="暂无邮件，先跑 mailmind demo"
        />
      </div>

      {selected !== null ? (
        <MailDetail
          mailId={selected}
          onClose={() => setSelected(null)}
          onChanged={() => {
            metrics.reload();
            recent.reload();
          }}
        />
      ) : null}
    </>
  );
}
