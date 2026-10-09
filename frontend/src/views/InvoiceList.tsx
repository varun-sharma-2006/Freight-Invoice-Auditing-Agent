import { useEffect, useState } from "react";
import { api, money, ERROR_LABELS, type InvoiceSummary } from "../api";
import { Badge, Button, Card, EmptyState, Icon, Kpi, Skeleton, StatusBadge, useToast } from "../ui";

type Sample = { file: string; template: string; injected: string[] };

export default function InvoiceList() {
  const toast = useToast();
  const [rows, setRows] = useState<InvoiceSummary[] | null>(null);
  const [contracts, setContracts] = useState<{ id: string; carrier: string; rates: number }[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [contractId, setContractId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  const load = () => {
    api.invoices().then(setRows).catch((e) => toast("err", e.message));
    api.contracts().then(setContracts).catch(() => {});
    api.samples().then(setSamples).catch(() => {});
  };
  useEffect(load, []);

  const run = async (label: string, fn: () => Promise<string | null>) => {
    setBusy(label);
    try {
      const msg = await fn();
      if (msg) toast("ok", msg);
      load();
    } catch (e) {
      toast("err", (e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const uploadInvoice = (f: File) =>
    run("upload", async () => {
      const r = await api.upload(f, contractId || undefined);
      location.hash = `#/invoices/${r.invoice.id}`;
      return r.created ? `Audited ${r.invoice.invoice_number ?? f.name}` : "Already processed. Opened the existing audit.";
    });

  const list = rows ?? [];
  const open = list.reduce((s, r) => s + (r.overcharge || 0), 0);
  const flagged = list.filter((r) => r.findings > 0).length;
  const review = list.filter((r) => r.status === "needs_review").length;
  const disputes = list.filter((r) => r.dispute_status).length;
  const sent = list.filter((r) => r.dispute_status === "sent").length;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Kpi label="Invoices audited" value={rows ? list.length : <Skeleton className="h-7 w-12" />} icon="doc" hint={`${flagged} with discrepancies`} />
        <Kpi label="Overcharges found" value={rows ? money(open, "USD") : <Skeleton className="h-7 w-28" />} icon="alert" tone="rose" hint="Open + accepted findings" />
        <Kpi label="Needs review" value={rows ? review : <Skeleton className="h-7 w-10" />} icon="shield" tone="amber" hint="Low confidence or unreadable" />
        <Kpi label="Disputes" value={rows ? disputes : <Skeleton className="h-7 w-10" />} icon="send" tone="emerald" hint={`${sent} sent after approval`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Audit an invoice" subtitle="Carrier PDF in, evidence-backed findings out" className="xl:col-span-2">
          <label
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) uploadInvoice(f); }}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition ${drag ? "border-indigo-400 bg-indigo-50/60" : "border-slate-200 hover:border-indigo-300 hover:bg-slate-50"}`}>
            <span className="rounded-xl bg-indigo-50 p-3 text-indigo-600"><Icon name="upload" className="h-6 w-6" /></span>
            <span className="mt-3 text-sm font-medium text-slate-900">{busy === "upload" ? "Extracting and auditing…" : "Drop an invoice PDF or click to browse"}</span>
            <span className="mt-1 text-xs text-slate-500">PDF up to 4 MB · digital or scanned</span>
            <input type="file" accept="application/pdf" className="hidden" disabled={!!busy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadInvoice(f); e.target.value = ""; }} />
          </label>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span>Audit against</span>
            <select value={contractId} onChange={(e) => setContractId(e.target.value)}
              className="rounded-lg border-0 py-1.5 pl-3 pr-8 text-sm ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-indigo-600">
              <option value="">contract referenced on the invoice</option>
              {contracts.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
            </select>
          </div>

          {samples.length > 0 && (
            <details className="group mt-5 rounded-xl ring-1 ring-slate-200">
              <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium text-slate-700">
                <span className="flex items-center gap-2"><Icon name="spark" className="h-4 w-4 text-indigo-500" /> Try a sample carrier invoice <Badge tone="indigo">{samples.length}</Badge></span>
                <span className="text-xs text-slate-400 group-open:hidden">Show</span>
                <span className="hidden text-xs text-slate-400 group-open:inline">Hide</span>
              </summary>
              <div className="max-h-72 overflow-auto border-t border-slate-100">
                <table className="w-full text-sm">
                  <tbody>
                    {samples.map((s) => (
                      <tr key={s.file} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/70">
                        <td className="px-4 py-2 font-mono text-xs text-slate-700">{s.file.replace(/\.pdf$/, "")}</td>
                        <td className="px-2"><Badge>Layout {s.template}</Badge></td>
                        <td className="px-2 text-xs text-slate-500" title="Ground-truth label from the synthetic generator">
                          {s.injected.length ? s.injected.map((t) => ERROR_LABELS[t] ?? t).join(", ") : "No injected errors"}
                        </td>
                        <td className="px-4 py-1.5 text-right">
                          <Button size="sm" disabled={!!busy}
                            onClick={() => run(s.file, async () => {
                              const r = await api.processSample(s.file);
                              location.hash = `#/invoices/${r.invoice.id}`;
                              return null;
                            })}>
                            {busy === s.file ? "Auditing…" : "Audit"}
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

        <Card title="Carrier contracts" subtitle="Rate sheets the rule engine checks against"
          actions={
            <label className="cursor-pointer text-xs font-medium text-indigo-600 hover:text-indigo-500">
              Upload JSON
              <input type="file" accept=".json,application/json" className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) run("contract", async () => `Loaded contract ${(await api.uploadContract(f)).contract_id}`); e.target.value = ""; }} />
            </label>
          }>
          {contracts.length === 0 ? (
            <div className="text-center">
              <p className="mb-3 text-sm text-slate-500">No contracts loaded.</p>
              <Button variant="primary" disabled={!!busy} onClick={() => run("seed", async () => `Loaded ${(await api.seed()).loaded.length} demo contracts`)}>Load demo contracts</Button>
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {contracts.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-900">{c.carrier}</div>
                    <div className="font-mono text-[11px] text-slate-500">{c.id}</div>
                  </div>
                  <Badge tone="slate">{c.rates} rates</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Audited invoices" subtitle="Click a row to review findings and evidence" padded={false}
        actions={rows && rows.length > 0 ? <span className="text-xs text-slate-500">Open overcharges <b className="ml-1 text-slate-900">{money(open, "USD")}</b></span> : null}>
        {!rows ? (
          <div className="space-y-3 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState icon="upload" title="No invoices yet">Upload a carrier PDF or audit one of the sample invoices above.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-[11px] font-medium uppercase tracking-wide text-slate-500">
                  <th className="px-5 py-3">Invoice</th><th className="px-3">Carrier</th><th className="px-3">B/L</th>
                  <th className="px-3 text-right">Total</th><th className="px-3">Status</th><th className="px-3 text-right">Findings</th>
                  <th className="px-3 text-right">Overcharge</th><th className="px-5">Dispute</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} onClick={() => (location.hash = `#/invoices/${r.id}`)}
                    className="cursor-pointer border-b border-slate-50 transition last:border-0 hover:bg-indigo-50/40">
                    <td className="px-5 py-3">
                      <div className="font-medium text-slate-900">{r.invoice_number ?? <span className="text-slate-400">{r.filename}</span>}</div>
                      <div className="text-xs text-slate-400">{r.invoice_date ?? "Not extracted"}</div>
                    </td>
                    <td className="px-3 text-slate-700">{r.carrier ?? "—"}</td>
                    <td className="px-3 font-mono text-xs text-slate-500">{r.bl_number ?? "—"}</td>
                    <td className="whitespace-nowrap px-3 text-right tabular-nums text-slate-700">{money(r.total, r.currency ?? "")}</td>
                    <td className="px-3"><StatusBadge status={r.status} /></td>
                    <td className="px-3 text-right tabular-nums">{r.findings ? <Badge tone="red">{r.findings}</Badge> : <span className="text-slate-300">0</span>}</td>
                    <td className={`whitespace-nowrap px-3 text-right tabular-nums ${r.overcharge > 0 ? "font-semibold text-rose-600" : "text-slate-300"}`}>{r.overcharge > 0 ? money(r.overcharge, "USD") : "—"}</td>
                    <td className="px-5"><StatusBadge status={r.dispute_status} /></td>
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
