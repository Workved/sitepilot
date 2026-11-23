import { useEffect, useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
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
const HEALTH_TABS = [["all", "All"], ["on_track", "On track"], ["at_risk", "At risk"], ["delayed", "Delayed"], ["completed", "Completed"]];
const RUNNING = new Set(["active", "on_hold"]);
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

// Up to this many projects, one labelled horizontal bar each reads far
// better than a few thin columns stranded at the left of a wide chart.
const ROW_LAYOUT_MAX = 12;

function ProgressRows({ rows, onOpenProject }) {
  return <ul className="grid gap-1">
    {rows.map(row => <li key={row.project_id}>
      <button type="button" onClick={() => onOpenProject?.(row.code)} aria-label={`${row.name}: planned ${row.planned}%, completed ${row.progress_pct}%`} className="grid w-full grid-cols-1 items-center gap-x-5 gap-y-2 rounded-xl px-2 py-3 text-left transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 sm:grid-cols-[minmax(140px,220px)_minmax(0,1fr)_auto]">
        <span className="min-w-0"><span className="block truncate text-sm text-slate-950">{row.name}</span><span className="block truncate text-xs text-slate-500">{row.code}</span></span>
        <span className="relative block h-3.5 rounded-full bg-slate-100" aria-hidden="true">
          <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${row.planned}%`, background: row.behind ? "var(--color-behind-soft)" : "var(--color-blue-100)" }} />
          {row.progress_pct > 0 && <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(row.progress_pct, 2)}%`, background: row.behind ? "var(--color-behind)" : "var(--color-blue-600)" }} />}
          <span className="absolute -top-1 h-[22px] w-0.5 rounded bg-slate-950" style={{ left: `calc(${row.planned}% - 1px)` }} />
        </span>
        <span className="whitespace-nowrap text-[13px] tabular-nums text-slate-500"><span className="text-slate-950">{row.progress_pct}% done</span>, {row.planned}% of time used</span>
      </button>
    </li>)}
  </ul>;
}

