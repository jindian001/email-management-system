import { useCallback, useEffect, useState } from "react";
import { api, download, endpoint } from "../api";
import type { Draft, Mail, Thread } from "../types";
import { useToast } from "./Toast";
import { Bars, Modal, ScoreBar, Tag, formatTime, reasonText } from "./ui";

interface Props {
  mailId: number;
  onClose: () => void;
  onChanged?: () => void;
}

export function MailDetail({ mailId, onClose, onChanged }: Props) {
  const toast = useToast();
  const [currentId, setCurrentId] = useState(mailId);
  const [mail, setMail] = useState<Mail | null>(null);
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState("");
  const [bodies, setBodies] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (id: number) => {
    setError("");
    try {
      const detail = await api<Mail>("mail", { params: { id } });
      setMail(detail);
      const drafts = detail.drafts || [];
      setBodies(Object.fromEntries(drafts.map((draft) => [draft.id, draft.body])));
      const info = await api<Thread>("mailThread", { params: { id } }).catch(() => null);
      setThread(info);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    void load(currentId);
  }, [currentId, load]);

  const refresh = (changed = false) => {
    void load(currentId);
    if (changed) onChanged?.();
  };

  const feedback = async (label: "spam" | "ham") => {
    try {
      await api("mailFeedback", {
        params: { id: currentId },
        body: { task: "spam", label: { label } },
      });
      toast(`已标记为 ${label}`, "ok");
      refresh(true);
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const draftReply = async () => {
    setBusy(true);
    try {
      const draft = await api<Draft>("mailDraft", { params: { id: currentId }, method: "POST" });
      toast(`草稿已生成（${draft.status}，置信度 ${Number(draft.confidence).toFixed(2)}）`, "ok");
      refresh(true);
    } catch (exc) {
      toast(String(exc), "err");
    } finally {
      setBusy(false);
    }
  };

  const approve = async (draft: Draft) => {
    setBusy(true);
    try {
      const result = await api<{ ok: boolean; status: string; error: string }>("replyApprove", {
        params: { id: draft.id },
        body: { reviewer_id: "ops", body: bodies[draft.id] ?? draft.body },
      });
      toast(result.ok ? "已发送" : `发送失败：${result.error}`, result.ok ? "ok" : "err");
      refresh(true);
    } catch (exc) {
      toast(String(exc), "err");
    } finally {
      setBusy(false);
    }
  };

  const reject = async (draft: Draft) => {
    try {
      await api("replyReject", {
        params: { id: draft.id },
        body: { reviewer_id: "ops", reason: "人工判断不合适" },
      });
      toast("已拒绝", "ok");
      refresh(true);
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const verdict = mail?.verdict;
  const drafts = mail?.drafts || [];

  return (
    <Modal
      title={mail?.subject || `邮件 #${currentId}`}
      onClose={onClose}
      footer={
        <>
          <button className="act primary" onClick={draftReply} disabled={busy}>
            AI 起草
          </button>
          <button className="act" onClick={() => feedback("spam")}>
            标记垃圾
          </button>
          <button className="act" onClick={() => feedback("ham")}>
            标记非垃圾
          </button>
          <button
            className="act"
            onClick={() =>
              download(endpoint("mailRaw", { id: currentId }), `mail-${currentId}.eml`).catch((exc) =>
                toast(String(exc), "err"),
              )
            }
          >
            下载 EML
          </button>
        </>
      }
    >
      {error ? <div className="err">加载失败：{error}</div> : null}
      {!mail ? (
        <div className="empty">加载中…</div>
      ) : (
        <>
          <dl className="kv">
            <dt>发件人</dt>
            <dd>
              {mail.from_name} &lt;{mail.from_addr}&gt;
            </dd>
            <dt>收件人</dt>
            <dd>{(mail.to_addrs || []).join(", ") || "-"}</dd>
            <dt>时间</dt>
            <dd>{formatTime(mail.received_at)}</dd>
            <dt>状态</dt>
            <dd>
              <Tag tone="muted">{mail.status}</Tag>
            </dd>
            <dt>Message-ID</dt>
            <dd className="mono">{mail.message_id}</dd>
          </dl>

          <div className="card">
            <div className="label" style={{ marginBottom: 8 }}>
              判定
            </div>
            {verdict ? (
              <>
                <div>
                  <Tag tone={verdict.spam_label === "ham" ? "ham" : "spam"}>
                    {verdict.spam_label} {Number(verdict.spam_score).toFixed(3)}
                  </Tag>
                  <Tag tone={verdict.spam_action === "quarantine" ? "warn" : ""}>
                    {verdict.spam_action}
                  </Tag>
                  <Tag>{verdict.category}</Tag>
                </div>
                <ScoreBar value={verdict.spam_score} />
                <ul className="muted">
                  {(verdict.spam_reasons || []).length === 0 ? (
                    <li>无命中规则</li>
                  ) : (
                    verdict.spam_reasons.map((reason, index) => (
                      <li key={index}>
                        {reasonText(reason as Record<string, unknown>)}
                        {reason.detail && Object.keys(reason.detail).length > 0 ? (
                          <span className="mono"> {JSON.stringify(reason.detail)}</span>
                        ) : null}
                      </li>
                    ))
                  )}
                </ul>
                <div style={{ marginTop: 10 }}>
                  <Bars data={verdict.category_scores || {}} />
                </div>
              </>
            ) : (
              <div className="muted">尚未判定</div>
            )}
          </div>

          <div className="card">
            <div className="label" style={{ marginBottom: 8 }}>
              正文
            </div>
            <pre className="body">{mail.text_body || "(空)"}</pre>
          </div>

          {mail.attachments && mail.attachments.length > 0 ? (
            <div className="card">
              <div className="label">附件</div>
              <table>
                <tbody>
                  {mail.attachments.map((attachment) => (
                    <tr key={attachment.sha256}>
                      <td>{attachment.filename}</td>
                      <td className="muted">{attachment.content_type}</td>
                      <td>{attachment.size_bytes} B</td>
                      <td>{attachment.is_risky ? <Tag tone="spam">可疑</Tag> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {drafts.length > 0 ? (
            <div className="card">
              <div className="label" style={{ marginBottom: 8 }}>
                回复草稿
              </div>
              {drafts.map((draft) => (
                <div key={draft.id} style={{ marginBottom: 12 }}>
                  <div className="muted">
                    草稿 #{draft.id} · {draft.status} · 置信度 {Number(draft.confidence).toFixed(2)} · 引用{" "}
                    {(draft.citations || []).join(",") || "无"} · 风险{" "}
                    {(draft.risk_flags || []).join(",") || "无"}
                  </div>
                  <textarea
                    value={bodies[draft.id] ?? draft.body}
                    onChange={(event) =>
                      setBodies((prev) => ({ ...prev, [draft.id]: event.target.value }))
                    }
                  />
                  {draft.status === "pending_review" ? (
                    <div className="row" style={{ marginTop: 6 }}>
                      <button className="act primary" onClick={() => approve(draft)} disabled={busy}>
                        审核通过并发送
                      </button>
                      <button className="act danger" onClick={() => reject(draft)}>
                        拒绝
                      </button>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}

          {thread && thread.count > 1 ? (
            <div className="card">
              <div className="label" style={{ marginBottom: 8 }}>
                同会话 {thread.count} 封
              </div>
              <div className="row">
                {thread.mails.map((item) => (
                  <button key={item.id} className="act" onClick={() => setCurrentId(item.id)}>
                    #{item.id} {item.subject || "(无主题)"}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}
    </Modal>
  );
}
