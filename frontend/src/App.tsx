import { useEffect, useState } from "react";
import { api } from "./api";
import InvoiceList from "./views/InvoiceList";
import InvoiceReview from "./views/InvoiceReview";
import AuditLog from "./views/AuditLog";
import EvalResults from "./views/EvalResults";

type Route = { page: "invoices" } | { page: "invoice"; id: number } | { page: "audit" } | { page: "eval" };

function parse(hash: string): Route {
  const m = hash.match(/^#\/invoices\/(\d+)/);
  if (m) return { page: "invoice", id: Number(m[1]) };
  if (hash.startsWith("#/audit")) return { page: "audit" };
  if (hash.startsWith("#/eval")) return { page: "eval" };
  return { page: "invoices" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(parse(location.hash));
  const [health, setHealth] = useState<{ llm_configured: boolean; model: string } | null>(null);
  const [reviewer, setReviewer] = useState(() => {
    try {
      return localStorage.getItem("reviewer") ?? "";
    } catch {
      return "";
    }
  });

  useEffect(() => {
    const on = () => setRoute(parse(location.hash));
    addEventListener("hashchange", on);
    api.health().then(setHealth).catch(() => setHealth(null));
    return () => removeEventListener("hashchange", on);
  }, []);

  const saveReviewer = (v: string) => {
    setReviewer(v);
    try {
      localStorage.setItem("reviewer", v);
    } catch {
      /* storage unavailable */
    }
  };

  const nav = [
    ["#/", "Invoices", route.page === "invoices" || route.page === "invoice"],
    ["#/audit", "Audit log", route.page === "audit"],
    ["#/eval", "Eval results", route.page === "eval"],
  ] as const;

  return (
    <div className="min-h-screen text-slate-800">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <a href="#/" className="font-semibold tracking-tight text-slate-900">
            Freight Invoice Auditor
          </a>
          <nav className="flex gap-1">
            {nav.map(([href, label, active]) => (
              <a key={href} href={href} className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                {label}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs text-slate-500">
            <span title="Extraction and drafting backend">
              LLM: {health ? (health.llm_configured ? health.model : "off (offline mode)") : "backend unreachable"}
            </span>
            <label className="flex items-center gap-1.5">
              Reviewer
              <input value={reviewer} onChange={(e) => saveReviewer(e.target.value)} placeholder="your name"
                className="w-32 rounded-md border border-slate-300 px-2 py-1 text-sm text-slate-800" />
            </label>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        {route.page === "invoices" && <InvoiceList />}
        {route.page === "invoice" && <InvoiceReview id={route.id} reviewer={reviewer} />}
        {route.page === "audit" && <AuditLog />}
        {route.page === "eval" && <EvalResults />}
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-slate-400">
        Demo data is synthetic. Rule engine decides; the LLM only reads and writes. Nothing is sent without reviewer approval.
      </footer>
    </div>
  );
}
