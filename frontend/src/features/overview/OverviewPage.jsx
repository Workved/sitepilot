import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, ChevronDown, Search, X } from "lucide-react";
import { projectsApi } from "../../api/projectsApi";
import { Alert, EmptyState, LoadingSpinner } from "../../components/ui";
import { cn } from "../../utils/cn";
import { formatDateShort, initials } from "../../utils/format";
import { BEHIND_TOLERANCE, plannedPercent } from "../../utils/schedule";

export { plannedPercent };

/*
 * Overview: the home screen, built only from read models every role can
 * already reach - /projects/timeline (per-project dates, progress, overdue,
 * blocked, approvals, health) and /projects/attention (items waiting on the
 * viewer). Nothing here is invented: where a number cannot be derived from
 * those two payloads, the panel does not show it.
 */

const HEALTH = {
  on_track: { label: "On track", pill: "bg-emerald-50 text-emerald-800", tile: "bg-emerald-50 text-emerald-800" },
  at_risk: { label: "At risk", pill: "bg-orange-50 text-orange-800", tile: "bg-orange-50 text-orange-800" },
  delayed: { label: "Delayed", pill: "bg-rose-50 text-rose-800", tile: "bg-rose-50 text-rose-800" },
  completed: { label: "Completed", pill: "bg-blue-50 text-blue-800", tile: "bg-blue-50 text-blue-800" },
};
const HEALTH_TABS = [["all", "All"], ["at_risk", "At risk"], ["delayed", "Delayed"]];
const RUNNING = new Set(["active", "on_hold"]);
// The chart and the handover list hold a fixed number of rows so the page
// keeps its shape whether there are 3 projects or 300; the rest live in
// the "See all" panel.
export const CHART_LIMIT = 6;
const HANDOVER_LIMIT = 5;

// One answer to "is this project OK?", used by every panel on the page.
// The backend's health covers late forecasts, overdue and blocked work and
// approvals at risk; it cannot see a project whose tasks are all on time
// but whose completed work trails the calendar. That case is "at risk"
// here too, so the ring, the summary and the cards never disagree.
export function standingOf(row, planned) {
  if (row.status === "completed" || row.health === "completed") return "completed";
  if (row.health === "delayed") return "delayed";
  if (row.health === "at_risk") return "at_risk";
  if (planned != null && planned - row.progress_pct > BEHIND_TOLERANCE) return "at_risk";
  return "on_track";
}

const SORTS = [
  ["behind", "Most behind"],
  ["progress", "Least progress"],
  ["handover", "Handover soonest"],
];
const gapOf = row => row.planned - row.progress_pct;
const handoverTime = row => (row.target_handover_date ? new Date(`${row.target_handover_date}T00:00:00`).getTime() : Infinity);
export function sortRows(rows, sort) {
  const list = [...rows];
  if (sort === "progress") return list.sort((a, b) => a.progress_pct - b.progress_pct || a.name.localeCompare(b.name));
  if (sort === "handover") return list.sort((a, b) => handoverTime(a) - handoverTime(b) || a.name.localeCompare(b.name));
  return list.sort((a, b) => gapOf(b) - gapOf(a) || a.name.localeCompare(b.name));
}
function greeting(now = new Date()) {
  const hour = now.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function Panel({ title, id, action, className, children }) {
  return <section aria-labelledby={id} className={cn("flex min-w-0 flex-col gap-4 rounded-[22px] border border-line bg-white p-5 sm:p-6", className)}>
    {title && <div className="flex items-center justify-between gap-3">
      <h2 id={id} className="text-[17px] font-medium text-slate-950">{title}</h2>
      {action}
    </div>}
    {children}
  </section>;
}

function Legend({ items }) {
  return <div className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-slate-500">
    {items.map(([label, color]) => <span key={label} className="flex items-center gap-2"><span className="size-2.5 rounded-[3px]" style={{ background: color }} />{label}</span>)}
  </div>;
}

const ROW_HEIGHT = 48;

function ProgressRow({ row, onOpenProject }) {
  return <li>
    <button type="button" onClick={() => onOpenProject?.(row.code)} aria-label={`${row.name}: planned ${row.planned}%, completed ${row.progress_pct}%`} style={{ minHeight: ROW_HEIGHT }} className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 rounded-xl px-2 py-1.5 text-left transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 md:grid-cols-[minmax(120px,190px)_minmax(0,1fr)_9.5rem]">
      <span className="min-w-0"><span className="block truncate text-sm text-slate-950">{row.name}</span><span className="block truncate text-xs text-slate-500">{row.code}</span></span>
      <span className="relative order-3 col-span-2 block h-2.5 rounded-full bg-slate-100 md:order-none md:col-span-1" aria-hidden="true">
        <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${row.planned}%`, background: row.behind ? "var(--color-behind-soft)" : "var(--color-blue-100)" }} />
        {row.progress_pct > 0 && <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(row.progress_pct, 2)}%`, background: row.behind ? "var(--color-behind)" : "var(--color-blue-600)" }} />}
        <span className="absolute -top-1 h-[18px] w-0.5 rounded bg-slate-950" style={{ left: `calc(${row.planned}% - 1px)` }} />
      </span>
      <span className="whitespace-nowrap text-right text-xs tabular-nums text-slate-500"><span className="text-slate-950">{row.progress_pct}% done</span>, {row.planned}% time</span>
    </button>
  </li>;
}

