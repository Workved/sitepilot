import { createPortal } from "react-dom";
import { ChevronDown, ChevronRight, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { LoadingSpinner, Pill } from "../../../components/ui";

const STATUS_FILTERS = [
  ["all", "All statuses"],
  ["in_progress", "In progress"],
  ["not_started", "Not started"],
  ["completed", "Completed"],
];

const phaseStatusLabel = { in_progress: "In progress", not_started: "Not started", completed: "Completed" };
const phaseStatusTone = { in_progress: "blue", not_started: "gray", completed: "green" };

const taskStatusTone = {
  completed: "green", in_progress: "blue", submitted: "blue", verified: "blue",
  approval_pending: "orange", rejected: "red", cancelled: "gray", planned: "gray", ready: "gray",
};
const humanise = value => String(value || "").replaceAll("_", " ").replace(/^./, c => c.toUpperCase());

/** Template day offsets are 1-based and inclusive of the start date, the same
 *  convention derive_target_handover_date uses on the backend. */
export function plannedDate(startDate, dayOffset) {
  if (!startDate || typeof dayOffset !== "number") return null;
  const date = new Date(`${startDate}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  date.setDate(date.getDate() + dayOffset - 1);
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function ProgressCell({ phase }) {
  // A bar across one or two tasks is a yes/no drawn as a chart. The count and
  // the status chip already say it, so the bar only appears where it adds
  // something to scan.
  if (phase.total <= 2) return <span className="text-xs text-slate-400">—</span>;
  return <span className="flex items-center gap-2">
    <span className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
      <span className="block h-full rounded-full" style={{ width: `${phase.pct}%`, background: phase.pct === 100 ? "#059669" : "#2563eb" }}/>
    </span>
    <span className="w-8 shrink-0 text-right tabular-nums text-xs text-slate-500">{phase.pct}%</span>
  </span>;
}

function PhaseRow({ phase, expanded, onToggle, tasks, tasksLoading, startDate }) {
  return <>
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      className={`grid w-full grid-cols-[minmax(0,1fr)_3.5rem_minmax(4rem,7rem)_5.5rem] items-center gap-2 border-b border-slate-100 px-3 py-2.5 text-left transition hover:bg-slate-50 ${expanded ? "bg-slate-50" : ""}`}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        {expanded ? <ChevronDown size={14} className="shrink-0 text-slate-400"/> : <ChevronRight size={14} className="shrink-0 text-slate-400"/>}
        <span className="truncate text-xs font-bold text-slate-900">{phase.phase}</span>
      </span>
      <span className="tabular-nums text-xs text-slate-500">{phase.completed} / {phase.total}</span>
      <ProgressCell phase={phase}/>
      <span className="justify-self-end"><Pill tone={phaseStatusTone[phase.status]}>{phaseStatusLabel[phase.status]}</Pill></span>
    </button>

    {expanded && <div className="border-b border-slate-100 bg-slate-50/70 px-3 py-2">
      {tasksLoading
        ? <LoadingSpinner label="Loading tasks…"/>
        : tasks.length
          ? <ul className="grid gap-1">
              {tasks.map(task => <li key={task.id} className="grid grid-cols-[minmax(0,1fr)_auto_5.5rem] items-center gap-2 rounded-lg bg-white px-2.5 py-1.5">
                <span className="min-w-0">
                  <span className="block truncate text-xs font-semibold text-slate-800">{task.title}</span>
                  <span className="tabular-nums text-xs text-slate-400">{task.original_code}</span>
                </span>
                <Pill tone={taskStatusTone[task.lifecycle_status] || "gray"}>{humanise(task.lifecycle_status)}</Pill>
                <span className="justify-self-end text-right text-xs text-slate-500">
                  {plannedDate(startDate, task.planned_start_day) || "—"}
                </span>
              </li>)}
            </ul>
          : <p className="px-1 py-2 text-xs text-slate-400">No tasks in this phase.</p>}
    </div>}
  </>;
}

export function PhaseOverviewDrawer({ project, summary, onClose }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [expanded, setExpanded] = useState(null);
  const [tasks, setTasks] = useState(null);
  const [tasksLoading, setTasksLoading] = useState(false);

  useEffect(() => {
    function onKey(event) { if (event.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Fetched once, on first expand rather than on open - the full task list is
  // 99 rows on a 45-day project and most visits never drill in.
  async function toggle(phaseName) {
    const next = expanded === phaseName ? null : phaseName;
    setExpanded(next);
    if (!next || tasks !== null || tasksLoading) return;
    setTasksLoading(true);
    try {
      setTasks(await taskExecutionApi.list(project.id));
    } catch {
      setTasks([]);
    } finally {
      setTasksLoading(false);
    }
  }

  const phases = summary?.phases || [];
  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return phases.filter(phase => (status === "all" || phase.status === status)
      && (!term || phase.phase.toLowerCase().includes(term)));
  }, [phases, search, status]);

  const tasksByPhase = useMemo(() => {
    if (!tasks) return {};
    return tasks.reduce((groups, task) => {
      const key = task.phase || "Unphased";
      return { ...groups, [key]: [...(groups[key] || []), task] };
    }, {});
  }, [tasks]);

  return createPortal(<div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Phase overview">
    <button type="button" aria-label="Close phase overview" className="absolute inset-0 bg-slate-950/30 backdrop-blur-[2px]" onClick={onClose}/>
    <section className="relative flex h-full w-[min(30rem,100vw)] flex-col border-l border-slate-200 bg-white shadow-2xl">
      <header className="border-b border-slate-200 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-medium text-slate-950">Phase overview</h3>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              {project.name} · {summary?.total_count ?? 0} tasks · {summary?.completed_count ?? 0} completed
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="grid size-8 shrink-0 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-950">
            <X size={16}/>
          </button>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1.5 focus-within:border-blue-600">
            <Search size={14} className="shrink-0 text-slate-400" aria-hidden="true"/>
            <input
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder="Search phases…"
              aria-label="Search phases"
              className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-slate-400"
            />
          </label>
          <select
            value={status}
            onChange={event => setStatus(event.target.value)}
            aria-label="Filter phases by status"
            className="rounded-xl border border-slate-200 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700 outline-none focus:border-blue-600"
          >
            {STATUS_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)_3.5rem_minmax(4rem,7rem)_5.5rem] gap-2 border-b border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-500">
        <span>Phase</span><span>Tasks</span><span>Progress</span><span className="justify-self-end">Status</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {visible.length
          ? visible.map(phase => <PhaseRow
              key={phase.phase}
              phase={phase}
              expanded={expanded === phase.phase}
              onToggle={() => toggle(phase.phase)}
              tasks={tasksByPhase[phase.phase] || []}
              tasksLoading={tasksLoading && expanded === phase.phase}
              startDate={project.start_date}
            />)
          : <p className="px-4 py-10 text-center text-xs text-slate-400">
              {phases.length ? "No phases match this search or filter." : "No phase breakdown is available for this project."}
            </p>}
      </div>

      <footer className="border-t border-slate-200 px-4 py-2 text-xs text-slate-500">
        Showing {visible.length} of {phases.length} phases
      </footer>
    </section>
  </div>, document.body);
}
