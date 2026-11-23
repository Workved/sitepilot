import { CheckCircle2, FlaskConical, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button, Field, Input } from "../../components/ui";
import { BrandMark } from "../../components/layout/BrandMark";

function BrandPanel() {
  return <aside className="relative flex flex-col overflow-hidden border-b border-line bg-slate-50 p-7 sm:border-b-0 sm:border-r sm:p-10 lg:p-12">
    <div className="flex items-center gap-3"><BrandMark className="size-10"/><span><strong className="block text-lg font-medium tracking-[-0.01em] text-slate-950">Workved SiteOps</strong><small className="text-[13px] text-slate-500">Execution intelligence</small></span></div>
    <div className="my-auto py-10">
      <h1 className="max-w-md text-4xl font-light leading-[1.05] tracking-[-0.035em] text-slate-950 sm:text-[52px]">Every site decision, under control.</h1>
      <p className="mt-5 max-w-sm text-[15px] leading-7 text-slate-500">Plan fit-outs from approved templates, drive daily execution, and keep vendors and approvals on schedule in one workspace.</p>
      <div aria-hidden="true" className="mt-10 hidden max-w-sm items-end gap-1.5 sm:flex">
        {[38, 52, 46, 61, 34, 22, 28, 57, 66, 72, 64, 80].map((height, index) => <span key={index} className="flex-1 rounded-t-[4px]" style={{ height: `${height * 1.1}px`, background: index > 3 && index < 7 ? "var(--color-behind)" : "var(--color-blue-600)", opacity: index > 3 && index < 7 ? 1 : 0.35 + index * 0.05 }}/>)}
      </div>
    </div>
    <div className="flex items-center gap-2 text-[13px] text-slate-500"><ShieldCheck size={16}/>Authentication protected by Supabase</div>
  </aside>;
}

export function AuthShell({ eyebrow, title, subtitle, children }) {
  return <main className="min-h-screen bg-canvas p-0 sm:grid sm:place-items-center sm:p-6">
    <section className="grid min-h-screen w-full overflow-hidden bg-white sm:min-h-0 sm:max-w-6xl sm:grid-cols-[.95fr_1.05fr] sm:rounded-[28px] sm:border sm:border-slate-200">
      <BrandPanel/>
      <div className="grid content-center px-5 py-9 sm:px-10 lg:px-16 lg:py-14"><div className="mx-auto w-full max-w-md">{eyebrow && <p className="text-sm text-slate-500">{eyebrow}</p>}<h2 className="mt-1 text-3xl font-normal tracking-[-0.025em] text-slate-950 sm:text-[34px]">{title}</h2><p className="mt-3 text-sm leading-6 text-slate-500">{subtitle}</p>{children}</div></div>
    </section>
  </main>;
}

export function Notice({ error, message }) {
  if (error) return <div role="alert" className="rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>;
  if (message) return <div className="flex items-start gap-2 rounded-2xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"><CheckCircle2 className="mt-0.5 shrink-0" size={17}/>{message}</div>;
  return null;
}

function GoogleGlyph() {
  return <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.9c1.7-1.56 2.7-3.87 2.7-6.62Z"/><path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.9-2.26c-.8.54-1.84.86-3.06.86-2.35 0-4.34-1.59-5.05-3.72H.96v2.33A9 9 0 0 0 9 18Z"/><path fill="#FBBC05" d="M3.95 10.7A5.4 5.4 0 0 1 3.67 9c0-.59.1-1.17.28-1.7V4.97H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.03l2.99-2.33Z"/><path fill="#EA4335" d="M9 3.58c1.32 0 2.51.46 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.97l2.99 2.33C4.66 5.17 6.65 3.58 9 3.58Z"/></svg>;
}

export function GoogleButton({ onClick, children = "Continue with Google" }) {
  return <button type="button" onClick={onClick} className="inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white px-5 text-sm font-medium text-slate-800 transition hover:border-slate-300 hover:bg-slate-50"><GoogleGlyph/>{children}</button>;
}