function SortMenu({ sort, onChange }) {
  const [open, setOpen] = useState(false);
  const holder = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = event => { if (!holder.current?.contains(event.target)) setOpen(false); };
    const onKey = event => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const label = SORTS.find(([key]) => key === sort)?.[1];
  return <div ref={holder} className="relative">
    <button type="button" onClick={() => setOpen(value => !value)} aria-haspopup="true" aria-expanded={open} aria-label={`Sorted by ${label}. Change sort`} className="flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white pl-3 pr-2 text-[13px] text-slate-800 hover:border-slate-300">
      {label}<ChevronDown size={15} className="text-slate-500" aria-hidden="true" />
    </button>
    {open && <div role="menu" className="absolute right-0 top-[calc(100%+6px)] z-30 w-48 rounded-xl border border-line bg-white p-1 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      {SORTS.map(([key, text]) => <button key={key} type="button" role="menuitemradio" aria-checked={sort === key} onClick={() => { onChange(key); setOpen(false); }} className={cn("block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-50", sort === key ? "text-slate-950" : "text-slate-600")}>{text}</button>)}
    </div>}
  </div>;
}

// Every running project, searchable, in a side panel - the chart only ever
// shows the top few, so this is where a large portfolio is browsed.
function AllProjectsPanel({ rows, initialSort, onOpenProject, onClose }) {
  const [sort, setSort] = useState(initialSort);
  const [query, setQuery] = useState("");
  const inputRef = useRef(null);
  // Held in a ref so the mount-only effect below always calls the latest
  // handler without re-running (and re-locking scroll) on every render.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    inputRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = event => { if (event.key === "Escape") closeRef.current(); };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previous; document.removeEventListener("keydown", onKey); };
  }, []);
  const term = query.trim().toLowerCase();
  const shown = sortRows(rows, sort).filter(row => !term || [row.name, row.code, row.client_name, row.pm_name].some(value => String(value || "").toLowerCase().includes(term)));
  return createPortal(<div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <section role="dialog" aria-modal="true" aria-label="All running projects" className="flex h-full w-full max-w-[620px] flex-col bg-white shadow-[-16px_0_50px_rgba(21,23,26,.14)]">
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div><h2 className="text-lg font-normal text-slate-950">All running projects</h2><p className="text-[13px] text-slate-500">{rows.length} projects, time used against work done</p></div>
        <button type="button" onClick={onClose} aria-label="Close panel" className="grid size-10 place-items-center rounded-xl border border-slate-200 text-slate-700 hover:bg-slate-50"><X size={18} /></button>
      </header>
      <div className="flex items-center gap-2 border-b border-line px-5 py-3">
        <label className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 focus-within:border-blue-600 focus-within:bg-white">
          <Search size={15} className="text-slate-500" aria-hidden="true" />
          <input ref={inputRef} value={query} onChange={event => setQuery(event.target.value)} placeholder="Search name, code, client or PM" aria-label="Search running projects" className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400" />
        </label>
        <SortMenu sort={sort} onChange={setSort} />
      </div>
      <ul className="so-scroll min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {shown.map(row => <ProgressRow key={row.project_id} row={row} onOpenProject={code => { onClose(); onOpenProject?.(code); }} />)}
        {shown.length === 0 && <li className="px-2 py-10 text-center text-sm text-slate-500">No running project matches “{query}”.</li>}
      </ul>
    </section>
  </div>, document.body);
}

