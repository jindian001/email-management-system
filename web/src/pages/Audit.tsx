import { useState } from "react";
import { api } from "../api";
import { DataTable, Modal, formatTime } from "../components/ui";
import { useLoad } from "../hooks";
import type { AuditItem } from "../types";

interface AuditPageData {
  items: AuditItem[];
}

export function AuditPage() {
  const [action, setAction] = useState("");
  const [selected, setSelected] = useState<AuditItem | null>(null);
  const list = useLoad(() => api<AuditPageData>("audit", { query: { limit: 100, action } }));

  return (
    <>
      <div className="card">
        <div className="row">
          <input
            className="grow"
            placeholder="按动作前缀过滤，如 mail. / reply. / quarantine."
            value={action}
            onChange={(event) => setAction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") list.reload();
            }}
          />
          <button className="act primary fixed" onClick={list.reload}>
            查询
          </button>
        </div>
      </div>

      {list.error ? <div className="card err">加载失败：{list.error}</div> : null}
      <DataTable<AuditItem>
        loading={list.loading}
        rows={list.data?.items || []}
        rowKey={(item) => item.id}
        onRowClick={(item) => setSelected(item)}
        empty="暂无审计记录"
        columns={[
          {
            key: "time",
            title: "时间",
            render: (item) => <span className="muted">{formatTime(item.created_at)}</span>,
          },
          { key: "actor", title: "操作者", render: (item) => item.actor },
          { key: "action", title: "动作", render: (item) => item.action },
          { key: "target", title: "对象", render: (item) => item.target },
          {
            key: "trace",
            title: "trace",
            render: (item) => <span className="mono muted">{item.trace_id}</span>,
          },
        ]}
      />

      {selected ? (
        <Modal title={`审计 #${selected.id}`} onClose={() => setSelected(null)}>
          <pre>{JSON.stringify(selected, null, 2)}</pre>
        </Modal>
      ) : null}
    </>
  );
}
