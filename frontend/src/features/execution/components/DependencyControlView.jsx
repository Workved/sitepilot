import {
  ArrowLeftRight, CalendarRange, CheckCircle2, Eye, GitBranch, GitCommitHorizontal,
  MoreHorizontal, RotateCcw, Search, ShieldAlert, ShieldQuestion, Workflow, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, LoadingSpinner, Pill, Select } from "../../../components/ui";
import { formatDateShort } from "../../../utils/format";
import { DEPENDENCY_TYPE_LABEL, STATUS_TONE } from "./TaskDetailContent";
import { TaskDetailDrawer } from "./TaskDetailDrawer";

// A dependency's LIVE status - not the static `blocking` flag the planning
// endpoint carries (whether a PM marked this edge as gating at all), but
// whether the condition it describes is actually met right now, computed
// from the predecessor's real lifecycle_status. Mirrors the same rule the
// backend readiness engine already enforces:
//  - Finish-to-Start: the successor can't start until the predecessor is
//    done (completed, or verified and just awaiting PM approval).
//  - Start-to-Start: the successor can start once the predecessor has
//    actually started - not merely scheduled.
// Never guessed: a predecessor this project's execution list doesn't (yet)
// carry a lifecycle_status for status is "unknown", not silently blocking or
// satisfied.
const FINISH_TO_START_SATISFIED = new Set(["completed", "verified"]);
const START_TO_START_SATISFIED = new Set(["in_progress", "submitted", "verified", "approval_pending", "completed"]);

function dependencyStatus(dependencyType, predecessorTask) {
  if (!predecessorTask?.lifecycle_status) return "unknown";
  if (dependencyType === "finish_to_start") return FINISH_TO_START_SATISFIED.has(predecessorTask.lifecycle_status) ? "satisfied" : "blocking";
  if (dependencyType === "start_to_start") return START_TO_START_SATISFIED.has(predecessorTask.lifecycle_status) ? "satisfied" : "blocking";
  return "unknown";
}

const STATUS_CHIP = {
  satisfied: { tone: "green", label: "Satisfied", Icon: CheckCircle2 },
  blocking: { tone: "red", label: "Blocking", Icon: ShieldAlert },
  unknown: { tone: "gray", label: "Unknown", Icon: ShieldQuestion },
};

const TYPE_CHIP_TONE = { finish_to_start: "blue", start_to_start: "violet" };

const WHY_BLOCKING_TEXT = {
  finish_to_start: "The successor task cannot start until the predecessor task is completed.",
  start_to_start: "The successor task can start once the predecessor task has started.",
};

function humanizeStatus(value) {
  if (!value) return "—";
  const spaced = String(value).replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function TaskStatusChip({ task }) {
  if (!task) return <Pill tone="gray">Unknown</Pill>;
  return <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{humanizeStatus(task.lifecycle_status)}</Pill>;
}

function TaskRef({ code, title, task }) {
  return <div className="min-w-0">
    <span className="font-mono text-xs font-black text-blue-700">{code}</span>
    <div className="truncate text-sm font-bold text-slate-900">{title}</div>
    {task && <div className="truncate text-xs text-slate-400">{[task.phase, task.category].filter(Boolean).join(" / ") || "Unphased"}</div>}
  </div>;
}

function KpiCard({ icon: Icon, tone, value, label }) {
  return <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_10px_28px_rgba(27,47,76,0.065)]">
    <span className={`grid size-9 place-items-center rounded-xl ${tone}`}><Icon size={17}/></span>
    <strong className="mt-3 block font-serif text-3xl text-slate-950">{value}</strong>
    <p className="m-0 mt-1 text-xs font-bold text-slate-500">{label}</p>
  </article>;
}

const STATUS_FILTERS = [["all", "All"], ["blocking", "Blocking"], ["satisfied", "Satisfied"]];
const TYPE_FILTERS = [["all", "All"], ["finish_to_start", "Finish-to-Start"], ["start_to_start", "Start-to-Start"]];

const PAGE_SIZE = 6;