function ProgressChart({ rows, onOpenProject }) {
  const [sort, setSort] = useState("behind");
  const [allOpen, setAllOpen] = useState(false);
  const totals = rows.reduce((acc, row) => ({ done: acc.done + row.completed_count, all: acc.all + row.task_count }), { done: 0, all: 0 });
  const overall = totals.all ? Math.round(totals.done / totals.all * 100) : 0;
  const behindCount = rows.filter(row => row.behind).length;
  const shown = sortRows(rows, sort).slice(0, CHART_LIMIT);

  return <Panel id="ov-progress" className="ov-chart">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="grid gap-1.5">
        <h2 id="ov-progress" className="text-[17px] font-medium text-slate-950">Progress against plan</h2>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-[42px] font-light leading-none tracking-[-0.03em] text-slate-950">{overall}%</span>
          <span className="text-sm text-slate-500">{totals.done.toLocaleString()} of {totals.all.toLocaleString()} tasks complete across {rows.length} running {rows.length === 1 ? "project" : "projects"}</span>
          {behindCount > 0 && <span className="rounded-md bg-orange-50 px-2 py-0.5 text-xs text-orange-800">{behindCount} behind plan</span>}
        </div>
      </div>
      {rows.length > 1 && <SortMenu sort={sort} onChange={setSort} />}
    </div>
    <Legend items={[["Completed", "var(--color-blue-600)"], ["Time elapsed", "var(--color-blue-100)"], ["Behind plan", "var(--color-behind)"], ["Today", "var(--color-slate-950)"]]} />

    {/* Space for CHART_LIMIT rows is always reserved, so the card - and
        everything laid out after it - holds still as projects come and go. */}
    <div style={{ minHeight: CHART_LIMIT * (ROW_HEIGHT + 2) }}>
      {rows.length === 0
        ? <EmptyState className="h-full" title="No running projects" description="Projects show here once they are activated and have dated tasks." />
        : <ul className="grid gap-0.5">{shown.map(row => <ProgressRow key={row.project_id} row={row} onOpenProject={onOpenProject} />)}</ul>}
    </div>

    {rows.length > 0 && <div className="mt-auto flex items-center justify-between gap-3 border-t border-line pt-3 text-[13px]">
      <span className="text-slate-500">Showing {shown.length} of {rows.length}</span>
      {rows.length > CHART_LIMIT
        ? <button type="button" onClick={() => setAllOpen(true)} className="text-blue-700 hover:text-blue-900">See all {rows.length} projects</button>
        : <span className="text-slate-400">All running projects shown</span>}
    </div>}

    {allOpen && <AllProjectsPanel rows={rows} initialSort={sort} onOpenProject={onOpenProject} onClose={() => setAllOpen(false)} />}
  </Panel>;
}

