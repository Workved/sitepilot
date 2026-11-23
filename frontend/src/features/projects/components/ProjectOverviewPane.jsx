import { CircleCheck, Lock, MapPin } from "lucide-react";
import { planGap, scheduleWindow } from "../../../utils/schedule";
import { useState } from "react";
import { PhaseOverviewDrawer } from "./PhaseOverviewDrawer";

export const VISIBLE_PHASE_COUNT = 5;

/**
 * Pick the few phases worth showing on Overview.
 *
 * Chosen by what is happening, not by schedule order: a 45-day template has
 * 36 phases, and the first five stop meaning anything the moment a project is
 * past its opening weeks - they would all read 100% while the actual work sat
 * out of sight. Priority is work in flight, then what is up next, then the
 * most recently finished so a nearly-complete project still shows something.
 *
 * Selection is by relevance; display stays in schedule order, because a list
 * that jumps around is harder to read than one that does not.
 */
export function selectRelevantPhases(phases = [], limit = VISIBLE_PHASE_COUNT) {
  if (!phases.length) return [];
  const order = new Map(phases.map((phase, index) => [phase.phase, index]));
  const byStatus = status => phases.filter(phase => phase.status === status);

  const picked = [...byStatus("in_progress"), ...byStatus("not_started")].slice(0, limit);
  if (picked.length < limit) {
    const completed = byStatus("completed");
    picked.push(...completed.slice(Math.max(completed.length - (limit - picked.length), 0)));
  }
  return picked.sort((a, b) => order.get(a.phase) - order.get(b.phase));
}

const SEVERITY_DOT = { critical: "bg-rose-600", warning: "bg-behind", decision: "bg-gate" };

// Done / in progress / not started, side by side in one bar. The summary
// already carries all three counts, so work that has started shows even
// while nothing in the phase is finished yet.
function PhaseBars({ phases }) {
  return <ul className="grid gap-3">
    {phases.map(phase => {
      const total = phase.total || 1;
      const inProgress = phase.in_progress || 0;
      return <li key={phase.phase} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 text-[13px] sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_5.5rem]">
        <span className="truncate text-slate-900">{phase.phase}</span>
        <span className="order-3 col-span-2 flex h-2 overflow-hidden rounded-full bg-slate-100 sm:order-none sm:col-span-1" aria-hidden="true">
          {phase.completed > 0 && <span className="h-full" style={{ width: `${phase.completed / total * 100}%`, background: phase.pct === 100 ? "var(--color-ok)" : "var(--color-blue-600)" }}/>}
          {inProgress > 0 && <span className="h-full" style={{ width: `${inProgress / total * 100}%`, background: "var(--color-blue-200)" }}/>}
        </span>
        <span className="flex items-baseline justify-end gap-2 tabular-nums">
          {/* Counts lead: "0 / 8" tells you more about what is outstanding
              than "0%" does, especially where a phase holds one or two tasks. */}
          <span className="text-slate-900">{phase.completed}/{phase.total}</span>
          <span className="w-9 text-right text-slate-500">{phase.pct}%</span>
        </span>
      </li>;
    })}
  </ul>;
}

function Card({ title, action, children, className = "" }) {
  return <section className={`rounded-[20px] border border-line bg-white p-5 ${className}`}>
    {(title || action) && <div className="mb-4 flex items-start justify-between gap-3">{title}{action}</div>}
    {children}
  </section>;
}

function Headline({ project, summary }) {
  const pct = summary.progress_pct ?? 0;
  const gap = planGap(project, pct);
  const window = scheduleWindow(project);
  let status = null;
  if (window?.notStarted) status = { text: "Not started yet", className: "bg-slate-100 text-slate-700" };
  else if (gap?.behind) status = { text: `Behind plan by ${gap.gap} points`, className: "bg-orange-50 text-orange-800" };
  else if (gap) status = { text: "On plan", className: "bg-emerald-50 text-emerald-800" };
  return <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
    <span className="text-[44px] font-light leading-none tracking-[-0.03em] text-slate-950">{pct}%</span>
    <span className="pb-1 text-sm text-slate-500">{summary.completed_count} of {summary.total_count} tasks complete{gap ? `, ${gap.planned}% of time used` : ""}</span>
    {status && <span className={`mb-1 rounded-md px-2 py-0.5 text-xs ${status.className}`}>{status.text}</span>}
  </div>;
}

function Stat({ label, value, color, onOpen }) {
  const content = <>
    <span className="h-7 w-1.5 shrink-0 rounded" style={{ background: value ? color : "var(--color-slate-200)" }} aria-hidden="true"/>
    <span className={`min-w-0 flex-1 truncate text-sm ${value ? "text-slate-950" : "text-slate-500"}`}>{label}</span>
    <span className={`text-xl font-light tabular-nums ${value ? "text-slate-950" : "text-slate-400"}`}>{value}</span>
  </>;
  const className = "flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left";
  return <li>{onOpen
    ? <button type="button" onClick={onOpen} aria-label={`${label}: ${value}. Open the project dashboard`} className={`${className} transition-colors hover:bg-slate-50`}>{content}</button>
    : <div className={className}>{content}</div>}</li>;
}

