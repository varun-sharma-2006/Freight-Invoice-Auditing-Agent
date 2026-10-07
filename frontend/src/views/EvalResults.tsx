import { useEffect, useState } from "react";
import { api, money, ERROR_LABELS, type EvalResult } from "../api";
import { Card, Stat } from "../ui";

const pct = (n: number | null | undefined) => (n == null ? "–" : `${n}%`);

export default function EvalResults() {
  const [rows, setRows] = useState<EvalResult[] | null>(null);
  useEffect(() => {
    api.evalResults().then(setRows).catch(() => setRows([]));
  }, []);
  if (!rows) return <div className="text-slate-500">Loading…</div>;
  if (!rows.length)
    return <Card title="Eval results"><p className="text-sm text-slate-600">No results yet. Run <code>python -m evals.run_eval</code> in <code>backend/</code>.</p></Card>;

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Every number below comes from <code>evals/run_eval.py</code> on synthetic data. The <b>test</b> split was never used for tuning, and it includes
        a layout (T5) that does not appear in dev. Scores on synthetic data say nothing definitive about real invoices.
      </p>
      {rows.map((r) => (
        <Card key={r.name} title={<>{r.arm} · <span className="font-normal text-slate-500">{r.split} split, {r.n_invoices} invoices{r.model ? ` · ${r.model}` : ""}</span></>}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Stat label="Extraction accuracy" value={r.extraction ? pct(r.extraction.field_accuracy) : "n/a"} hint="field-level" />
            <Stat label="Recall" value={pct(r.detection.overall.recall)} hint={`${r.detection.overall.tp}/${r.detection.overall.tp + r.detection.overall.fn} injected errors`} />
            <Stat label="Precision" value={pct(r.detection.overall.precision)} hint={`${r.detection.overall.fp} false findings`} />
            <Stat label="Clean-line false alarms" value={pct(r.false_alarms.clean_line_false_alarm_rate)} />
            <Stat label="Overcharge recovered" value={pct(r.money_usd.identified_pct)} hint={`${money(r.money_usd.correctly_identified, "USD")} of ${money(r.money_usd.injected_overcharge, "USD")}`} />
            <Stat label="Routed to review" value={r.routed_to_review} hint={`${r.failures} extraction failures`} />
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500"><tr><th className="py-1 pr-3">Error type</th><th className="pr-3 text-right">TP</th><th className="pr-3 text-right">FN</th><th className="pr-3 text-right">FP</th><th className="pr-3 text-right">Recall</th><th className="text-right">Precision</th></tr></thead>
              <tbody>
                {Object.entries(r.detection.per_type).map(([k, v]) => (
                  <tr key={k} className="border-t border-slate-100">
                    <td className="py-1 pr-3">{ERROR_LABELS[k] ?? k}</td>
                    <td className="pr-3 text-right tabular-nums">{v.tp}</td><td className="pr-3 text-right tabular-nums">{v.fn}</td><td className="pr-3 text-right tabular-nums">{v.fp}</td>
                    <td className="pr-3 text-right tabular-nums">{pct(v.recall)}</td><td className="text-right tabular-nums">{pct(v.precision)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-slate-400">Cost ${r.cost.total_usd} total (${r.cost.per_invoice_usd}/invoice) · latency mean {r.latency_s.mean}s, p95 {r.latency_s.p95}s · generated {r.generated_at}</p>
        </Card>
      ))}
    </div>
  );
}
