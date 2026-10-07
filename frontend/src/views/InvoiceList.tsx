import { useEffect, useState } from "react";
import { api, money, ERROR_LABELS, type InvoiceSummary } from "../api";
import { Badge, Button, Card, StatusBadge } from "../ui";

export default function InvoiceList() {
  const [rows, setRows] = useState<InvoiceSummary[]>([]);
  const [contracts, setContracts] = useState<{ id: string; carrier: string }[]>([]);
  const [samples, setSamples] = useState<{ file: string; template: string; injected: string[] }[]>([]);
  const [contractId, setContractId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  const load = () => {
    api.invoices().then(setRows).catch((e) => setMsg({ tone: "err", text: e.message }));
    api.contracts().then(setContracts).catch(() => {});
    api.samples().then(setSamples).catch(() => {});
  };
  useEffect(load, []);

  const run = async (label: string, fn: () => Promise<string>) => {
    setBusy(label);
    setMsg(null);
    try {
      setMsg({ tone: "ok", text: await fn() });
      load();
    } catch (e) {
      setMsg({ tone: "err", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  const uploadInvoice = (f: File) =>
    run("upload", async () => {
      const r = await api.upload(f, contractId || undefined);
      if (r.created) location.hash = `#/invoices/${r.invoice.id}`;
      return r.created ? "Invoice processed." : `Already processed (invoice #${r.invoice.id}); re-upload ignored.`;
    });

  const totalOver = rows.reduce((s, r) => s + (r.overcharge || 0), 0);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="1. Contracts" className="lg:col-span-1">
          <p className="mb-3 text-sm text-slate-600">
            {contracts.length ? `${contracts.length} contract(s) loaded.` : "No contracts yet."} Upload a contract JSON or load the synthetic demo set.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" disabled={!!busy} onClick={() => run("seed", async () => `Loaded ${(await api.seed()).loaded.length} demo contracts.`)}>
              Load demo contracts
            </Button>
            <label className="inline-flex cursor-pointer items-center rounded-lg px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
              Upload contract JSON
              <input type="file" accept=".json,application/json" className="hidden"
                onChange={(e) => e.target.files?.[0] && run("contract", async () => `Loaded ${(await api.uploadContract(e.target.files![0])).contract_id}.`)} />
            </label>
          </div>
          {contracts.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-slate-500">
              {contracts.map((c) => (
                <li key={c.id}><span className="font-mono text-slate-700">{c.id}</span> · {c.carrier}</li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="2. Upload an invoice PDF" className="lg:col-span-2">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex cursor-pointer items-center justify-center rounded-lg border-2 border-dashed border-slate-300 px-6 py-5 text-sm text-slate-600 hover:border-slate-400 hover:bg-slate-50">
              {busy === "upload" ? "Processing…" : "Choose PDF…"}
              <input type="file" accept="application/pdf" className="hidden" disabled={!!busy}
                onChange={(e) => e.target.files?.[0] && uploadInvoice(e.target.files[0])} />
            </label>
            <label className="text-sm text-slate-600">
              Contract{" "}
              <select value={contractId} onChange={(e) => setContractId(e.target.value)} className="ml-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                <option value="">auto-detect from invoice</option>
                {contracts.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
              </select>
            </label>
          </div>
          {samples.length > 0 && (
            <details className="mt-4">
              <summary className="cursor-pointer text-sm text-slate-600">…or process a synthetic test invoice ({samples.length} available)</summary>
              <div className="mt-2 max-h-60 overflow-auto rounded-lg border border-slate-200">
                <table className="w-full text-xs">
                  <tbody>
                    {samples.map((s) => (
                      <tr key={s.file} className="border-b border-slate-100 last:border-0">
                        <td className="px-2 py-1.5 font-mono">{s.file}</td>
                        <td className="px-2"><Badge>{s.template}</Badge></td>
                        <td className="px-2 text-slate-500" title="Ground-truth label from the generator (for demo only)">
                          {s.injected.length ? s.injected.map((t) => ERROR_LABELS[t] ?? t).join(", ") : "clean"}
                        </td>
                        <td className="px-2 text-right">
                          <Button variant="ghost" disabled={!!busy}
                            onClick={() => run(s.file, async () => {
                              const r = await api.processSample(s.file);
                              location.hash = `#/invoices/${r.invoice.id}`;
                              return r.created ? "Processed." : "Already processed.";
                            })}>
                            {busy === s.file ? "…" : "Audit"}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </Card>
      </div>

      {msg && <div className={`rounded-lg px-4 py-2 text-sm ${msg.tone === "ok" ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800"}`}>{msg.text}</div>}

      <Card title="Invoices" actions={<span className="text-xs text-slate-500">Open overcharges: <b className="text-slate-800">{money(totalOver, "USD")}</b></span>}>
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">No invoices yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2 pr-3">#</th><th className="pr-3">Invoice</th><th className="pr-3">Carrier</th><th className="pr-3">B/L</th>
                  <th className="pr-3 text-right">Total</th><th className="pr-3">Status</th><th className="pr-3 text-right">Findings</th>
                  <th className="pr-3 text-right">Overcharge (USD)</th><th>Dispute</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} onClick={() => (location.hash = `#/invoices/${r.id}`)} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50">
                    <td className="py-2 pr-3 text-slate-400">{r.id}</td>
                    <td className="pr-3 font-medium">{r.invoice_number ?? <span className="text-slate-400">{r.filename}</span>}</td>
                    <td className="pr-3">{r.carrier ?? "–"}</td>
                    <td className="pr-3 font-mono text-xs">{r.bl_number ?? "–"}</td>
                    <td className="pr-3 text-right tabular-nums">{money(r.total, r.currency ?? "")}</td>
                    <td className="pr-3"><StatusBadge status={r.status} /></td>
                    <td className="pr-3 text-right tabular-nums">{r.findings || <span className="text-slate-300">0</span>}</td>
                    <td className={`pr-3 text-right tabular-nums ${r.overcharge > 0 ? "font-medium text-rose-700" : "text-slate-300"}`}>{money(r.overcharge)}</td>
                    <td><StatusBadge status={r.dispute_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