// Local-dev-only: mints a real session for any local test account (or any
// typed email, to try a first-time-login/new-invite scenario) without
// Google, via backend/app/routes/auth.py's dev_login. Only rendered at all
// when the backend reports it's actually reachable - see App() in
// main.jsx - so this is invisible against a real deployment.
const DEV_ACCOUNTS = [
  { label: "Super Admin", email: "superadmin@siteops.local" },
  { label: "Admin", email: "interior.ops@siteops.local" },
  { label: "Project Manager", email: "prachitk@siteops.local" },
  { label: "Supervisor", email: "deepaks@sitesops.local" },
  { label: "Internal Employee", email: "preetig@sitesops.local" },
];

function DevLoginPanel({ onDevLogin }) {
  const [customEmail, setCustomEmail] = useState("");
  const [busy, setBusy] = useState("");

  async function signInAs(email) {
    setBusy(email);
    try { await onDevLogin(email); } finally { setBusy(""); }
  }

  return <div className="mt-6 rounded-2xl border-2 border-dashed border-amber-300 bg-amber-50 p-4">
    <div className="flex items-center gap-2 text-xs font-medium text-amber-800"><FlaskConical size={14}/> Local dev sign-in</div>
    <p className="mt-1 text-xs text-amber-700">Skips Google - only available against your local Supabase stack, never in production.</p>
    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
      {DEV_ACCOUNTS.map(account => <button
        key={account.email}
        type="button"
        onClick={() => signInAs(account.email)}
        disabled={Boolean(busy)}
        className="rounded-lg border border-amber-300 bg-white px-2.5 py-2 text-xs font-bold text-amber-900 transition hover:bg-amber-100 disabled:opacity-50"
      >{busy === account.email ? "Signing in…" : account.label}</button>)}
    </div>
    <form onSubmit={event => { event.preventDefault(); if (customEmail.trim()) signInAs(customEmail.trim()); }} className="mt-3 flex gap-2">
      <input
        type="email"
        value={customEmail}
        onChange={event => setCustomEmail(event.target.value)}
        placeholder="or sign in as any email (test a new invite)"
        className="min-h-9 flex-1 rounded-lg border border-amber-300 bg-white px-2.5 text-xs outline-none focus:border-amber-500"
      />
      <button type="submit" disabled={!customEmail.trim() || Boolean(busy)} className="rounded-lg bg-amber-600 px-3 text-xs font-bold text-white transition hover:bg-amber-700 disabled:opacity-50">Go</button>
    </form>
  </div>;
}

function PasswordForm({ onPassword }) {
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    const { email, password } = Object.fromEntries(new FormData(event.currentTarget));
    if (!email.trim() || !password) return;
    setBusy(true);
    try {
      await onPassword(email.trim(), password);
    } finally {
      setBusy(false);
    }
  }
  return <form onSubmit={submit} className="grid gap-3">
    <Field label="Email" htmlFor="login-email"><Input id="login-email" name="email" type="email" autoComplete="username" placeholder="name@company.com" required/></Field>
    <Field label="Password" htmlFor="login-password"><Input id="login-password" name="password" type="password" autoComplete="current-password" required/></Field>
    <Button type="submit" size="lg" loading={busy}>Sign in</Button>
  </form>;
}

export function LoginPage({ onGoogle, onPassword, error, message, devLoginEnabled = false, onDevLogin }) {
  return <AuthShell eyebrow="Welcome back" title="Sign in to SiteOps" subtitle="Use the Google account or the email and password your administrator set up for you.">
    <div className="mt-8 grid gap-5">
      <GoogleButton onClick={onGoogle}/>
      {onPassword && <>
        <div className="flex items-center gap-3 text-xs font-bold text-slate-500"><span className="h-px flex-1 bg-slate-200"/>or<span className="h-px flex-1 bg-slate-200"/></div>
        <PasswordForm onPassword={onPassword}/>
      </>}
      <Notice error={error} message={message}/>
      <p className="text-center text-[13px] leading-5 text-slate-500">New here? Ask your Admin or Super Admin to add you in User Management - you'll be able to sign in the moment they do.</p>
      {devLoginEnabled && <DevLoginPanel onDevLogin={onDevLogin}/>}
    </div>
  </AuthShell>;
}