function Ring({ value, total }) {
  const radius = 64;
  const circumference = 2 * Math.PI * radius;
  const share = total ? value / total : 0;
  return <div className="relative size-[168px]">
    <svg viewBox="0 0 168 168" className="size-full" role="img" aria-label={`${value} of ${total} running projects on track`}>
      <circle cx="84" cy="84" r="80" fill="none" stroke="var(--color-line)" strokeWidth="1" />
      <circle cx="84" cy="84" r={radius} fill="none" stroke="var(--color-slate-200)" strokeWidth="12" />
      {share > 0 && <circle cx="84" cy="84" r={radius} fill="none" stroke="var(--color-blue-600)" strokeWidth="12" strokeLinecap="round" strokeDasharray={`${circumference * share} ${circumference}`} transform="rotate(-90 84 84)" />}
    </svg>
    <div className="absolute inset-0 grid place-content-center text-center">
      <span className="text-[36px] font-light leading-none tracking-[-0.03em] text-slate-950">{value}<span className="text-slate-400">/{total}</span></span>
      <span className="mt-1 text-xs text-slate-500">on track</span>
    </div>
  </div>;
}

const SEVERITY_DOT = { critical: "bg-rose-600", warning: "bg-behind", decision: "bg-gate" };
const SEVERITY_ORDER = { critical: 0, warning: 1, decision: 2 };

function TodayPanel({ user, rows, attention, tabs, onOpenProject, onTabChange }) {
  const onTrack = rows.filter(row => row.standing === "on_track").length;
  const late = rows.filter(row => row.standing === "delayed");
  const atRisk = rows.filter(row => row.standing === "at_risk");
  const decisions = attention.filter(item => item.group === "Needs a decision");
  const runningLate = attention.filter(item => item.group === "Running late");
  const top = [...attention].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3)).slice(0, 3);
  const canOpenExecution = tabs?.some(([key]) => key === "execution");
  const firstName = (user?.name || "").split(" ")[0];

  const sentences = [];
  if (late.length) sentences.push(`${late.length} ${late.length === 1 ? "project is" : "projects are"} running late${late.length <= 2 ? `: ${late.map(row => row.name).join(" and ")}` : ""}.`);
  if (atRisk.length) sentences.push(`${atRisk.length} ${atRisk.length === 1 ? "project is" : "projects are"} at risk${atRisk.length <= 2 ? `: ${atRisk.map(row => row.name).join(" and ")}` : ""}.`);
  if (decisions.length) sentences.push(`${decisions.length} ${decisions.length === 1 ? "decision is" : "decisions are"} waiting on you.`);
  if (!sentences.length) sentences.push(rows.length ? "Every running project is moving to plan and nothing is waiting on you." : "No running projects yet. Activated projects and their alerts show up here.");

  return <aside aria-labelledby="ov-today" className="ov-today flex min-w-0 flex-col gap-4 rounded-[22px] border border-line bg-slate-50 p-5 sm:p-6">
    <div className="flex flex-col items-center gap-1 pt-1 text-center">
      <div className="mb-1"><Ring value={onTrack} total={rows.length} /></div>
      <p className="text-sm text-slate-500">{greeting()}{firstName ? `, ${firstName}` : ""}</p>
      <h2 id="ov-today" className="text-[22px] font-normal tracking-[-0.01em] text-slate-950">Here is what needs you today</h2>
    </div>

    <div className="grid gap-3 rounded-2xl border border-line bg-white p-4">
      <h3 className="text-sm font-medium text-slate-950">Today's summary</h3>
      <p className="text-[13px] leading-relaxed text-slate-600">{sentences.join(" ")}</p>
      {attention.length > top.length && <p className="text-xs text-slate-500">{attention.length - top.length} more in Projects, Needs attention</p>}
      {top.length > 0 && <ul className="grid gap-0.5">
        {top.map(item => <li key={item.id}>
          <button type="button" onClick={() => onOpenProject?.(item.project_code, item.pane)} className="flex w-full items-start gap-2.5 rounded-xl px-1.5 py-1.5 text-left text-[13px] hover:bg-slate-50">
            <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", SEVERITY_DOT[item.severity] || "bg-slate-400")} />
            <span className="min-w-0"><span className="block truncate text-slate-950">{item.title}</span><span className="block truncate text-slate-500">{[item.subtitle, item.due_label].filter(Boolean).join(", ").replaceAll(" · ", ", ")}</span></span>
          </button>
        </li>)}
      </ul>}
    </div>

    <div className="grid grid-cols-2 gap-2.5">
      <div className="rounded-2xl border border-line bg-white p-3.5">
        <div className="flex items-center gap-2"><span className="text-[26px] font-light leading-none">{decisions.length}</span><span className="rounded-md bg-violet-50 px-2 py-0.5 text-xs text-violet-800">Decisions</span></div>
        <p className="mt-1.5 text-[13px] text-slate-500">Waiting on you</p>
      </div>
      <div className="rounded-2xl border border-line bg-white p-3.5">
        <div className="flex items-center gap-2"><span className="text-[26px] font-light leading-none">{runningLate.length}</span><span className="rounded-md bg-orange-50 px-2 py-0.5 text-xs text-orange-800">Late</span></div>
        <p className="mt-1.5 text-[13px] text-slate-500">Items running late</p>
      </div>
    </div>

    {canOpenExecution && <button type="button" onClick={() => onTabChange?.("execution")} className="mt-auto flex h-12 items-center justify-center gap-2 rounded-xl bg-slate-950 text-sm font-medium text-white transition-colors hover:bg-slate-800">Open execution board<ArrowRight aria-hidden="true" size={16} /></button>}
  </aside>;
}

