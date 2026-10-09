import { useEffect, useState, type FormEvent } from "react";
import { api, session, type SessionUser } from "../api";
import { Button, Icon, Logo } from "../ui";

const POINTS = [
  { icon: "shield", title: "Deterministic rule engine", text: "Rates, D&D days, FX and tax are checked in code. The LLM never decides." },
  { icon: "doc", title: "Evidence on every finding", text: "Each flag cites the invoice line and the contract clause it's based on." },
  { icon: "lock", title: "Human approval required", text: "Nothing is sent to a carrier until a signed-in reviewer approves it." },
];

export default function Login({ onSignedIn }: { onSignedIn: (u: SessionUser) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [demo, setDemo] = useState<{ email: string; password: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.authConfig().then((c) => setDemo(c.demo)).catch(() => setDemo(null));
  }, []);

  const signIn = async (e?: string, p?: string) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.login(e ?? email, p ?? password);
      session.set(r.token);
      onSignedIn(r.user);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    signIn();
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* brand panel */}
      <div className="relative hidden overflow-hidden bg-[#0b1020] px-12 py-12 text-white lg:flex lg:flex-col">
        <div className="pointer-events-none absolute -left-32 -top-32 h-[28rem] w-[28rem] rounded-full bg-indigo-600/30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 right-0 h-[26rem] w-[26rem] rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <Logo size={36} />
          <span className="text-lg font-semibold tracking-tight">Freight Invoice Auditor</span>
        </div>
        <div className="relative mt-auto max-w-lg">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">
            Stop overpaying carriers.
            <span className="block text-indigo-300">Audit every invoice line.</span>
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-slate-300">
            Extract charges from carrier PDFs, check every line against the contracted rate sheet, and send evidence-backed disputes after a reviewer signs off.
          </p>
          <ul className="mt-10 space-y-5">
            {POINTS.map((p) => (
              <li key={p.title} className="flex gap-3.5">
                <span className="mt-0.5 rounded-lg bg-white/10 p-2 text-indigo-200 ring-1 ring-white/10"><Icon name={p.icon} /></span>
                <span>
                  <span className="block text-sm font-medium text-white">{p.title}</span>
                  <span className="block text-sm text-slate-400">{p.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative mt-12 text-xs text-slate-500">Demo environment · all carriers, contracts and invoices are synthetic.</p>
      </div>

      {/* form */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <Logo />
            <span className="font-semibold tracking-tight">Freight Invoice Auditor</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Sign in</h2>
          <p className="mt-1 text-sm text-slate-500">Reviewer access to the audit workspace.</p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Work email</span>
              <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
                className="mt-1.5 block w-full rounded-lg border-0 px-3 py-2.5 text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600"
                placeholder="you@company.com" />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Password</span>
              <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="mt-1.5 block w-full rounded-lg border-0 px-3 py-2.5 text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-inset focus:ring-indigo-600" />
            </label>
            {err && (
              <div className="flex items-center gap-2 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-inset ring-rose-200">
                <Icon name="alert" /> {err}
              </div>
            )}
            <div className="pt-1 [&>button]:w-full">
              <Button type="submit" variant="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
            </div>
          </form>

          {demo && (
            <div className="mt-8 rounded-xl border border-indigo-100 bg-indigo-50/60 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-indigo-900"><Icon name="spark" /> Evaluator access</div>
              <p className="mt-1 text-xs leading-relaxed text-indigo-900/70">
                Demo reviewer account: <span className="font-mono">{demo.email}</span> / <span className="font-mono">{demo.password}</span>
              </p>
              <div className="mt-3 [&>button]:w-full">
                <Button variant="secondary" disabled={busy} onClick={() => { setEmail(demo.email); setPassword(demo.password); signIn(demo.email, demo.password); }}>
                  Continue as demo reviewer
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
