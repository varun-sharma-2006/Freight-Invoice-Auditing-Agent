import { useCallback, useEffect, useState } from "react";
import { api, money, ERROR_LABELS, type Dispute, type Finding, type InvoiceDetail } from "../api";
import { Badge, Button, Card, Stat, StatusBadge } from "../ui";

export default function InvoiceReview({ id, reviewer }: { id: number; reviewer: string }) {
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showPdf, setShowPdf] = useState(true);
  const load = useCallback(() => api.invoice(id).then(setInv).catch((e) => setErr(e.message)), [id]);
  useEffect(() => {
    load();
  }, [load]);

  if (err) return <div className="rounded-lg bg-rose-50 p-4 text-rose-800">{err}</div>;
  if (!inv) return <div className="text-slate-500">Loading…</div>;

  const actor = reviewer || "reviewer";
  const flagged = new Map<number, Finding[]>();
  inv.finding_list.forEach((f) => f.line_no && flagged.set(f.line_no, [...(flagged.get(f.line_no) ?? []), f]));
  const open = inv.finding_list.filter((f) => f.status !== "dismissed");
  const head = (inv.invoice ?? {}) as Record<string, string | number | null>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <a href="#/" className="text-sm text-slate-500 hover:text-slate-800">← Invoices</a>
        <h1 className="text-xl font-semibold">{inv.invoice_number ?? inv.filename}</h1>
        <StatusBadge status={inv.status} />
        <span className="text-sm text-slate-500">{inv.carrier}</span>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => setShowPdf((v) => !v)}>{showPdf ? "Hide PDF" : "Show PDF"}</Button>
          {inv.status === "needs_review" && inv.invoice && (
            <Button onClick={() => api.markReviewed(inv.id, actor).then(setInv)} title="Confirm you have verified the flagged fields">
              Mark reviewed
            </Button>
          )}
        </div>
      </div>

      {inv.review_notes.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <div className="mb-1 font-medium">{inv.status === "needs_review" ? "Needs human review" : "Notes"}</div>
          <ul className="list-disc space-y-0.5 pl-5">{inv.review_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Invoice total" value={money(inv.total, inv.currency ?? "")} />
        <Stat label="Findings" value={open.length} />
        <Stat label="Disputed overcharge" value={money(open.reduce((s, f) => s + f.difference, 0), "USD")} hint="contract currency" />
        <Stat label="Extraction" value={<span className="text-sm">{inv.extraction_method ?? "failed"}</span>}
          hint={`${inv.latency_s.toFixed(2)}s${inv.cost_usd ? ` · $${inv.cost_usd.toFixed(4)}` : ""}`} />
      </div>

      <div className={`grid gap-4 ${showPdf ? "xl:grid-cols-2" : ""}`}>
        {showPdf && (
          <Card title="Source document" className="xl:sticky xl:top-20 xl:self-start">
            <iframe title="invoice pdf" src={api.pdfUrl(inv.id)} className="h-[78vh] w-full rounded-md border border-slate-200" />
          </Card>
        )}
        <div className="space-y-4">
          {inv.invoice && (
            <Card title="Extracted data">
              <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
                {(["bl_number", "contract_ref", "origin", "destination", "container_type", "container_count", "ship_date", "currency", "exchange_rate",
                  "equipment_out", "equipment_in", "discharge_date", "pickup_date"] as const)
                  .filter((k) => head[k] != null)
                  .map((k) => (
                    <div key={k}><dt className="text-slate-400">{k.replace(/_/g, " ")}</dt><dd className="font-mono text-slate-800">{String(head[k])}</dd></div>
                  ))}
              </dl>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-slate-500">
                    <tr><th className="py-1 pr-2">#</th><th className="pr-2">Description</th><th className="pr-2">Mapped as</th>
                      <th className="pr-2 text-right">Qty</th><th className="pr-2 text-right">Rate</th><th className="text-right">Amount</th></tr>
                  </thead>
                  <tbody>
                    {inv.lines.map((l) => {
                      const fl = flagged.get(l.line_no)?.filter((f) => f.status !== "dismissed");
                      return (
                        <tr key={l.line_no} className={`border-t border-slate-100 ${fl?.length ? "bg-rose-50" : ""}`}>
                          <td className="py-1.5 pr-2 text-slate-400">{l.line_no}</td>
                          <td className="pr-2">{l.description}{fl?.map((f) => <span key={f.id} className="ml-1"><Badge tone="red">{ERROR_LABELS[f.error_type]}</Badge></span>)}</td>
                          <td className="pr-2">
                            <span className={`font-mono ${l.charge_type === "UNKNOWN" ? "text-amber-700" : "text-slate-500"}`}>{l.charge_type}</span>
                            {l.mapping_confidence < 0.9 && <span className="ml-1 text-amber-700" title="mapping confidence">({l.mapping_confidence.toFixed(2)})</span>}
                          </td>
                          <td className="pr-2 text-right tabular-nums">{l.quantity}</td>
                          <td className="pr-2 text-right tabular-nums">{money(l.unit_rate)}</td>
                          <td className="text-right tabular-nums">{money(l.amount)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot className="text-slate-600">
                    {(["subtotal", "tax_amount", "total"] as const).map((k) => (
                      <tr key={k} className="border-t border-slate-200"><td colSpan={5} className="py-1 pr-2 text-right">{k.replace("_", " ")}</td>
                        <td className="text-right font-medium tabular-nums">{money(Number(head[k]))}</td></tr>
                    ))}
                  </tfoot>
                </table>
              </div>
            </Card>
          )}

          <Card title={`Findings (${inv.finding_list.length})`}>
            {inv.finding_list.length === 0 ? (
              <p className="text-sm text-slate-500">{inv.invoice ? "No discrepancies against the contract." : "No findings: the document could not be extracted."}</p>
            ) : (
              <ul className="space-y-3">
                {inv.finding_list.map((f) => <FindingCard key={f.id} f={f} onStatus={(s) => api.setFinding(f.id, s, actor).then(setInv)} />)}
              </ul>
            )}
          </Card>

          {inv.finding_list.length > 0 && <DisputePanel inv={inv} reviewer={reviewer} onChange={load} />}
          <AgentChat invoiceId={inv.id} />
        </div>
      </div>
    </div>
  );
}

function FindingCard({ f, onStatus }: { f: Finding; onStatus: (s: string) => void }) {
  const dim = f.status === "dismissed" ? "opacity-50" : "";
  return (
    <li className={`rounded-lg border border-slate-200 p-3 ${dim}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="red">{ERROR_LABELS[f.error_type] ?? f.error_type}</Badge>
        <span className="text-xs text-slate-500">{f.line_no ? `line ${f.line_no}` : "invoice level"} · rule <code>{f.rule_id}</code></span>
        {f.confidence < 0.8 && <Badge tone="amber">low confidence {f.confidence.toFixed(2)}</Badge>}
        {f.status !== "open" && <Badge tone={f.status === "accepted" ? "green" : "slate"}>{f.status}</Badge>}
        <span className="ml-auto text-sm font-semibold tabular-nums text-rose-700">+{money(f.difference, f.currency)}</span>
      </div>
      <p className="mt-2 text-sm text-slate-800">{f.message}</p>
      {(f.expected != null || f.billed != null) && (
        <p className="mt-1 text-xs text-slate-500">Expected <b className="tabular-nums">{money(f.expected, f.currency)}</b> · billed <b className="tabular-nums">{money(f.billed, f.currency)}</b></p>
      )}
      <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
        <div className="rounded-md bg-slate-50 p-2"><div className="mb-0.5 font-medium text-slate-500">Invoice evidence</div><div className="font-mono text-slate-700">{f.invoice_text}</div></div>
        <div className="rounded-md bg-sky-50 p-2"><div className="mb-0.5 font-medium text-sky-700">Contract clause</div><div className="font-mono text-slate-700">{f.contract_clause}</div></div>
      </div>
      <div className="mt-2 flex gap-2">
        <Button variant="ghost" disabled={f.status === "accepted"} onClick={() => onStatus("accepted")}>✓ Accept</Button>
        <Button variant="ghost" disabled={f.status === "dismissed"} onClick={() => onStatus("dismissed")}>✕ Dismiss</Button>
        {f.status !== "open" && <Button variant="ghost" onClick={() => onStatus("open")}>Reset</Button>}
      </div>
    </li>
  );
}

function DisputePanel({ inv, reviewer, onChange }: { inv: InvoiceDetail; reviewer: string; onChange: () => void }) {
  const [d, setD] = useState<Dispute | null>(inv.dispute);
  const [subject, setSubject] = useState(inv.dispute?.subject ?? "");
  const [body, setBody] = useState(inv.dispute?.body ?? "");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const actor = reviewer || "reviewer";

  const act = async (fn: () => Promise<Dispute>) => {
    setBusy(true);
    setErr(null);
    try {
      const nd = await fn();
      setD(nd);
      setSubject(nd.subject);
      setBody(nd.body);
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const dirty = d && (subject !== d.subject || body !== d.body);
  const editable = !d || d.status === "draft" || d.status === "rejected";

  return (
    <Card title="Dispute" actions={d && <StatusBadge status={d.status} />}>
      {!d ? (
        <div className="flex items-center gap-3">
          <Button variant="primary" disabled={busy} onClick={() => act(() => api.draft(inv.id, actor))}>Draft dispute email</Button>
          <span className="text-xs text-slate-500">Uses open and accepted findings. Dismissed findings are excluded.</span>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="text-xs text-slate-500">
            To <span className="font-mono">{d.to_address}</span> · drafted by <code>{d.drafted_by}</code> · amount {money(d.amount, d.currency)}
            {d.reviewer && <> · {d.status} by <b>{d.reviewer}</b></>}
          </div>
          <input value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-50" />
          <textarea value={body} disabled={!editable} onChange={(e) => setBody(e.target.value)} rows={14}
            className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs leading-relaxed disabled:bg-slate-50" />
          {d.status !== "sent" && (
            <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Review comment (optional)"
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          )}
          <div className="flex flex-wrap gap-2">
            {editable && <Button disabled={busy || !dirty} onClick={() => act(() => api.editDispute(d.id, subject, body, actor))}>Save edits</Button>}
            {editable && <Button disabled={busy} onClick={() => act(() => api.draft(inv.id, actor))}>Redraft</Button>}
            {d.status === "draft" && (
              <Button variant="primary" disabled={busy || !!dirty || !reviewer}
                title={!reviewer ? "Enter your name as reviewer (top right)" : dirty ? "Save edits first" : ""}
                onClick={() => act(() => api.approve(d.id, reviewer, comment || undefined))}>
                Approve
              </Button>
            )}
            {(d.status === "draft" || d.status === "approved") && (
              <Button variant="danger" disabled={busy || !reviewer} onClick={() => act(() => api.reject(d.id, reviewer, comment || undefined))}>Reject</Button>
            )}
            <Button variant="primary" disabled={busy || d.status !== "approved"} title={d.status !== "approved" ? "A reviewer must approve first" : "Mock send: saved to outbox"}
              onClick={() => act(() => api.send(d.id, actor))}>
              Send (mock)
            </Button>
          </div>
          {!reviewer && d.status === "draft" && <p className="text-xs text-amber-700">Enter your name in the Reviewer box (top right) to approve.</p>}
          {d.status === "sent" && <p className="text-xs text-emerald-700">Saved to outbox: <span className="font-mono">{d.outbox_path}</span>. No real email was sent.</p>}
          {err && <p className="text-sm text-rose-700">{err}</p>}
        </div>
      )}
      {!d && err && <p className="mt-2 text-sm text-rose-700">{err}</p>}
    </Card>
  );
}

function AgentChat({ invoiceId }: { invoiceId: number }) {
  const [q, setQ] = useState("");
  const [log, setLog] = useState<{ role: "you" | "agent"; text: string; tools?: string[] }[]>([]);
  const [busy, setBusy] = useState(false);
  const ask = async (text: string) => {
    if (!text.trim()) return;
    setLog((l) => [...l, { role: "you", text }]);
    setQ("");
    setBusy(true);
    try {
      const r = await api.chat(text, invoiceId);
      setLog((l) => [...l, { role: "agent", text: r.answer, tools: r.tool_calls.map((t) => t.tool) }]);
    } catch (e) {
      setLog((l) => [...l, { role: "agent", text: `Error: ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Ask the agent">
      <div className="mb-3 flex flex-wrap gap-2">
        {["Explain the findings", "Any duplicates of this invoice?", "Summarise the contract terms"].map((s) => (
          <Button key={s} variant="ghost" disabled={busy} onClick={() => ask(s)}>{s}</Button>
        ))}
      </div>
      <div className="max-h-80 space-y-2 overflow-auto">
        {log.map((m, i) => (
          <div key={i} className={`rounded-lg px-3 py-2 text-sm ${m.role === "you" ? "bg-slate-100" : "border border-slate-200"}`}>
            <div className="whitespace-pre-wrap">{m.text}</div>
            {m.tools && m.tools.length > 0 && <div className="mt-1 text-xs text-slate-400">tools: {m.tools.join(", ")}</div>}
          </div>
        ))}
      </div>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about this invoice…"
          className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        <Button type="submit" variant="primary" disabled={busy}>{busy ? "…" : "Ask"}</Button>
      </form>
    </Card>
  );
}