// The dependency detail overlay - same large right-side drawer chrome as
// TaskDetailDrawer (backdrop, fixed w-[820px] aside, body scroll lock), so a
// dependency's detail no longer competes for space with the table in a small
// sticky sidebar. Read-only for every role that reaches this tab (Admin, PM,
// Super Admin, Supervisor) - the only actions are jumping to either task's
// own TaskDetailDrawer, never duplicated here.
function DependencyDetailDrawer({ dependency, onClose, onOpenTask }) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, []);

  const chip = STATUS_CHIP[dependency.status];

  return <>
    <div className="fixed inset-0 z-40 bg-slate-950/40" onClick={onClose} aria-hidden="true"/>
    <aside
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[90vw] flex-col rounded-l-2xl bg-white shadow-[-16px_0_50px_rgba(15,23,42,.18)] sm:w-[820px]"
      aria-label={`Dependency detail - ${dependency.predecessor_code} to ${dependency.successor_code}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-6 py-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500"><GitBranch size={14}/> Dependency Detail</div>
          <h2 className="mt-1 text-lg font-black leading-snug text-slate-950">{dependency.predecessor_code} &rarr; {dependency.successor_code}</h2>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Pill tone={chip.tone}><chip.Icon size={11}/> {chip.label}</Pill>
            <Pill tone={TYPE_CHIP_TONE[dependency.dependency_type] || "gray"}>{DEPENDENCY_TYPE_LABEL[dependency.dependency_type] || humanizeStatus(dependency.dependency_type)}</Pill>
            {dependency.excluded_task_warning && <Pill tone="orange">Excluded task</Pill>}
          </div>
        </div>
        <button type="button" aria-label="Close dependency detail" onClick={onClose} className="shrink-0 rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">
          <X size={20}/>
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/60 px-6 py-5">
        <div className="grid gap-4">
          <section>
            <h4 className="text-xs font-medium text-slate-500">Predecessor Task</h4>
            <div className="mt-1 flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-3">
              <TaskRef code={dependency.predecessor_code} title={dependency.predecessor_title} task={dependency.predecessorTask}/>
              <TaskStatusChip task={dependency.predecessorTask}/>
            </div>
          </section>

          <section>
            <h4 className="text-xs font-medium text-slate-500">Successor Task</h4>
            <div className="mt-1 flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-3">
              <TaskRef code={dependency.successor_code} title={dependency.successor_title} task={dependency.successorTask}/>
              <TaskStatusChip task={dependency.successorTask}/>
            </div>
          </section>

          <section>
            <h4 className="text-xs font-medium text-slate-500">Dependency Type</h4>
            <Pill tone={TYPE_CHIP_TONE[dependency.dependency_type] || "gray"} className="mt-1">{DEPENDENCY_TYPE_LABEL[dependency.dependency_type] || humanizeStatus(dependency.dependency_type)}</Pill>
          </section>

          <section>
            <h4 className="text-xs font-medium text-slate-500">Impact</h4>
            <p className="mt-1 text-sm text-slate-700">{dependency.impact ? `${dependency.impact} task${dependency.impact === 1 ? " is" : "s are"} waiting on this dependency.` : "Impact not calculated."}</p>
          </section>

          <section>
            <h4 className="text-xs font-medium text-slate-500">{dependency.status === "satisfied" ? "Status" : "Why is this blocking?"}</h4>
            {dependency.status === "satisfied" && <p className="mt-1 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-bold text-emerald-800">Dependency condition is satisfied.</p>}
            {dependency.status === "blocking" && <p className="mt-1 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-bold text-rose-800">{WHY_BLOCKING_TEXT[dependency.dependency_type] || "This dependency's condition has not been met yet."}</p>}
            {dependency.status === "unknown" && <p className="mt-1 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-bold text-slate-600">The predecessor task's current status isn't available, so this can't be determined yet.</p>}
          </section>

          <section>
            <h4 className="text-xs font-medium text-slate-500">Dates</h4>
            <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
              <dt className="text-slate-400">Planned Start (Predecessor)</dt><dd className="text-right font-bold text-slate-700">{dependency.predecessorTask ? formatDateShort(dependency.predecessorTask.planned_start_date) : "—"}</dd>
              <dt className="text-slate-400">Planned Finish (Predecessor)</dt><dd className="text-right font-bold text-slate-700">{dependency.predecessorTask ? formatDateShort(dependency.predecessorTask.planned_end_date) : "—"}</dd>
              <dt className="text-slate-400">Planned Start (Successor)</dt><dd className="text-right font-bold text-slate-700">{dependency.successorTask ? formatDateShort(dependency.successorTask.planned_start_date) : "—"}</dd>
              <dt className="text-slate-400">Planned Finish (Successor)</dt><dd className="text-right font-bold text-slate-700">{dependency.successorTask ? formatDateShort(dependency.successorTask.planned_end_date) : "—"}</dd>
            </dl>
          </section>
        </div>
      </div>

      {/* Not a "View Both" button: only one task detail overlay can be open
          at a time, so a button claiming to open both would be a UI that
          doesn't do what it says. */}
      <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 bg-white px-6 py-4">
        <Button size="sm" variant="secondary" disabled={!dependency.predecessorTask} title={!dependency.predecessorTask ? "This task hasn't been instantiated for execution yet." : undefined} onClick={() => onOpenTask("predecessor")}>View Predecessor Task</Button>
        <Button size="sm" variant="secondary" disabled={!dependency.successorTask} title={!dependency.successorTask ? "This task hasn't been instantiated for execution yet." : undefined} onClick={() => onOpenTask("successor")}>View Successor Task</Button>
      </footer>
    </aside>
  </>;
}

// Admin/PM/Super Admin/Supervisor: the "Task Dependencies" control view that
// replaces the old flat "Task A | Finish To Start | Task B" list. Internal
// Employee never reaches this component at all - ExecutionPage's own tab
// list already hides "Dependencies" for that role (dependency-blocking
// reasons still surface inside the task drawer's Overview tab instead).
// Supervisor gets the exact same unscoped list Admin/PM see: there is no
// existing backend scoping of dependencies to a Supervisor's 3-day window,
// and inventing a client-side one here would just hide dependencies a
// Supervisor legitimately needs to see coming.
export function DependencyControlView({ projectId, project, user, dependencies }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [phaseFilter, setPhaseFilter] = useState("all");
  const [selectedId, setSelectedId] = useState(null);
  const [openDrawerTaskId, setOpenDrawerTaskId] = useState(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const items = await taskExecutionApi.list(projectId);
      setTasks(items);
    } catch (caught) {
      setError(caught?.message || "The execution task list could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId]);
  useEffect(() => { setSelectedId(null); setOpenDrawerTaskId(null); }, [projectId]);
  useEffect(() => { setVisibleCount(PAGE_SIZE); }, [search, typeFilter, statusFilter, phaseFilter, projectId]);

  const candidates = (project?.memberships || []).filter(m => m.project_role === "internal_employee");

  // Dependency items reference PLANNING-layer task ids (V2ProjectTask), not
  // the EXECUTION-layer task ids this list carries - the two are different
  // tables materialized at different times. `original_code` is the one
  // identifier stable and unique across both, so it's the safe join key
  // here, never a raw uuid comparison.
  const taskByCode = useMemo(() => {
    const map = new Map();
    for (const task of tasks) map.set(task.original_code, task);
    return map;
  }, [tasks]);

  const items = dependencies?.items || [];
  const enriched = useMemo(() => items.map(dep => {
    const predecessorTask = taskByCode.get(dep.predecessor_code) || null;
    const successorTask = taskByCode.get(dep.successor_code) || null;
    const status = dependencyStatus(dep.dependency_type, predecessorTask);
    // A real, derivable number: how many successor tasks (including this
    // row) wait on the SAME predecessor across every dependency this
    // project has - not a fabricated "impact" estimate.
    const impact = items.filter(other => other.predecessor_code === dep.predecessor_code).length;
    return { ...dep, predecessorTask, successorTask, status, impact };
  }), [items, taskByCode]);

  const counts = useMemo(() => ({
    total: enriched.length,
    finishToStart: enriched.filter(d => d.dependency_type === "finish_to_start").length,
    startToStart: enriched.filter(d => d.dependency_type === "start_to_start").length,
    blocking: enriched.filter(d => d.status === "blocking").length,
    satisfied: enriched.filter(d => d.status === "satisfied").length,
  }), [enriched]);

  const phases = useMemo(() => Array.from(new Set(tasks.map(t => t.phase).filter(Boolean))), [tasks]);

  const term = search.trim().toLowerCase();
  const filtered = enriched.filter(dep => {
    if (typeFilter !== "all" && dep.dependency_type !== typeFilter) return false;
    if (statusFilter !== "all" && dep.status !== statusFilter) return false;
    if (phaseFilter !== "all" && dep.predecessorTask?.phase !== phaseFilter && dep.successorTask?.phase !== phaseFilter) return false;
    if (!term) return true;
    return [dep.predecessor_code, dep.predecessor_title, dep.successor_code, dep.successor_title].some(v => v && v.toLowerCase().includes(term));
  });

  const selected = enriched.find(d => d.id === selectedId) || null;
  const drawerTask = openDrawerTaskId === "predecessor" ? selected?.predecessorTask : openDrawerTaskId === "successor" ? selected?.successorTask : null;
  const visibleItems = filtered.slice(0, visibleCount);
  const hasMore = filtered.length > visibleItems.length;
  const canShowLess = visibleCount > PAGE_SIZE;
  const filtersActive = Boolean(search.trim()) || typeFilter !== "all" || statusFilter !== "all" || phaseFilter !== "all";

  function resetFilters() {
    setSearch("");
    setTypeFilter("all");
    setStatusFilter("all");
    setPhaseFilter("all");
  }

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading dependencies..."/></div>;
  if (error) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm font-bold text-rose-700">{error}</div>;

  return <div className="grid gap-4">
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="font-serif text-xl text-slate-950">Task Dependencies</h2>
        <p className="mt-0.5 max-w-2xl text-sm text-slate-500">Understand how tasks are related and which dependencies are blocking execution.</p>
      </div>
      <div className="flex items-center gap-1.5">
        <button type="button" aria-label="Calendar view" title="Open the Execution Calendar for date context" className="rounded-lg border border-slate-200 bg-white p-2 text-slate-500 transition hover:bg-slate-50"><CalendarRange size={16}/></button>
        <button type="button" aria-label="More options" className="rounded-lg border border-slate-200 bg-white p-2 text-slate-500 transition hover:bg-slate-50"><MoreHorizontal size={16}/></button>
      </div>
    </div>

    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5" role="group" aria-label="Dependency summary">
      <KpiCard icon={Workflow} tone="bg-blue-50 text-blue-700" value={counts.total} label="Total Dependencies"/>
      <KpiCard icon={ArrowLeftRight} tone="bg-blue-50 text-blue-700" value={counts.finishToStart} label="Finish-to-Start"/>
      <KpiCard icon={GitCommitHorizontal} tone="bg-violet-50 text-violet-700" value={counts.startToStart} label="Start-to-Start"/>
      <KpiCard icon={ShieldAlert} tone="bg-rose-50 text-rose-700" value={counts.blocking} label="Blocking"/>
      <KpiCard icon={CheckCircle2} tone="bg-emerald-50 text-emerald-700" value={counts.satisfied} label="Satisfied"/>
    </div>

    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
      <label className="relative min-w-[220px] flex-1">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18}/>
        <input value={search} onChange={e => setSearch(e.target.value)} className="min-h-10 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" placeholder="Search by task code or title"/>
      </label>
      <Select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} aria-label="Filter by dependency type" className="min-h-10 w-auto min-w-[160px]">
        {TYPE_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </Select>
      <Select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} aria-label="Filter by dependency status" className="min-h-10 w-auto min-w-[140px]">
        {STATUS_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </Select>
      <Select value={phaseFilter} onChange={e => setPhaseFilter(e.target.value)} aria-label="Filter by phase" className="min-h-10 w-auto min-w-[140px]">
        <option value="all">All phases</option>
        {phases.map(phase => <option key={phase} value={phase}>{phase}</option>)}
      </Select>
      <button type="button" onClick={resetFilters} disabled={!filtersActive} className="flex min-h-10 items-center gap-1.5 rounded-xl px-3 text-sm font-bold text-slate-500 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40">
        <RotateCcw size={14}/> Reset Filters
      </button>
    </div>

    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Quick dependency filters">
      {[
        ["all", "All", enriched.length, () => { setStatusFilter("all"); setTypeFilter("all"); }, statusFilter === "all" && typeFilter === "all"],
        ["blocking", "Blocking", counts.blocking, () => setStatusFilter(statusFilter === "blocking" ? "all" : "blocking"), statusFilter === "blocking"],
        ["satisfied", "Satisfied", counts.satisfied, () => setStatusFilter(statusFilter === "satisfied" ? "all" : "satisfied"), statusFilter === "satisfied"],
        ["fs", "Finish-to-Start", counts.finishToStart, () => setTypeFilter(typeFilter === "finish_to_start" ? "all" : "finish_to_start"), typeFilter === "finish_to_start"],
        ["ss", "Start-to-Start", counts.startToStart, () => setTypeFilter(typeFilter === "start_to_start" ? "all" : "start_to_start"), typeFilter === "start_to_start"],
      ].map(([key, label, count, onClick, active]) => (
        <button key={key} type="button" onClick={onClick} aria-pressed={active} className={`rounded-full px-3 py-1.5 text-xs font-bold transition ${active ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
          {label} ({count})
        </button>
      ))}
    </div>

    {!filtered.length ? (
      <EmptyState icon={<GitBranch size={21}/>} title={items.length ? "No dependencies match" : "No dependencies were generated for this project"} description={items.length ? "Try a different search or filter." : undefined}/>
    ) : (
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs font-medium text-slate-500">
                <th className="px-4 py-3 font-black">Predecessor Task</th>
                <th className="px-4 py-3 font-black">Dependency Type</th>
                <th className="px-4 py-3 font-black">Successor Task</th>
                <th className="px-4 py-3 font-black">Predecessor Status</th>
                <th className="px-4 py-3 font-black">Dependency Status</th>
                <th className="px-4 py-3 font-black">Impact</th>
                <th className="px-4 py-3 font-black">Action</th>
              </tr>
            </thead>
            <tbody>
              {visibleItems.map(dep => {
                const chip = STATUS_CHIP[dep.status];
                return <tr key={dep.id} onClick={() => setSelectedId(dep.id)} className={`cursor-pointer border-b border-slate-50 transition last:border-0 hover:bg-blue-50/40 ${selectedId === dep.id ? "bg-blue-50/70" : ""}`}>
                  <td className="px-4 py-3 align-top"><TaskRef code={dep.predecessor_code} title={dep.predecessor_title} task={dep.predecessorTask}/></td>
                  <td className="px-4 py-3 align-top"><Pill tone={TYPE_CHIP_TONE[dep.dependency_type] || "gray"}>{DEPENDENCY_TYPE_LABEL[dep.dependency_type] || humanizeStatus(dep.dependency_type)}</Pill></td>
                  <td className="px-4 py-3 align-top"><TaskRef code={dep.successor_code} title={dep.successor_title} task={dep.successorTask}/></td>
                  <td className="px-4 py-3 align-top"><TaskStatusChip task={dep.predecessorTask}/></td>
                  <td className="px-4 py-3 align-top"><Pill tone={chip.tone}><chip.Icon size={11}/> {chip.label}</Pill>{dep.excluded_task_warning && <Pill tone="orange" className="ml-1">Excluded task</Pill>}</td>
                  <td className="px-4 py-3 align-top font-bold text-slate-700">{dep.impact || "—"}</td>
                  <td className="px-4 py-3 align-top">
                    <button type="button" onClick={event => { event.stopPropagation(); setSelectedId(dep.id); }} aria-label={`View dependency between ${dep.predecessor_code} and ${dep.successor_code}`} className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-bold text-slate-600 transition hover:bg-slate-100">
                      <Eye size={13}/> View
                    </button>
                  </td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>
        {(hasMore || canShowLess) && <div className="flex items-center justify-center gap-3 border-t border-slate-100 px-4 py-3">
          {hasMore && <Button size="sm" variant="secondary" onClick={() => setVisibleCount(count => count + PAGE_SIZE)}>Load More</Button>}
          {canShowLess && <Button size="sm" variant="ghost" onClick={() => setVisibleCount(PAGE_SIZE)}>Show Less</Button>}
        </div>}
      </div>
    )}

    {selected && <DependencyDetailDrawer key={selected.id} dependency={selected} onClose={() => setSelectedId(null)} onOpenTask={setOpenDrawerTaskId}/>}

    {drawerTask && <TaskDetailDrawer
      key={drawerTask.id}
      projectId={projectId}
      project={project}
      task={drawerTask}
      user={user}
      candidates={candidates}
      onClose={() => setOpenDrawerTaskId(null)}
      onChanged={load}
    />}
  </div>;
}
