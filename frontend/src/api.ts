export const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export type Status = "audited" | "needs_review" | "processing" | "failed";

export interface InvoiceSummary {
  id: number;
  filename: string;
  carrier: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  bl_number: string | null;
  contract_id: string | null;
  currency: string | null;
  total: number | null;
  status: Status;
  findings: number;
  overcharge: number;
  dispute_status: string | null;
  created_at: string;
}

export interface Line {
  line_no: number;
  description: string;
  charge_type: string;
  mapping_confidence: number;
  quantity: number;
  unit_rate: number;
  amount: number;
}

export interface Finding {
  id: number;
  line_no: number | null;
  error_type: string;
  rule_id: string;
  charge_type: string | null;
  expected: number | null;
  billed: number | null;
  difference: number;
  currency: string;
  confidence: number;
  message: string;
  contract_clause: string;
  invoice_text: string;
  status: "open" | "accepted" | "dismissed";
}

export interface Dispute {
  id: number;
  invoice_id: number;
  to_address: string;
  subject: string;
  body: string;
  amount: number;
  currency: string;
  status: "draft" | "approved" | "rejected" | "sent";
  drafted_by: string;
  reviewer: string | null;
  review_comment: string | null;
  outbox_path: string | null;
  sent_at: string | null;
}

export interface InvoiceDetail extends InvoiceSummary {
  extraction_method: string | null;
  cost_usd: number;
  latency_s: number;
  review_notes: string[];
  invoice: Record<string, unknown> | null;
  lines: Line[];
  finding_list: Finding[];
  dispute: Dispute | null;
}

export interface AuditEvent {
  id: number;
  ts: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor: string;
  details: Record<string, unknown>;
  hash: string;
}

// ---- session -------------------------------------------------------------
export interface SessionUser {
  email: string;
  name: string;
  role: string;
}
const TOKEN_KEY = "fa_session";
let token: string | null = null;
try {
  token = localStorage.getItem(TOKEN_KEY);
} catch {
  /* storage unavailable: session lasts for this tab only */
}
export const session = {
  get token() {
    return token;
  },
  set(t: string | null) {
    token = t;
    try {
      if (t) localStorage.setItem(TOKEN_KEY, t);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};
export const onUnauthorized = new EventTarget();

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(API + path, { ...init, headers });
  if (r.status === 401 && !path.startsWith("/api/auth/login")) {
    session.set(null);
    onUnauthorized.dispatchEvent(new Event("logout"));
  }
  if (!r.ok) {
    let msg = r.statusText;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {
      /* not json */
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  authConfig: () => req<{ demo: { email: string; password: string } | null }>("/api/auth/config"),
  login: (email: string, password: string) =>
    req<{ token: string; user: SessionUser }>("/api/auth/login", json("POST", { email, password })),
  me: () => req<SessionUser>("/api/auth/me"),
  health: () => req<{ llm_configured: boolean; model: string; extractor: string }>("/api/health"),
  contracts: () => req<{ id: string; carrier: string; valid_from: string; valid_to: string; rates: number }[]>("/api/contracts"),
  seed: () => req<{ loaded: string[] }>("/api/demo/seed", { method: "POST" }),
  samples: () => req<{ file: string; template: string; injected: string[] }[]>("/api/demo/samples?limit=60"),
  processSample: (file: string) =>
    req<{ created: boolean; invoice: InvoiceDetail }>(`/api/demo/samples/test/${encodeURIComponent(file)}`, { method: "POST" }),
  upload: (file: File, contractId?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (contractId) fd.append("contract_id", contractId);
    return req<{ created: boolean; invoice: InvoiceDetail }>("/api/invoices", { method: "POST", body: fd });
  },
  uploadContract: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ contract_id: string }>("/api/contracts/upload", { method: "POST", body: fd });
  },
  invoices: () => req<InvoiceSummary[]>("/api/invoices"),
  invoice: (id: number) => req<InvoiceDetail>(`/api/invoices/${id}`),
  pdfUrl: (id: number) => `${API}/api/invoices/${id}/pdf?token=${encodeURIComponent(token ?? "")}`,
  setFinding: (id: number, status: string, actor: string) => req<InvoiceDetail>(`/api/findings/${id}`, json("PATCH", { status, actor })),
  markReviewed: (id: number, actor: string) => req<InvoiceDetail>(`/api/invoices/${id}/reviewed`, json("POST", { actor })),
  draft: (invoiceId: number, actor: string) => req<Dispute>(`/api/invoices/${invoiceId}/dispute`, json("POST", { actor })),
  editDispute: (id: number, subject: string, body: string, actor: string) =>
    req<Dispute>(`/api/disputes/${id}`, json("PUT", { subject, body, actor })),
  approve: (id: number, reviewer: string, comment?: string) => req<Dispute>(`/api/disputes/${id}/approve`, json("POST", { reviewer, comment })),
  reject: (id: number, reviewer: string, comment?: string) => req<Dispute>(`/api/disputes/${id}/reject`, json("POST", { reviewer, comment })),
  send: (id: number, actor: string) => req<Dispute>(`/api/disputes/${id}/send`, json("POST", { actor })),
  audit: (entityType?: string, entityId?: string) => {
    const q = new URLSearchParams();
    if (entityType) q.set("entity_type", entityType);
    if (entityId) q.set("entity_id", entityId);
    return req<AuditEvent[]>(`/api/audit?${q}`);
  },
  verify: () => req<{ ok: boolean; events: number; broken_at: number | null }>("/api/audit/verify"),
  chat: (message: string, invoiceId?: number) =>
    req<{ answer: string; tool_calls: { tool: string }[]; mode: string }>("/api/agent/chat", json("POST", { message, invoice_id: invoiceId })),
  evalResults: () => req<EvalResult[]>("/api/eval/results"),
};

export interface EvalResult {
  name: string;
  arm: string;
  split: string;
  n_invoices: number;
  generated_at: string;
  model: string | null;
  failures: number;
  routed_to_review: number;
  extraction: { field_accuracy: number; perfect_invoices: number } | null;
  detection: {
    overall: { tp: number; fn: number; fp: number; recall: number; precision: number };
    per_type: Record<string, { tp: number; fn: number; fp: number; recall: number | null; precision: number | null }>;
  };
  false_alarms: { clean_line_false_alarm_rate: number; clean_invoice_false_alarm_rate: number };
  money_usd: { injected_overcharge: number; correctly_identified: number; identified_pct: number; falsely_claimed: number };
  cost: { total_usd: number; per_invoice_usd: number };
  latency_s: { mean: number; p95: number };
}

export const money = (n: number | null | undefined, ccy = "") =>
  n == null ? "–" : `${ccy ? ccy + " " : ""}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const ERROR_LABELS: Record<string, string> = {
  wrong_rate: "Wrong rate",
  expired_rate: "Expired rate",
  duplicate_line: "Duplicate line",
  duplicate_invoice: "Duplicate invoice",
  unauthorized_charge: "Unauthorized charge",
  calculation_error: "Calculation error",
  detention_demurrage: "Detention / demurrage",
  currency_tax: "Currency / tax",
};