function Gauge({ percent }) {
  // Semicircle: arc length of r=120 half circle is ~377.
  const arc = 377 * percent / 100;
  return <div className="relative mx-auto mt-1 w-full max-w-[210px]">
    <svg viewBox="0 0 280 160" className="w-full" role="img" aria-label={`${percent}% of open tasks on schedule`}>
      <path d="M 20 150 A 120 120 0 0 1 260 150" fill="none" stroke="var(--color-line)" strokeWidth="18" strokeLinecap="round" />
      {percent > 0 && <path d="M 20 150 A 120 120 0 0 1 260 150" fill="none" stroke="var(--color-ok)" strokeWidth="18" strokeLinecap="round" strokeDasharray={`${arc} 377`} />}
    </svg>
    <div className="absolute inset-x-0 bottom-1 flex flex-col items-center gap-1.5">
      <span className="text-[34px] font-light leading-none tracking-[-0.03em] text-slate-950">{percent}%</span>
      <span className="rounded-md bg-emerald-50 px-2.5 py-0.5 text-xs text-emerald-800">On schedule</span>
    </div>
  </div>;
}

function SiteHealth({ rows }) {
  const sum = key => rows.reduce((total, row) => total + (row[key] || 0), 0);
  const open = sum("task_count") - sum("completed_count");
  const overdue = sum("overdue_count");
  const approvalsOverdue = rows.reduce((total, row) => total + (row.approvals || []).filter(item => item.overdue).length, 0);
  const pastHandover = rows.filter(row => row.days_late > 0);
  const onSchedule = open ? Math.round((open - overdue) / open * 100) : 100;
  const items = [
    { label: "Overdue tasks", hint: "Past their planned finish, still open", value: overdue, color: "var(--color-behind)" },
    { label: "Blocked on site", hint: "Stopped on material, access or a NOC", value: sum("blocked_count"), color: "#d9483b" },
    { label: "Approvals overdue", hint: "Client, landlord and authority sign-offs", value: approvalsOverdue, color: "var(--color-gate)" },
    { label: "Forecast past handover", hint: pastHandover.length ? `Worst: ${Math.max(...pastHandover.map(row => row.days_late))} days late` : "Every forecast is within its handover date", value: pastHandover.length, color: "#f2c94c" },
  ];
  return <Panel title="Site health" id="ov-health" className="ov-health">
    <div className="grid">
      {items.map(item => <div key={item.label} className="flex items-center gap-3.5 border-b border-slate-100 py-2.5 last:border-b-0">
        <span className="h-8 w-2 shrink-0 rounded" style={{ background: item.value ? item.color : "var(--color-slate-200)" }} />
        <span className="min-w-0 flex-1"><span className="block text-[15px] text-slate-950">{item.label}</span><span className="block truncate text-[13px] text-slate-500">{item.hint}</span></span>
        <span className="text-[22px] font-light tabular-nums text-slate-950">{item.value}</span>
      </div>)}
    </div>
    <Gauge percent={onSchedule} />
    <p className="text-center text-[13px] text-slate-500">Open tasks that are not past their planned finish</p>
  </Panel>;
}

