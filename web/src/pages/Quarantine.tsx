import { useState } from "react";
import { api } from "../api";
import { MailDetail } from "../components/MailDetail";
import { DataTable, formatTime, reasonText } from "../components/ui";
import { useToast } from "../components/Toast";
import { useLoad } from "../hooks";
import type { Mail, MailPage } from "../types";

export function QuarantinePage() {
  const toast = useToast();
  const [selected, setSelected] = useState<number | null>(null);
  const list = useLoad(() => api<MailPage>("quarantine", { query: { size: 50 } }));

  const release = async (id: number) => {
    try {
      await api("quarantineRelease", {
        params: { id },
        method: "POST",
        query: { add_allowlist: true },
      });
      toast("已放行，并把发件域加入白名单", "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const remove = async (id: number) => {
    if (!window.confirm("确认删除这封隔离邮件？")) return;
    try {
      await api("quarantineDelete", { params: { id }, method: "POST" });
      toast("已删除", "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  return (
    <>
      {list.error ? <div className="card err">加载失败：{list.error}</div> : null}
      <DataTable<Mail>
        loading={list.loading}
        rows={list.data?.items || []}
        rowKey={(mail) => mail.id}
        onRowClick={(mail) => setSelected(mail.id)}
        empty="隔离区为空 🎉"
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
            title: "主题 / 原因",
            render: (mail) => (
              <>
                {mail.subject}
                <div className="muted">
                  {(mail.verdict?.spam_reasons || [])
                    .map((reason) => reasonText(reason as Record<string, unknown>))
                    .join(" · ")}
                </div>
              </>
            ),
          },
          {
            key: "score",
            title: "分数",
            render: (mail) => Number(mail.verdict?.spam_score || 0).toFixed(3),
          },
          {
            key: "actions",
            title: "操作",
            render: (mail) => (
              <div onClick={(event) => event.stopPropagation()}>
                <button className="act primary" onClick={() => release(mail.id)}>
                  放行并加白
                </button>
                <button className="act danger" onClick={() => remove(mail.id)}>
                  删除
                </button>
              </div>
            ),
          },
        ]}
      />

      {selected !== null ? (
        <MailDetail mailId={selected} onClose={() => setSelected(null)} onChanged={list.reload} />
      ) : null}
    </>
  );
}
