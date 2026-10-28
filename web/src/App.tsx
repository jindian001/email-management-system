import { useEffect, useState } from "react";
import { api, getApiKey, setApiKey } from "./api";
import { Badge } from "./components/ui";
import { useLoad } from "./hooks";
import type { Health } from "./types";
import { AccountsPage } from "./pages/Accounts";
import { AuditPage } from "./pages/Audit";
import { FeedbackPage } from "./pages/Feedback";
import { InboxPage } from "./pages/Inbox";
import { KnowledgePage } from "./pages/Knowledge";
import { OverviewPage } from "./pages/Overview";
import { QuarantinePage } from "./pages/Quarantine";
import { ReviewPage } from "./pages/Review";
import { RulesPage } from "./pages/Rules";

export const ROUTES = {
  overview: { label: "总览", component: OverviewPage },
  inbox: { label: "收件箱", component: InboxPage },
  quarantine: { label: "隔离区", component: QuarantinePage },
  review: { label: "自动回复审核", component: ReviewPage },
  accounts: { label: "账号", component: AccountsPage },
  rules: { label: "规则", component: RulesPage },
  kb: { label: "知识库", component: KnowledgePage },
  audit: { label: "审计", component: AuditPage },
  feedback: { label: "反馈", component: FeedbackPage },
} as const;

export type RouteKey = keyof typeof ROUTES;

function currentRoute(): RouteKey {
  const raw = window.location.hash.replace(/^#\/?/, "");
  return (raw in ROUTES ? raw : "overview") as RouteKey;
}

export default function App() {
  const [route, setRoute] = useState<RouteKey>(currentRoute);
  const [refreshKey, setRefreshKey] = useState(0);
  const [apiKeyDraft, setApiKeyDraft] = useState(getApiKey());
  const health = useLoad(() => api<Health>("health"));

  useEffect(() => {
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (next: RouteKey) => {
    if (window.location.hash !== `#/${next}`) window.location.hash = `#/${next}`;
    else setRoute(next);
  };

  const refresh = () => {
    health.reload();
    setRefreshKey((value) => value + 1);
  };

  const Page = ROUTES[route].component;

  return (
    <>
      <div className="topbar">
        <h1>MailMind</h1>
        <Badge>
          {health.data
            ? `LLM: ${health.data.llm_provider} · 回复: ${health.data.auto_reply_mode}`
            : "加载中…"}
        </Badge>
        <Badge tone={health.data?.status === "ok" ? "ok" : "bad"}>
          {health.data ? `服务 ${health.data.status}` : "-"}
        </Badge>
        <span className="spacer" />
        <input
          style={{ maxWidth: 240 }}
          placeholder="X-API-Key（未启用鉴权可留空）"
          value={apiKeyDraft}
          onChange={(event) => setApiKeyDraft(event.target.value)}
          onBlur={() => {
            setApiKey(apiKeyDraft);
            refresh();
          }}
        />
        <button className="act" onClick={refresh}>
          刷新
        </button>
      </div>

      <div className="layout">
        <nav className="nav">
          {(Object.keys(ROUTES) as RouteKey[]).map((key) => (
            <button key={key} className={key === route ? "active" : ""} onClick={() => go(key)}>
              {ROUTES[key].label}
            </button>
          ))}
        </nav>
        <Page key={`${route}-${refreshKey}`} />
      </div>
    </>
  );
}
