import { useState } from "react";
import { api } from "../api";
import { DataTable, Tag } from "../components/ui";
import { useToast } from "../components/Toast";
import { useLoad } from "../hooks";
import type { KbDocument } from "../types";

interface DocPage {
  items: KbDocument[];
}

interface SearchHit {
  id: number;
  title: string;
  content: string;
  score: number;
}

export function KnowledgePage() {
  const toast = useToast();
  const list = useLoad(() => api<DocPage>("kbDocuments"));
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);

  const create = async () => {
    try {
      const response = await api<{ ids: number[]; chunks: number }>("kbDocuments", {
        method: "POST",
        body: { title, content, source: "faq" },
      });
      toast(`已导入，切成 ${response.chunks} 个片段`, "ok");
      setTitle("");
      setContent("");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const remove = async (doc: KbDocument) => {
    if (!window.confirm(`确认删除知识片段 #${doc.id}？`)) return;
    try {
      await api("kbDocument", { params: { id: doc.id }, method: "DELETE" });
      toast("已删除", "ok");
      list.reload();
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  const search = async () => {
    if (!query.trim()) return;
    try {
      const response = await api<{ items: SearchHit[] }>("kbSearch", {
        query: { q: query, top_k: 5 },
      });
      setHits(response.items);
    } catch (exc) {
      toast(String(exc), "err");
    }
  };

  return (
    <>
      <div className="card">
        <div className="label" style={{ marginBottom: 10 }}>
          导入知识（按空行自动切片）
        </div>
        <input placeholder="标题，如「退换货政策」" value={title} onChange={(event) => setTitle(event.target.value)} />
        <div style={{ height: 8 }} />
        <textarea
          placeholder="知识内容"
          value={content}
          onChange={(event) => setContent(event.target.value)}
        />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="act primary" onClick={create}>
            导入
          </button>
          <input
            className="grow"
            placeholder="检索测试：输入一句话"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void search();
            }}
          />
          <button className="act" onClick={search}>
            检索
          </button>
        </div>
        {hits ? <pre>{JSON.stringify(hits, null, 2)}</pre> : null}
      </div>

      {list.error ? <div className="card err">加载失败：{list.error}</div> : null}
      <DataTable<KbDocument>
        loading={list.loading}
        rows={list.data?.items || []}
        rowKey={(doc) => doc.id}
        empty="知识库为空"
        columns={[
          { key: "id", title: "ID", render: (doc) => doc.id },
          { key: "title", title: "标题", render: (doc) => doc.title },
          { key: "content", title: "内容", render: (doc) => `${doc.content.slice(0, 160)}…` },
          { key: "source", title: "来源", render: (doc) => <Tag>{doc.source}</Tag> },
          {
            key: "actions",
            title: "操作",
            render: (doc) => (
              <button className="act danger" onClick={() => remove(doc)}>
                删除
              </button>
            ),
          },
        ]}
      />
    </>
  );
}
