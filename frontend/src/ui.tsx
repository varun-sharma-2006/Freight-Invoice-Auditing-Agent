import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

// ---------------------------------------------------------------- brand
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#4f46e5" />
      <path d="M8 20.5 13.5 9h3L22 20.5" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10.5 16h9" stroke="#a5b4fc" strokeWidth="2.4" strokeLinecap="round" />
      <path d="m18.5 22.5 2.5 2.5 4.5-5" fill="none" stroke="#34d399" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ---------------------------------------------------------------- icons (inline, stroke-based)
const paths: Record<string, string> = {
  dashboard: "M3 13h8V3H3v10Zm0 8h8v-6H3v6Zm10 0h8V11h-8v10Zm0-18v6h8V3h-8Z",
  audit: "M9 12h6M9 16h6M9 8h6M5 3h14a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  upload: "M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  shield: "M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6l-8-3Zm-3 9 2 2 4-4",
  logout: "M15 17l5-5-5-5M20 12H9M12 21H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h7",
  check: "m5 12 5 5L20 7",
  x: "M6 6l12 12M18 6 6 18",
  doc: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8l-5-5Zm0 0v5h5",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  send: "M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z",
  arrow: "M15 18l-6-6 6-6",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z",
  alert: "M12 9v4m0 4h.01M10.3 3.9 2.2 18a2 2 0 0 0 1.7 3h16.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
};
export function Icon({ name, className = "h-4 w-4" }: { name: keyof typeof paths | string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name] ?? ""} />
    </svg>
  );
}

// ---------------------------------------------------------------- primitives
type Tone = "slate" | "green" | "amber" | "red" | "blue" | "violet" | "indigo";
export function Badge({ tone = "slate", children, dot }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  const tones: Record<Tone, string> = {
    slate: "bg-slate-100 text-slate-700 ring-slate-200",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    red: "bg-rose-50 text-rose-700 ring-rose-200",
    blue: "bg-sky-50 text-sky-700 ring-sky-200",
    violet: "bg-violet-50 text-violet-700 ring-violet-200",
    indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  };
  const dots: Record<Tone, string> = {
    slate: "bg-slate-400", green: "bg-emerald-500", amber: "bg-amber-500", red: "bg-rose-500",
    blue: "bg-sky-500", violet: "bg-violet-500", indigo: "bg-indigo-500",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${tones[tone]}`}>
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${dots[tone]}`} />}
      {children}
    </span>
  );
}

const STATUS: Record<string, [Tone, string]> = {
  audited: ["green", "Audited"],
  needs_review: ["amber", "Needs review"],
  processing: ["blue", "Processing"],
  failed: ["red", "Failed"],
  draft: ["blue", "Draft"],
  approved: ["violet", "Approved"],
  rejected: ["red", "Rejected"],
  sent: ["green", "Sent"],
};
export function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-slate-300">—</span>;
  const [tone, label] = STATUS[status] ?? ["slate", status];
  return <Badge tone={tone} dot>{label}</Badge>;
}

export function Card({ title, subtitle, actions, children, className = "", padded = true }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean;
}) {
  return (
    <section className={`rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_-12px_rgba(15,23,42,0.08)] ${className}`}>
      {title && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={padded ? "p-5" : ""}>{children}</div>
    </section>
  );
}

export function Button({ children, onClick, variant = "secondary", disabled, title, type = "button", size = "md" }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "danger" | "ghost" | "success";
  disabled?: boolean; title?: string; type?: "button" | "submit"; size?: "sm" | "md";
}) {
  const v = {
    primary: "bg-indigo-600 text-white shadow-sm shadow-indigo-600/20 hover:bg-indigo-500 focus-visible:outline-indigo-600",
    success: "bg-emerald-600 text-white shadow-sm shadow-emerald-600/20 hover:bg-emerald-500 focus-visible:outline-emerald-600",
    secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-200 hover:bg-slate-50 hover:ring-slate-300",
    danger: "bg-white text-rose-700 ring-1 ring-inset ring-rose-200 hover:bg-rose-50",
    ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
  }[variant];
  const sz = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm";
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-40 ${sz} ${v}`}>
      {children}
    </button>
  );
}

export function Kpi({ label, value, hint, icon, tone = "indigo" }: {
  label: string; value: ReactNode; hint?: ReactNode; icon?: string; tone?: "indigo" | "rose" | "amber" | "emerald";
}) {
  const t = {
    indigo: "bg-indigo-50 text-indigo-600", rose: "bg-rose-50 text-rose-600",
    amber: "bg-amber-50 text-amber-600", emerald: "bg-emerald-50 text-emerald-600",
  }[tone];
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex items-start justify-between">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
        {icon && <div className={`rounded-lg p-1.5 ${t}`}><Icon name={icon} /></div>}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums text-slate-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

// Back-compat: compact stat used inside cards.
export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-inset ring-slate-100">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{value}</div>
      {hint && <div className="text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function EmptyState({ icon = "doc", title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 rounded-xl bg-slate-100 p-3 text-slate-500"><Icon name={icon} className="h-6 w-6" /></div>
      <div className="text-sm font-medium text-slate-900">{title}</div>
      {children && <div className="mt-1 max-w-sm text-sm text-slate-500">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- toasts
type Toast = { id: number; tone: "ok" | "err"; text: string };
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[min(92vw,360px)] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={`toast-in pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-white px-4 py-3 text-sm shadow-lg shadow-slate-900/10 ${t.tone === "ok" ? "border-emerald-200" : "border-rose-200"}`}>
            <span className={`mt-0.5 rounded-full p-0.5 ${t.tone === "ok" ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
              <Icon name={t.tone === "ok" ? "check" : "x"} className="h-3.5 w-3.5" />
            </span>
            <span className="text-slate-700">{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
