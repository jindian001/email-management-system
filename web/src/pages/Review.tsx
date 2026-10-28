import { useState } from "react";
import { api } from "../api";
import { MailDetail } from "../components/MailDetail";
import { Tag } from "../components/ui";
import { useToast } from "../components/Toast";
import { useLoad } from "../hooks";
import type { Draft } from "../types";

interface DraftPage {
  items: Draft[];
}

export function ReviewPage() {
  const toast = useToast();
  const [reviewer, setReviewer] = useState("ops");
  const [bodies, setBodies] = useState<Record<number, string>>({});
  const [openMail, setOpenMail] = useState<number | null>(null);
  const list = useLoad(() => api<DraftPage>("replies", { query: { status: "pending_review", size: 50 } }));

  const items = list.data?.items || [];

  const approve = async (draft: Draft) => {
    try {
      const result = await api<{ ok: boolean; error: string }>("replyApprove", {
        params: { id: draft.id },
        body: { reviewer_id: reviewer, body: bodies[draft.id] ?? draft.body },
      });
      toast(result.ok ? "已发送" : `发送失败：${result.error}`, result.ok ? "ok" : "err");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const reject = async (draft: Draft) => {
    try {
      await api("replyReject", {
        params: { id: draft.id },
        body: { reviewer_id: reviewer, reason: "人工判断不合适" },
      });
      toast("已拒绝", "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  return (
    <>
      <div className="card">
        <label className="field" style={{ maxWidth: 240 }}>
          <span>审核人</span>
          <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
        </label>
      </div>

      {list.error ? <div className="card err">加载失败：{list.error}</div> : null}
      {list.loading ? <div className="card empty">加载中…</div> : null}
      {!list.loading && items.length === 0 ? (
        <div className="card empty">没有待审核的回复草稿</div>
      ) : null}

      {items.map((draft) => (
        <div className="card" key={draft.id}>
          <div className="muted">
            草稿 #{draft.id} · 邮件 #{draft.mail_id} · 意图 {draft.intent} · 置信度{" "}
            {Number(draft.confidence).toFixed(2)} · {draft.model}
          </div>
          <h3 style={{ margin: "6px 0" }}>{draft.subject}</h3>
          <textarea
            value={bodies[draft.id] ?? draft.body}
            onChange={(event) => setBodies((prev) => ({ ...prev, [draft.id]: event.target.value }))}
          />
          <div className="row" style={{ marginTop: 10 }}>
            <button className="act primary" onClick={() => approve(draft)}>
              审核通过并发送
            </button>
            <button className="act danger" onClick={() => reject(draft)}>
              拒绝
            </button>
            <button className="act" onClick={() => setOpenMail(draft.mail_id)}>
              查看原邮件
            </button>
            <span className="muted">
              引用 {(draft.citations || []).join(",") || "无"} · 风险{" "}
              {(draft.risk_flags || []).join(",") || "无"}
            </span>
            {draft.risk_flags?.length ? <Tag tone="warn">需人工确认</Tag> : null}
          </div>
        </div>
      ))}

      {openMail !== null ? (
        <MailDetail mailId={openMail} onClose={() => setOpenMail(null)} onChanged={list.reload} />
      ) : null}
    </>
  );
}