function OpenWork({ rows }) {
  const sum = key => rows.reduce((total, row) => total + (row[key] || 0), 0);
  const open = sum("task_count") - sum("completed_count");
  const overdue = sum("overdue_count");
  const onTime = Math.max(0, open - overdue);
  const max = Math.max(onTime, overdue, 1);
  return <Panel title="Open work" id="ov-open" className="ov-open">
    <Legend items={[["On schedule", "var(--color-gate)"], ["Overdue", "var(--color-behind)"]]} />
    <div className="flex min-h-[150px] flex-1 items-end gap-3.5">
      <div className="flex-1 pb-1">
        <span className="block text-[42px] font-light leading-none tracking-[-0.03em] text-slate-950">{open.toLocaleString()}</span>
        <span className="mt-1.5 block text-[13px] text-slate-500">open tasks across {rows.length} {rows.length === 1 ? "site" : "sites"}</span>
      </div>
      {[[onTime, "var(--color-gate)", "On schedule"], [overdue, "var(--color-behind)", "Overdue"]].map(([value, color, label]) => <div key={label} className="flex w-[72px] flex-col items-center gap-1.5 sm:w-[84px]">
        <span className="text-[13px] font-medium tabular-nums text-slate-950">{value}</span>
        <div className="w-full rounded-xl" style={{ height: `${Math.max(12, value / max * 120)}px`, background: color }} title={label} />
      </div>)}
    </div>
  </Panel>;
}

// The card's one-line status must agree with its health label: "Delayed"
// comes from overdue tasks as well as a late forecast, so check both.
export function cardStatus(row) {
  if (row.health === "completed") return { text: "Handed over", tone: "text-blue-700" };
  if (row.days_late > 0) return { text: `${row.days_late} ${row.days_late === 1 ? "day" : "days"} late`, tone: "text-rose-700" };
  if (row.overdue_count > 0) return { text: `${row.overdue_count} overdue`, tone: "text-rose-700" };
  if (row.blocked_count > 0) return { text: `${row.blocked_count} blocked`, tone: "text-orange-700" };
  if (row.behind) return { text: "Behind plan", tone: "text-orange-700" };
  return { text: "On plan", tone: "text-emerald-700" };
}

function daysUntil(date) {
  if (!date) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return Math.round((new Date(`${date}T00:00:00`) - today) / 86400000);
}

function HandoverRow({ row, onOpenProject }) {
  const meta = HEALTH[row.standing] || HEALTH.on_track;
  const status = cardStatus(row);
  const days = daysUntil(row.target_handover_date);
  const when = days == null ? "No handover date" : days < 0 ? `${-days} days past handover` : days === 0 ? "Handover today" : `In ${days} ${days === 1 ? "day" : "days"}`;
  return <li>
    <button type="button" onClick={() => onOpenProject?.(row.code)} aria-label={`Open ${row.name}`} className="flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600">
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-[10px] text-xs font-medium", meta.tile)}>{initials(row.name)}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2"><span className="truncate text-sm text-slate-950">{row.name}</span><span className="shrink-0 text-xs tabular-nums text-slate-700">{row.progress_pct}%</span></span>
        <span className="flex items-baseline justify-between gap-2 text-xs"><span className="truncate text-slate-500">{row.target_handover_date ? `${formatDateShort(row.target_handover_date)}, ${when.toLowerCase()}` : when}</span><span className={cn("shrink-0", status.tone)}>{status.text}</span></span>
      </span>
    </button>
  </li>;
}

