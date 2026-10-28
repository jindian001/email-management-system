import { api } from "../api";
import { DataTable, formatTime } from "../components/ui";
import { useToast } from "../components/Toast";
import { useLoad } from "../hooks";
import type { FeedbackItem } from "../types";

interface FeedbackPageData {
  items: FeedbackItem[];
}

export function FeedbackPage() {
  const toast = useToast();
  const list = useLoad(() => api<FeedbackPageData>("feedback", { query: { limit: 100 } }));

  const retrain = async () => {
    try {
      const result = await api<{ ok: boolean; stats: Record<string, number> }>("retrain", {
        method: "POST",
      });
      toast(`重训完成：${JSON.stringify(result.stats)}`, "ok");
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  return (
    <>
      <div className="card">
        <div className="row">
          <span className="muted">
            反馈会以 3 倍权重进入训练集；点「立即重训」或执行{" "}
            <code className="mono">mailmind train</code> 生效。
          </span>
          <span className="spacer" />
          <button className="act primary fixed" onClick={retrain}>
            立即重训
          </button>
        </div>
      </div>

      {list.error ? <div className="card err">加载失败：{list.error}</div> : null}
      <DataTable<FeedbackItem>
        loading={list.loading}
        rows={list.data?.items || []}
        rowKey={(item) => item.id}
        empty="暂无反馈"
        columns={[
          { key: "id", title: "ID", render: (item) => item.id },
          { key: "mail", title: "邮件", render: (item) => item.mail_id },
          { key: "task", title: "任务", render: (item) => item.task },
          { key: "source", title: "来源", render: (item) => item.source },
          {
            key: "label",
            title: "标签",
            render: (item) => <span className="mono">{JSON.stringify(item.label)}</span>,
          },
          { key: "weight", title: "权重", render: (item) => item.weight },
          {
            key: "time",
            title: "时间",
            render: (item) => <span className="muted">{formatTime(item.created_at)}</span>,
          },
        ]}
      />
    </>
  );
}
