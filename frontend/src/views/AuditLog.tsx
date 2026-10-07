import { useEffect, useState } from "react";
import { api, type AuditEvent } from "../api";
import { Badge, Button, Card } from "../ui";

export default function AuditLog() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [chain, setChain] = useState<{ ok: boolean; events: number; broken_at: number | null } | null>(null);
  const [type, setType] = useState("");
  const load = () => {
    api.audit(type || undefined).then(setEvents);
    api.verify().then(setChain);
  };
  useEffect(load, [type]);

  return (
    <Card
      title="Audit log"
      actions={
        <div className="flex items-center gap-2">
          {chain && (
            <Badge tone={chain.ok ? "green" : "red"}>
              {chain.ok ? `hash chain intact · ${chain.events} events` : `chain broken at event ${chain.broken_at}`}
            </Badge>
          )}
          <select value={type} onChange={(e) => setType(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1 text-sm">
            <option value="">all</option>
            {["invoice", "finding", "dispute", "contract", "agent"].map((t) => <option key={t}>{t}</option>)}
          </select>
          <Button variant="ghost" onClick={load}>Refresh</Button>
        </div>
      }
    >
      <p className="mb-3 text-xs text-slate-500">Append-only. Each event stores the SHA-256 of the previous one, so edits or deletions are detectable.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500">
            <tr><th className="py-1 pr-3">Time (UTC)</th><th className="pr-3">Entity</th><th className="pr-3">Action</th><th className="pr-3">Actor</th><th className="pr-3">Details</th><th>Hash</th></tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id} className="border-t border-slate-100 align-top">
                <td className="py-1.5 pr-3 whitespace-nowrap tabular-nums text-slate-500">{e.ts.replace("T", " ").slice(0, 19)}</td>
                <td className="pr-3 whitespace-nowrap">
                  {e.entity_type === "invoice" ? <a className="text-sky-700 hover:underline" href={`#/invoices/${e.entity_id}`}>invoice {e.entity_id}</a> : `${e.entity_type} ${e.entity_id}`}
                </td>
                <td className="pr-3 font-medium">{e.action}</td>
                <td className="pr-3">{e.actor}</td>
                <td className="pr-3 font-mono text-slate-500 break-all">{JSON.stringify(e.details).slice(0, 220)}</td>
                <td className="font-mono text-slate-400">{e.hash}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
