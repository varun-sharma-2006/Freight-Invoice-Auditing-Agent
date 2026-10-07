import type { ReactNode } from "react";

export function Badge({ tone = "slate", children }: { tone?: "slate" | "green" | "amber" | "red" | "blue" | "violet"; children: ReactNode }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700 ring-slate-200",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    red: "bg-rose-50 text-rose-700 ring-rose-200",
    blue: "bg-sky-50 text-sky-700 ring-sky-200",
    violet: "bg-violet-50 text-violet-700 ring-violet-200",
  };
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-slate-400">–</span>;
  const tone = ({ audited: "green", needs_review: "amber", draft: "blue", approved: "violet", sent: "green", rejected: "red", failed: "red" } as const)[
    status as "audited"
  ] ?? "slate";
  return <Badge tone={tone}>{status.replace("_", " ")}</Badge>;
}

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Button({
  children,
  onClick,
  variant = "secondary",
  disabled,
  title,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
  title?: string;
  type?: "button" | "submit";
}) {
  const v = {
    primary: "bg-slate-900 text-white hover:bg-slate-700",
    secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50",
    danger: "bg-white text-rose-700 ring-1 ring-inset ring-rose-300 hover:bg-rose-50",
    ghost: "text-slate-600 hover:bg-slate-100",
  }[variant];
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${v}`}>
      {children}
    </button>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-slate-900">{value}</div>
      {hint && <div className="text-xs text-slate-400">{hint}</div>}
    </div>
  );
}
