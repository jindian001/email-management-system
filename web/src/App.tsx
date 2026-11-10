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
  const [needKey, setNeedKey] = useState(false);
  const health = useLoad(() => api<Health>("health"));

  useEffect(() => {
    const onUnauthorized = () => setNeedKey(true);
    window.addEventListener("mailmind:unauthorized", onUnauthorized);
    return () => window.removeEventListener("mailmind:unauthorized", onUnauthorized);
  }, []);

  useEffect(() => {
    if (health.data?.auth === "enabled" && !getApiKey()) setNeedKey(true);
  }, [health.data]);

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

  const saveKey = () => {
    setApiKey(apiKeyDraft);
    setNeedKey(false);
    refresh();
  };

  const Page = ROUTES[route].component;

  return (
    <>
      <div className="topbar">
        <div className="brand">
          <span className="brand-mark">◈</span>
          <div>
            <h1>MailMind</h1>
            <div className="brand-sub">MAIL OPS CONSOLE</div>
          </div>
        </div>
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
          style={{ maxWidth: 220 }}
          placeholder="X-API-Key"
          value={apiKeyDraft}
          onChange={(event) => setApiKeyDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") saveKey();
          }}
        />
        <button className="act" onClick={saveKey}>
          保存
        </button>
        <button className="act" onClick={refresh}>
          刷新
        </button>
      </div>

      {needKey ? (
        <div className="authbar">
          <span>该服务已启用接口鉴权，请填入 X-API-Key</span>
          <input
            placeholder="粘贴 X-API-Key 后回车"
            value={apiKeyDraft}
            onChange={(event) => setApiKeyDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") saveKey();
            }}
          />
          <button className="act primary" onClick={saveKey}>
            保存并刷新
          </button>
        </div>
      ) : null}

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