function ProgressChart({ rows, onOpenProject }) {
  const [filter, setFilter] = useState("all");
  const [hover, setHover] = useState(null);
  const shown = filter === "behind" ? rows.filter(row => row.behind) : rows;
  const totals = rows.reduce((acc, row) => ({ done: acc.done + row.completed_count, all: acc.all + row.task_count }), { done: 0, all: 0 });
  const overall = totals.all ? Math.round(totals.done / totals.all * 100) : 0;
  const behindCount = rows.filter(row => row.behind).length;
  const active = hover != null ? shown[hover] : null;

  return <Panel id="ov-progress" className="ov-chart">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="grid gap-1.5">
        <h2 id="ov-progress" className="text-[17px] font-medium text-slate-950">Progress against plan</h2>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-[42px] font-light leading-none tracking-[-0.03em] text-slate-950">{overall}%</span>
          <span className="text-sm text-slate-500">{totals.done.toLocaleString()} of {totals.all.toLocaleString()} tasks complete across {rows.length} running {rows.length === 1 ? "project" : "projects"}</span>
        </div>
      </div>
      <div role="tablist" aria-label="Projects shown" className="flex gap-0.5 rounded-[10px] bg-slate-100 p-[3px]">
        {[["all", "All"], ["behind", `Behind plan ${behindCount}`]].map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={filter === key} onClick={() => { setFilter(key); setHover(null); }} className={cn("h-8 rounded-lg px-3 text-[13px] transition", filter === key ? "bg-white text-slate-950 shadow-[0_1px_3px_rgba(21,23,26,.12)]" : "text-slate-500 hover:text-slate-950")}>{label}</button>)}
      </div>
    </div>
    <Legend items={[["Completed", "var(--color-blue-600)"], ["Time elapsed", "var(--color-blue-100)"], ["Behind plan", "var(--color-behind)"], ["Today", "var(--color-slate-950)"]]} />

    {shown.length === 0
      ? <EmptyState title={filter === "behind" ? "Nothing is behind plan" : "No running projects"} description={filter === "behind" ? "Every running project has completed at least as much work as the calendar expects." : "Projects show here once they are activated and have dated tasks."} />
      : shown.length <= ROW_LAYOUT_MAX
        ? <ProgressRows rows={shown} onOpenProject={onOpenProject} />
        : <div>
          <div className="relative h-[240px]">
            <div aria-hidden="true" className="absolute inset-0 grid grid-rows-4">
              {[0, 1, 2, 3].map(line => <div key={line} className="border-t border-dashed border-slate-200" />)}
            </div>
            {active && <div className="pointer-events-none absolute -top-2 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-[10px] border border-line bg-white px-3 py-2 text-xs shadow-[0_8px_24px_rgba(21,23,26,.08)]">
              <span className="font-medium text-slate-950">{active.name}</span>
              <span className="ml-2 text-slate-500">Planned {active.planned}%, done {active.progress_pct}%</span>
            </div>}
            <div className="absolute inset-0 flex items-end gap-[3px] sm:gap-1.5">
              {shown.map((row, index) => <button key={row.project_id} type="button" onClick={() => onOpenProject?.(row.code)} onMouseEnter={() => setHover(index)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(index)} onBlur={() => setHover(null)} aria-label={`${row.name}: planned ${row.planned}%, completed ${row.progress_pct}%`} className="group relative h-full min-w-0 flex-1 rounded-t-[4px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600" style={{ maxWidth: 56 }}>
                <span className="absolute inset-x-0 bottom-0 rounded-t-[4px] transition-colors" style={{ height: `${Math.max(row.planned, 2)}%`, background: row.behind ? "var(--color-behind-soft)" : "var(--color-blue-100)" }} />
                <span className="absolute inset-x-0 bottom-0 rounded-t-[4px] transition-opacity group-hover:opacity-85" style={{ height: `${Math.max(row.progress_pct, 1.5)}%`, background: row.behind ? "var(--color-behind)" : "var(--color-blue-600)" }} />
              </button>)}
            </div>
          </div>
          <div className="mt-2 flex gap-[3px] border-t border-line pt-2 sm:gap-1.5" aria-hidden="true">
            {shown.map(row => <span key={row.project_id} className="min-w-0 flex-1 truncate text-center text-[11px] text-slate-500" style={{ maxWidth: 56 }}>{shown.length > 18 ? "" : row.code.split("-").pop()}</span>)}
          </div>
        </div>}
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
  const onTrack = rows.filter(row => row.health === "on_track").length;
  const late = rows.filter(row => row.health === "delayed");
  const decisions = attention.filter(item => item.group === "Needs a decision");
  const runningLate = attention.filter(item => item.group === "Running late");
  const top = [...attention].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3)).slice(0, 4);
  const canOpenExecution = tabs?.some(([key]) => key === "execution");
  const firstName = (user?.name || "").split(" ")[0];

  const sentences = [];
  if (late.length) sentences.push(`${late.length} ${late.length === 1 ? "project is" : "projects are"} running late${late.length <= 2 ? `: ${late.map(row => row.name).join(" and ")}` : ""}.`);
  if (decisions.length) sentences.push(`${decisions.length} ${decisions.length === 1 ? "decision is" : "decisions are"} waiting on you.`);
  if (!sentences.length) sentences.push(rows.length ? "Every running project is moving to plan and nothing is waiting on you." : "No running projects yet. Activated projects and their alerts show up here.");

  return <aside aria-labelledby="ov-today" className="ov-today flex min-w-0 flex-col gap-4 rounded-[22px] border border-line bg-slate-50 p-5 sm:p-6">
    <div className="flex flex-col items-center gap-1 pt-1 text-center">
      <div className="mb-2"><Ring value={onTrack} total={rows.length} /></div>
      <p className="text-sm text-slate-500">{greeting()}{firstName ? `, ${firstName}` : ""}</p>
      <h2 id="ov-today" className="text-[22px] font-normal tracking-[-0.01em] text-slate-950">Here is what needs you today</h2>
    </div>

    <div className="grid gap-3 rounded-2xl border border-line bg-white p-4">
      <h3 className="text-sm font-medium text-slate-950">Today's summary</h3>
      <p className="text-[13px] leading-relaxed text-slate-600">{sentences.join(" ")}</p>
      {top.length > 0 && <ul className="grid gap-1">
        {top.map(item => <li key={item.id}>
          <button type="button" onClick={() => onOpenProject?.(item.project_code, item.pane)} className="flex w-full items-start gap-2.5 rounded-xl px-1.5 py-1.5 text-left text-[13px] hover:bg-slate-50">
            <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", SEVERITY_DOT[item.severity] || "bg-slate-400")} />
            <span className="min-w-0"><span className="block text-slate-950">{item.title}</span><span className="block truncate text-slate-500">{item.project_code}{item.due_label ? `, ${item.due_label}` : ""}{item.subtitle ? `, ${item.subtitle}` : ""}</span></span>
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
  return <div className="relative mx-auto mt-2 w-full max-w-[280px]">
    <svg viewBox="0 0 280 160" className="w-full" role="img" aria-label={`${percent}% of open tasks on schedule`}>
      <path d="M 20 150 A 120 120 0 0 1 260 150" fill="none" stroke="var(--color-line)" strokeWidth="18" strokeLinecap="round" />
      {percent > 0 && <path d="M 20 150 A 120 120 0 0 1 260 150" fill="none" stroke="var(--color-ok)" strokeWidth="18" strokeLinecap="round" strokeDasharray={`${arc} 377`} />}
    </svg>
    <div className="absolute inset-x-0 bottom-1 flex flex-col items-center gap-1.5">
      <span className="text-[44px] font-light leading-none tracking-[-0.03em] text-slate-950">{percent}%</span>
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
      {items.map(item => <div key={item.label} className="flex items-center gap-3.5 border-b border-slate-100 py-3 last:border-b-0">
        <span className="h-9 w-2.5 shrink-0 rounded" style={{ background: item.color }} />
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

function ProjectCard({ row, onOpenProject }) {
  const meta = HEALTH[row.health] || HEALTH.on_track;
  const status = cardStatus(row);
  return <button type="button" onClick={() => onOpenProject?.(row.code)} aria-label={`Open ${row.name}`} className="flex w-[212px] shrink-0 flex-col gap-2.5 rounded-2xl border border-line bg-white p-3.5 text-left transition-colors hover:border-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">
    <span className="flex items-center gap-2.5">
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-[10px] text-xs font-medium", meta.tile)}>{initials(row.name)}</span>
      <span className="min-w-0"><span className="block truncate text-sm font-medium text-slate-950">{row.name}</span><span className="block truncate text-xs text-slate-500">{row.code}</span></span>
    </span>
    <span className="flex items-baseline justify-between gap-2">
      <span className="text-[26px] font-light tracking-[-0.02em] text-slate-950">{row.progress_pct}%</span>
      <span className={cn("text-xs font-medium", status.tone)}>{status.text}</span>
    </span>
    <span className="relative block h-1.5 rounded-full bg-slate-100" aria-hidden="true">
      <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${row.progress_pct}%`, background: row.behind ? "var(--color-behind)" : "var(--color-blue-600)" }} />
      {row.planned != null && row.health !== "completed" && <span className="absolute -top-1 h-3.5 w-0.5 rounded bg-slate-950" style={{ left: `calc(${row.planned}% - 1px)` }} />}
    </span>
    <span className="text-xs text-slate-500">{row.target_handover_date ? `Handover ${formatDateShort(row.target_handover_date)}` : "No handover date set"}</span>
    <span className={cn("w-fit rounded-md px-2 py-0.5 text-xs", meta.pill)}>{meta.label}</span>
  </button>;
}

function ProjectRail({ rows, onOpenProject, onTabChange, tabs }) {
  const [tab, setTab] = useState("all");
  const shown = tab === "all" ? rows : rows.filter(row => row.health === tab);
  const canOpenProjects = tabs?.some(([key]) => key === "projects");
  return <section aria-labelledby="ov-projects" className="ov-projects flex min-w-0 flex-col gap-3.5 rounded-[22px] border border-line bg-white px-4 pb-4 pt-2 sm:px-5">
    <h2 id="ov-projects" className="sr-only">Projects</h2>
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line">
      <div role="tablist" aria-label="Filter projects by health" className="so-scroll flex gap-1 overflow-x-auto">
        {HEALTH_TABS.map(([key, label]) => {
          const count = key === "all" ? rows.length : rows.filter(row => row.health === key).length;
          return <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)} className={cn("h-11 shrink-0 px-2.5 text-sm transition-colors", tab === key ? "text-slate-950 shadow-[inset_0_-2px_0_var(--color-slate-950)]" : "text-slate-500 hover:text-slate-950")}>{label} <span className="text-slate-400">{count}</span></button>;
        })}
      </div>
      {canOpenProjects && <button type="button" onClick={() => onTabChange?.("projects")} className="py-2 text-[13px] text-blue-700 hover:text-blue-900">All projects</button>}
    </div>
    <div className="so-scroll flex gap-3 overflow-x-auto pb-1">
      {shown.length === 0
        ? <p className="py-6 text-sm text-slate-500">No projects in this group right now.</p>
        : shown.map(row => <ProjectCard key={row.project_id} row={row} onOpenProject={onOpenProject} />)}
    </div>
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
    return { ...row, planned: planned ?? 0, behind: planned != null && row.status !== "completed" && planned - row.progress_pct > BEHIND_TOLERANCE };
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
      <ProjectRail rows={rows} onOpenProject={onOpenProject} onTabChange={onTabChange} tabs={tabs} />
    </div>
  </div>;
}