// Upcoming handovers, nearest first: a different cut of the portfolio from
// the progress chart above, rather than the same projects a second time.
function Handovers({ rows, onOpenProject, onTabChange, tabs }) {
  const [tab, setTab] = useState("all");
  const upcoming = sortRows(rows.filter(row => row.standing !== "completed"), "handover");
  const filtered = tab === "all" ? upcoming : upcoming.filter(row => row.standing === tab);
  const shown = filtered.slice(0, HANDOVER_LIMIT);
  const canOpenProjects = tabs?.some(([key]) => key === "projects");
  return <section aria-labelledby="ov-projects" className="ov-projects flex min-w-0 flex-col gap-3 rounded-[22px] border border-line bg-white p-5 sm:p-6">
    <div className="flex items-center justify-between gap-3">
      <h2 id="ov-projects" className="text-[17px] font-medium text-slate-950">Handovers coming up</h2>
      {canOpenProjects && <button type="button" onClick={() => onTabChange?.("projects")} className="text-[13px] text-blue-700 hover:text-blue-900">All projects</button>}
    </div>
    <div role="tablist" aria-label="Filter handovers by health" className="flex w-fit gap-0.5 rounded-[10px] bg-slate-100 p-[3px]">
      {HEALTH_TABS.map(([key, label]) => {
        const count = key === "all" ? upcoming.length : upcoming.filter(row => row.standing === key).length;
        return <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)} className={cn("h-7 rounded-lg px-2.5 text-[13px] transition", tab === key ? "bg-white text-slate-950 shadow-[0_1px_3px_rgba(21,23,26,.12)]" : "text-slate-500 hover:text-slate-950")}>{label} <span className="text-slate-400">{count}</span></button>;
      })}
    </div>
    <ul className="-mx-2 grid content-start" style={{ minHeight: HANDOVER_LIMIT * 56 }}>
      {shown.length === 0
        ? <li className="px-2 py-6 text-sm text-slate-500">No projects in this group right now.</li>
        : shown.map(row => <HandoverRow key={row.project_id} row={row} onOpenProject={onOpenProject} />)}
    </ul>
    {filtered.length > shown.length && <p className="mt-auto border-t border-line pt-3 text-[13px] text-slate-500">{filtered.length - shown.length} more after {formatDateShort(shown[shown.length - 1].target_handover_date)}</p>}
  </section>;
}

export function OverviewPage({ user, tabs, onOpenProject, onTabChange }) {
  const [timeline, setTimeline] = useState([]);
  const [attention, setAttention] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      // Each source fails on its own: a missing attention feed should not
      // blank the portfolio numbers, and vice versa.
      const [timelineResult, attentionResult] = await Promise.allSettled([projectsApi.timeline(), projectsApi.attention()]);
      if (!alive) return;
      if (timelineResult.status === "fulfilled") setTimeline(Array.isArray(timelineResult.value) ? timelineResult.value : []);
      if (attentionResult.status === "fulfilled") setAttention(Array.isArray(attentionResult.value) ? attentionResult.value : []);
      const failed = [timelineResult, attentionResult].filter(result => result.status === "rejected");
      if (failed.length) setError(failed[0].reason?.message || "Part of the overview could not be loaded. Refresh to try again.");
      setLoading(false);
    })();
    return () => { alive = false; };
  }, []);

  const rows = useMemo(() => timeline.map(row => {
    const planned = plannedPercent(row);
    return {
      ...row,
      planned: planned ?? 0,
      behind: planned != null && row.status !== "completed" && planned - row.progress_pct > BEHIND_TOLERANCE,
      standing: standingOf(row, planned),
    };
  }), [timeline]);
  const running = useMemo(() => rows.filter(row => RUNNING.has(row.status) && row.task_count > 0), [rows]);

  if (loading) return <div className="grid min-h-60 place-items-center"><LoadingSpinner label="Loading overview..." /></div>;

  return <div className="grid gap-4">
    {error && <Alert tone="warning">{error}</Alert>}
    <div className="ov-grid">
      <ProgressChart rows={running} onOpenProject={onOpenProject} />
      <TodayPanel user={user} rows={running} attention={attention} tabs={tabs} onOpenProject={onOpenProject} onTabChange={onTabChange} />
      <SiteHealth rows={running} />
      <OpenWork rows={running} />
      <Handovers rows={rows} onOpenProject={onOpenProject} onTabChange={onTabChange} tabs={tabs} />
    </div>
  </div>;
}

