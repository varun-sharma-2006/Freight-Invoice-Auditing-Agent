import { useEffect, useState } from "react";
import { api, onUnauthorized, session, type SessionUser } from "./api";
import { Icon, Logo, Skeleton, ToastProvider } from "./ui";
import Login from "./views/Login";
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

const TITLES: Record<Route["page"], [string, string]> = {
  invoices: ["Invoices", "Upload carrier invoices and review audit results"],
  invoice: ["Invoice review", "Verify findings against the source document"],
  audit: ["Audit trail", "Every action, tamper-evident"],
  eval: ["Evaluation", "Measured accuracy on held-out synthetic data"],
};

export default function App() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [checking, setChecking] = useState(!!session.token);

  useEffect(() => {
    if (session.token) {
      api.me().then(setUser).catch(() => session.set(null)).finally(() => setChecking(false));
    }
    const out = () => setUser(null);
    onUnauthorized.addEventListener("logout", out);
    return () => onUnauthorized.removeEventListener("logout", out);
  }, []);

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="w-64 space-y-3"><Skeleton className="h-8 w-8" /><Skeleton /><Skeleton className="h-4 w-2/3" /></div>
      </div>
    );
  }
  return (
    <ToastProvider>
      {user ? <Shell user={user} onSignOut={() => { session.set(null); setUser(null); location.hash = "#/"; }} /> : <Login onSignedIn={setUser} />}
    </ToastProvider>
  );
}

function Shell({ user, onSignOut }: { user: SessionUser; onSignOut: () => void }) {
  const [route, setRoute] = useState<Route>(parse(location.hash));
  const [health, setHealth] = useState<{ llm_configured: boolean; model: string } | null>(null);

  useEffect(() => {
    const on = () => setRoute(parse(location.hash));
    addEventListener("hashchange", on);
    api.health().then(setHealth).catch(() => setHealth(null));
    return () => removeEventListener("hashchange", on);
  }, []);

  const nav = [
    { href: "#/", label: "Invoices", icon: "dashboard", active: route.page === "invoices" || route.page === "invoice" },
    { href: "#/audit", label: "Audit trail", icon: "audit", active: route.page === "audit" },
    { href: "#/eval", label: "Evaluation", icon: "chart", active: route.page === "eval" },
  ];
  const [title, subtitle] = TITLES[route.page];
  const initials = user.name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className="min-h-screen lg:pl-64">
      {/* sidebar */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col bg-[#0b1020] lg:flex">
        <div className="flex items-center gap-3 px-6 py-6">
          <Logo />
          <div>
            <div className="text-sm font-semibold tracking-tight text-white">Freight Invoice</div>
            <div className="text-xs text-slate-400">Auditor</div>
          </div>
        </div>
        <nav className="mt-2 flex-1 space-y-1 px-3">
          {nav.map((n) => (
            <a key={n.href} href={n.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${n.active ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5 hover:text-slate-200"}`}>
              <Icon name={n.icon} /> {n.label}
            </a>
          ))}
        </nav>
        <div className="mx-3 mb-3 rounded-xl bg-white/5 p-3 ring-1 ring-white/10">
          <div className="flex items-center gap-2 text-xs text-slate-300">
            <span className={`h-2 w-2 rounded-full ${health ? "bg-emerald-400" : "bg-rose-400"}`} />
            {health ? "API connected" : "API unreachable"}
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Extraction: {health ? (health.llm_configured ? health.model : "offline parser") : "–"}
          </div>
        </div>
        <div className="flex items-center gap-3 border-t border-white/10 px-4 py-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-500/20 text-xs font-semibold text-indigo-200 ring-1 ring-indigo-400/30">{initials}</div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-white">{user.name}</div>
            <div className="truncate text-[11px] capitalize text-slate-400">{user.role}</div>
          </div>
          <button onClick={onSignOut} title="Sign out" className="rounded-md p-1.5 text-slate-400 hover:bg-white/10 hover:text-white">
            <Icon name="logout" />
          </button>
        </div>
      </aside>

      {/* mobile top bar */}
      <div className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
        <Logo size={28} />
        <nav className="flex flex-1 gap-1 overflow-x-auto">
          {nav.map((n) => (
            <a key={n.href} href={n.href} className={`whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm ${n.active ? "bg-slate-900 text-white" : "text-slate-600"}`}>{n.label}</a>
          ))}
        </nav>
        <button onClick={onSignOut} title="Sign out" className="rounded-md p-1.5 text-slate-500"><Icon name="logout" /></button>
      </div>

      <main className="mx-auto max-w-[1400px] px-4 py-8 sm:px-8">
        {route.page !== "invoice" && (
          <div className="mb-8">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
            <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
          </div>
        )}
        {route.page === "invoices" && <InvoiceList />}
        {route.page === "invoice" && <InvoiceReview id={route.id} reviewer={user.name} />}
        {route.page === "audit" && <AuditLog />}
        {route.page === "eval" && <EvalResults />}
        <footer className="mt-12 border-t border-slate-200 pt-6 text-xs text-slate-400">
          Synthetic demo data. The rule engine decides, the LLM only reads and writes, and nothing is sent without reviewer approval.
        </footer>
      </main>
    </div>
  );
}
