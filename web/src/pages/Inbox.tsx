import { useState } from "react";
import { api } from "../api";
import { MailDetail } from "../components/MailDetail";
import { DataTable, Pagination, Tag, formatTime, reasonText } from "../components/ui";
import { useToast } from "../components/Toast";
import { useLoad } from "../hooks";
import type { Mail, MailPage } from "../types";

const CATEGORIES = [
  "",
  "consult",
  "billing",
  "notice",
  "marketing",
  "social",
  "internal",
  "recruiting",
  "complaint",
  "spam",
  "other",
];

const STATUSES: [string, string][] = [
  ["", "全部状态"],
  ["quarantined", "隔离中"],
  ["classified", "已分类"],
  ["pending_review", "待审核"],
  ["replied", "已回复"],
  ["deleted", "已删除"],
];

interface Filters {
  q: string;
  status: string;
  category: string;
}

export function InboxPage() {
  const toast = useToast();
  const [filters, setFilters] = useState<Filters>({ q: "", status: "", category: "" });
  const [draft, setDraft] = useState<Filters>({ q: "", status: "", category: "" });
  const [cursor, setCursor] = useState<string | null>(null);
  const [stack, setStack] = useState<(string | null)[]>([]);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);

  const list = useLoad(() =>
    api<MailPage>("mails", {
      query: {
        size: 20,
        q: filters.q,
        status: filters.status,
        category: filters.category,
        cursor: cursor ?? undefined,
      },
    }),
  );

  const search = () => {
    setFilters(draft);
    setCursor(null);
    setStack([]);
    setPage(1);
    list.reload();
  };

  const reset = () => {
    const empty = { q: "", status: "", category: "" };
    setDraft(empty);
    setFilters(empty);
    setCursor(null);
    setStack([]);
    setPage(1);
    list.reload();
  };

  const feedback = async (id: number, label: "spam" | "ham") => {
    try {
      await api("mailFeedback", { params: { id }, body: { task: "spam", label: { label } } });
      toast(`已标记为 ${label}`, "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const generate = async (id: number) => {
    try {
      const created = await api("mailDraft", { params: { id }, method: "POST" });
      toast("草稿已生成", "ok");
      setSelected(id);
      void created;
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  return (
    <>
      <div className="card">
        <div className="row">
          <input
            className="grow"
            placeholder="搜索主题 / 正文 / 发件人"
            value={draft.q}
            onChange={(event) => setDraft({ ...draft, q: event.target.value })}
            onKeyDown={(event) => {
              if (event.key === "Enter") search();
            }}
          />
          <select
            className="fixed"
            style={{ width: 132 }}
            value={draft.status}
            onChange={(event) => setDraft({ ...draft, status: event.target.value })}
          >
            {STATUSES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <select
            className="fixed"
            style={{ width: 132 }}
            value={draft.category}
            onChange={(event) => setDraft({ ...draft, category: event.target.value })}
          >
            {CATEGORIES.map((value) => (
              <option key={value || "all"} value={value}>
                {value || "全部类别"}
              </option>
            ))}
          </select>
          <button className="act primary fixed" onClick={search}>
            查询
          </button>
          <button className="act fixed" onClick={reset}>
            重置
          </button>
        </div>
      </div>

      {list.error ? <div className="card err">加载失败：{list.error}</div> : null}

      <DataTable<Mail>
        loading={list.loading}
        rows={list.data?.items || []}
        rowKey={(mail) => mail.id}
        onRowClick={(mail) => setSelected(mail.id)}
        empty="没有匹配的邮件"
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
                    {mail.verdict.spam_label} {Number(mail.verdict.spam_score).toFixed(2)}
                  </Tag>
                  <Tag>{mail.verdict.category}</Tag>
                  <Tag tone={mail.verdict.spam_action === "quarantine" ? "warn" : ""}>
                    {mail.verdict.spam_action}
                  </Tag>
                  <div className="muted">
                    {(mail.verdict.spam_reasons || []).slice(0, 2).map((r, i) => (
                      <span key={i}>{reasonText(r as Record<string, unknown>)} </span>
                    ))}
                  </div>
                </>
              ) : (
                <Tag tone="muted">未判定</Tag>
              ),
          },
          { key: "status", title: "状态", render: (mail) => <Tag tone="muted">{mail.status}</Tag> },
          {
            key: "actions",
            title: "操作",
            render: (mail) => (
              <div onClick={(event) => event.stopPropagation()}>
                <button className="act" onClick={() => generate(mail.id)}>
                  AI 起草
                </button>
                <button className="act" onClick={() => feedback(mail.id, "spam")}>
                  是垃圾
                </button>
                <button className="act" onClick={() => feedback(mail.id, "ham")}>
                  非垃圾
                </button>
              </div>
            ),
          },
        ]}
      />

      <Pagination
        page={page}
        total={list.data?.total ?? 0}
        hasPrev={stack.length > 0}
        hasNext={Boolean(list.data?.next_cursor)}
        onPrev={() => {
          const nextStack = [...stack];
          const previous = nextStack.pop() ?? null;
          setStack(nextStack);
          setCursor(previous);
          setPage((value) => Math.max(1, value - 1));
          list.reload();
        }}
        onNext={() => {
          setStack([...stack, cursor]);
          setCursor(list.data?.next_cursor ?? null);
          setPage((value) => value + 1);
          list.reload();
        }}
      />

      {selected !== null ? (
        <MailDetail mailId={selected} onClose={() => setSelected(null)} onChanged={list.reload} />
      ) : null}
    </>
  );
}
