export interface Reason {
  type?: string;
  kind?: string;
  rule_id?: number | null;
  desc?: string;
  detail?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Verdict {
  spam_label: string;
  spam_score: number;
  spam_action: string;
  spam_reasons: Reason[];
  category: string;
  category_scores: Record<string, number>;
  category_reason: Record<string, unknown>;
  model_versions: Record<string, string>;
}

export interface Attachment {
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  is_risky: boolean;
}

export interface Draft {
  id: number;
  mail_id: number;
  intent: string;
  subject: string;
  body: string;
  citations: number[];
  confidence: number;
  status: string;
  model: string;
  risk_flags: string[];
  reviewer_id?: string;
  provider_message_id?: string;
  created_at?: string;
}

export interface Mail {
  id: number;
  account_id: number;
  message_id: string;
  thread_id: string;
  folder: string;
  from_addr: string;
  from_name: string;
  to_addrs: string[];
  subject: string;
  received_at: string;
  sent_at: string | null;
  status: string;
  has_attachment: boolean;
  snippet: string;
  verdict: Verdict | null;
  text_body?: string;
  headers?: Record<string, string>;
  attachments?: Attachment[];
  drafts?: Draft[];
}

export interface MailPage {
  items: Mail[];
  total: number;
  page: number;
  size: number;
  next_cursor: string | null;
}

export interface Account {
  id: number;
  email: string;
  provider: string;
  display_name: string;
  status: string;
  last_uid: number;
  uid_validity: number;
  last_synced_at: string | null;
  created_at: string | null;
  config: Record<string, unknown>;
}

export interface SyncResult {
  fetched: number;
  ingested: number;
  duplicates: number;
  failed: number;
  reset: boolean;
  last_uid: number;
  uid_validity: number;
}

export interface Rule {
  id: number;
  kind: string;
  action: string;
  payload: Record<string, unknown>;
  scope: string;
  scope_id: string;
  priority: number;
  enabled: boolean;
  description: string;
}

export interface KbDocument {
  id: number;
  title: string;
  content: string;
  source: string;
  metadata: Record<string, unknown>;
  updated_at: string | null;
}

export interface AuditItem {
  id: number;
  actor: string;
  action: string;
  target: string;
  detail: Record<string, unknown>;
  trace_id: string;
  created_at: string | null;
}

export interface FeedbackItem {
  id: number;
  mail_id: number;
  source: string;
  task: string;
  label: Record<string, unknown>;
  note: string;
  weight: number;
  created_at: string | null;
}

export interface Metrics {
  mails_total: number;
  spam_total: number;
  spam_rate: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_spam_action: Record<string, number>;
  drafts_by_status: Record<string, number>;
  quarantine_pending: number;
  review_pending: number;
  feedback_total: number;
  generated_at: string;
}

export interface Health {
  status: string;
  version: string;
  env: string;
  database: string;
  llm_provider: string;
  auto_reply_mode: string;
  storage: string;
}

export interface Thread {
  thread_id: string;
  count: number;
  mails: { id: number; from_addr: string; subject: string; received_at: string | null }[];
}

export interface RuleTestResult {
  spam: {
    label: string;
    score: number;
    action: string;
    reasons: Reason[];
    model_version: string;
    used_llm: boolean;
  };
  classification: { category: string; scores: Record<string, number>; reason: Record<string, unknown> };
  rule_hits: Reason[];
  features: Record<string, unknown>;
}

export interface SendResult {
  ok: boolean;
  status: string;
  provider_message_id: string;
  error: string;
  draft?: Draft;
}
