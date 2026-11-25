import { ArrowUpDown, CheckCircle2, ClipboardCheck, ClipboardList, Clock3, PlayCircle, Search, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, LoadingSpinner, Pill } from "../../../components/ui";
import { formatDateShort } from "../../../utils/format";
import { STATUS_TONE } from "./TaskDetailContent";
import { executionCounts, matchesStatusBucket, plannedDayLabel } from "./executionViewHelpers";

const FILTER_CHIPS = [["all", "All"], ["in_progress", "In Progress"], ["ready", "Ready"], ["needs_review", "Needs Review"], ["delayed", "Delayed"], ["completed", "Completed"]];
const TILES = [
  ["total", "Total Assigned", ClipboardList, "blue"],
  ["in_progress", "In Progress", PlayCircle, "blue"],
  ["ready", "Ready", ShieldCheck, "green"],
  ["needs_review", "Needs Review", ClipboardCheck, "orange"],
  ["delayed", "Delayed", Clock3, "orange"],
  ["completed", "Completed", CheckCircle2, "green"],
];

// A deliberately conservative "what should this employee do next" label,
// computed from the list-item summary alone (not the full task detail) so
// this list never has to fetch every row's detail just to render itself.
// Every case here mirrors an authority TaskDetailContent's own
// forwardTargetsFor/canExecute would grant this actor once the row is open:
// the task list this component renders is already server-filtered to tasks
// this employee is actively support-assigned to (list_project_tasks), so the
// executor-gated transitions (start/submit) are legitimately theirs.
function nextActionFor(task) {
  if (task.lifecycle_status === "ready") return "Start work";
  if (task.lifecycle_status === "in_progress") return "Update progress";
  if (task.lifecycle_status === "rejected") return "Resume work";
  if (["submitted", "verified", "approval_pending"].includes(task.lifecycle_status)) return "Awaiting review";
  if (task.lifecycle_status === "planned") return "Mark ready";
  return "View details";
}

function Row({ task, onOpen }) {
  const late = task.variance?.status === "late";
  const dueDate = task.planned_end_date || task.planned_start_date;
  return <button type="button" onClick={() => onOpen(task.id)} className="grid w-full gap-2 border-b border-slate-100 px-4 py-3 text-left last:border-0 hover:bg-slate-50 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto_auto] sm:items-center sm:gap-4">
    <div className="min-w-0">
      <span className="tabular-nums text-xs font-medium text-slate-600">{task.original_code}</span>
      <strong className="block truncate text-sm font-medium text-slate-950">{task.title}</strong>
      <span className="text-xs text-slate-500">{[task.phase, task.category].filter(Boolean).join(" / ")}</span>
    </div>
    <span className="text-xs font-bold text-slate-500">{plannedDayLabel(task)}</span>
    <span className="flex flex-wrap items-center gap-1.5">
      <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
      {late && <Pill tone="orange">{task.variance.days}d late</Pill>}
    </span>
    <span className="text-xs font-bold text-slate-500">{dueDate ? formatDateShort(dueDate) : "—"}</span>
    <span className="text-xs font-medium text-blue-700">{nextActionFor(task)}</span>
  </button>;
}

// Internal Employee, list mode ("My Assigned Work"). Replaces the old Tasks
// tab for this role. Fetches the same server-scoped list the old
// TaskExecutionBoard fetched (list_project_tasks already restricts an
// internal_employee actor to their own active support assignments).
export function MyAssignedWorkList({ projectId, onOpenTask, onTasksLoaded }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [sortAsc, setSortAsc] = useState(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const items = await taskExecutionApi.list(projectId);
      setTasks(items);
      onTasksLoaded?.(items);
    } catch (caught) {
      setError(caught?.message || "Your assigned tasks could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId]);

  const counts = executionCounts(tasks);
  const term = search.trim().toLowerCase();
  const filtered = tasks.filter(task => {
    if (!matchesStatusBucket(task, filter)) return false;
    if (!term) return true;
    return [task.original_code, task.title, task.category, task.phase].some(value => value && value.toLowerCase().includes(term));
  });
  const sorted = [...filtered].sort((a, b) => {
    const left = a.planned_start_date || a.planned_end_date || "9999-12-31";
    const right = b.planned_start_date || b.planned_end_date || "9999-12-31";
    return sortAsc ? left.localeCompare(right) : right.localeCompare(left);
  });

  if (loading) return <div className="rounded-[20px] border border-line bg-white p-8"><LoadingSpinner label="Loading your assigned work..."/></div>;
  if (error) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm font-bold text-rose-700">{error}</div>;
  if (!tasks.length) return <EmptyState icon={<ClipboardList size={21}/>} title="No tasks assigned" description="No task is currently assigned to you on this project."/>;

  return <div className="grid gap-4">
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" role="group" aria-label="My work summary">
      {TILES.map(([key, label, Icon, tone]) => <article key={key} className="rounded-[20px] border border-line bg-white p-4">
        <div className="flex items-center gap-2 text-slate-500"><Icon size={16}/><small className="text-xs font-medium">{label}</small></div>
        <strong className="mt-2 block font-serif text-2xl text-slate-950">{counts[key]}</strong>
      </article>)}
    </div>

    <div className="grid gap-2 rounded-[20px] border border-line bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18}/>
          <input value={search} onChange={event => setSearch(event.target.value)} className="min-h-10 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" placeholder="Search task code, title, phase or category"/>
        </label>
        <Button size="sm" variant="ghost" onClick={() => setSortAsc(value => !value)}><ArrowUpDown size={14}/> Due date {sortAsc ? "↑" : "↓"}</Button>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        {FILTER_CHIPS.map(([key, label]) => <button
          key={key}
          type="button"
          aria-pressed={filter === key}
          onClick={() => setFilter(key)}
          className={`min-h-9 rounded-xl px-3 text-sm font-bold transition ${filter === key ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}
        >{label}</button>)}
      </div>
    </div>

    {sorted.length ? <div className="overflow-hidden rounded-[20px] border border-line bg-white">
      {sorted.map(task => <Row key={task.id} task={task} onOpen={onOpenTask}/>)}
    </div> : <EmptyState icon={<ClipboardList size={21}/>} title={`No ${filter.replaceAll("_", " ")} tasks`} description="Try a different filter or search term."/>}
  </div>;
}