export function ProjectOverviewPane({ project, summary, attention = [], onOpenPane }) {
  const [phasesOpen, setPhasesOpen] = useState(false);
  const allPhases = summary?.phases || [];
  const phases = allPhases.length ? selectRelevantPhases(allPhases) : null;
  const hiddenPhaseCount = Math.max(allPhases.length - (phases?.length || 0), 0);
  const openDashboard = project.status === "draft" ? undefined : () => onOpenPane("dashboard");

  return <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
    <div className="grid min-w-0 gap-4">
      {summary
        ? <Card
            title={<h3 className="text-[17px] font-medium text-slate-950">Execution progress</h3>}
            action={<button type="button" onClick={() => onOpenPane("template-review")} className="shrink-0 py-1 text-[13px] text-blue-700 hover:text-blue-900">All tasks</button>}
          >
            <Headline project={project} summary={summary}/>
            <div className="mt-6 flex items-center justify-between gap-3">
              <h4 className="text-sm text-slate-950">{allPhases.some(phase => phase.status === "in_progress") ? "Phases in progress and up next" : "Phases"}</h4>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                {[["Done", "var(--color-blue-600)"], ["In progress", "var(--color-blue-200)"], ["Not started", "var(--color-slate-100)"]].map(([label, color]) => <span key={label} className="flex items-center gap-1.5"><span className="size-2.5 rounded-[3px] border border-slate-200" style={{ background: color }}/>{label}</span>)}
              </div>
            </div>
            <div className="mt-3">
              {phases ? <PhaseBars phases={phases}/> : <p className="text-sm text-slate-500">Phase breakdown is not available for this project.</p>}
            </div>
            {hiddenPhaseCount > 0 && <button
              type="button"
              onClick={() => setPhasesOpen(true)}
              className="mt-5 flex h-10 w-full items-center justify-center rounded-xl border border-slate-200 bg-white text-[13px] text-slate-800 transition hover:border-slate-300 hover:bg-slate-50"
            >View all {allPhases.length} phases</button>}
          </Card>
        : <Card><p className="text-sm text-slate-500">Progress figures are not available for this project yet.</p></Card>}

      <Card>
        <div className="flex items-start gap-3.5">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-700"><MapPin size={18} aria-hidden="true"/></span>
          <div className="min-w-0">
            <h3 className="text-[15px] font-medium text-slate-950">Site</h3>
            <p className="mt-0.5 whitespace-pre-wrap text-sm leading-6 text-slate-600">{project.site_address || "No site address recorded."}</p>
            {project.description && <p className="mt-3 border-t border-slate-100 pt-3 text-sm leading-6 text-slate-500">{project.description}</p>}
          </div>
        </div>
        {project.status !== "draft" && <p className="mt-4 flex items-center gap-2 border-t border-slate-100 pt-3 text-[13px] text-slate-500">
          <Lock size={14} className="shrink-0" aria-hidden="true"/>
          Baseline locked on activation. The template reference can no longer change.
        </p>}
      </Card>
    </div>

    <div className="grid min-w-0 gap-4">
      <Card title={<h3 className="flex items-center gap-2 text-[15px] font-medium text-slate-950">Needs attention{attention.length > 0 && <span className="grid h-5 min-w-5 place-items-center rounded-md bg-rose-600 px-1 text-xs font-normal text-white">{attention.length}</span>}</h3>}>
        {attention.length
          ? <ul className="-mx-2 grid gap-0.5">
              {attention.map(item => <li key={item.id}>
                <button type="button" onClick={() => onOpenPane(item.pane || "overview")} className="flex w-full items-start gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-slate-50">
                  <span className={`mt-1.5 size-2 shrink-0 rounded-full ${SEVERITY_DOT[item.severity] || "bg-slate-400"}`} aria-hidden="true"/>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-slate-950">{item.title}</span>
                    <span className="block truncate text-xs text-slate-500">{item.subtitle}</span>
                  </span>
                  {item.due_label && <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{item.due_label}</span>}
                </button>
              </li>)}
            </ul>
          : <p className="flex items-center gap-2 text-sm text-slate-500"><CircleCheck size={16} className="text-emerald-600" aria-hidden="true"/>Nothing is waiting on you here.</p>}
      </Card>

      {summary && <Card title={<h3 className="text-[15px] font-medium text-slate-950">Site health</h3>}>
        <ul className="-mx-2 grid">
          <Stat label="Overdue tasks" value={summary.overdue_count ?? 0} color="var(--color-behind)" onOpen={openDashboard}/>
          <Stat label="Blocked on site" value={summary.blocked_count ?? 0} color="#d9483b" onOpen={openDashboard}/>
          <Stat label="Delayed" value={summary.delayed_count ?? 0} color="#e8a33c" onOpen={openDashboard}/>
          <Stat label="Pending approvals" value={summary.pending_approvals ?? 0} color="var(--color-gate)" onOpen={openDashboard}/>
          <Stat label="Awaiting verification" value={summary.pending_verifications ?? 0} color="var(--color-blue-600)" onOpen={openDashboard}/>
          <Stat label="No update in 48h" value={summary.no_update_count ?? 0} color="#f2c94c" onOpen={openDashboard}/>
        </ul>
      </Card>}
    </div>

    {phasesOpen && <PhaseOverviewDrawer project={project} summary={summary} onClose={() => setPhasesOpen(false)}/>}
  </div>;
}
