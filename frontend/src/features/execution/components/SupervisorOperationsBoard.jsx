import { CalendarClock, ClipboardCheck, Clock3, Rocket, Search, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, LoadingSpinner, Pill } from "../../../components/ui";
import { todayIso } from "../../../utils/format";
import { STATUS_TONE } from "./TaskDetailContent";
import { TaskDetailDrawer } from "./TaskDetailDrawer";
import { matchesTaskType, needsReview, startedEarlyDays, TASK_TYPE_FILTERS, taskOccupiesDay, todayAsDay } from "./executionViewHelpers";

const VISIBLE_PER_COLUMN = 5;

function offsetDay(day, delta) {
  const next = new Date(day);
  next.setUTCDate(next.getUTCDate() + delta);
  return next;
}

function columnLabel(date, kind) {
  const weekday = date.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  const formatted = date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  return { kind, formatted: `${weekday} ${formatted}` };
}

const ATTENTION_KEYS = [
  ["delayed", "Delayed", Clock3, task => task.variance?.status === "late"],
  ["started_early", "Started early", Rocket, task => startedEarlyDays(task) > 0],
  ["blocked", "Blocked", ShieldAlert, task => task.readiness?.state === "blocked"],
  ["needs_review", "Needs review", ClipboardCheck, needsReview],
  ["approval_pending", "Approval pending", ShieldCheck, task => task.lifecycle_status === "approval_pending"],
];

// Delayed and early-started tasks need to be seen first, not buried
// wherever their planned date happens to sort them - a Supervisor scanning
// a 5-task column for the one thing that actually needs attention
// shouldn't have to read past four routine cards to find it.
function attentionRank(task) {
  if (task.variance?.status === "late") return 0;
  if (startedEarlyDays(task) > 0) return 1;
  return 2;
}

export function sortByAttention(tasks) {
  return [...tasks].sort((a, b) => attentionRank(a) - attentionRank(b));
}

function TaskCard({ task, onOpen }) {
  const late = task.variance?.status === "late";
  const earlyDays = startedEarlyDays(task);
  return <button type="button" onClick={() => onOpen(task.id)}
    className={`relative grid w-full min-w-0 gap-1.5 overflow-hidden rounded-xl border border-line bg-white p-3 text-left transition hover:border-slate-300 hover:shadow-[0_2px_10px_rgba(21,23,26,.06)] ${late ? "pl-4" : ""}`}>
    {late && <span className="absolute inset-y-0 left-0 w-1 bg-behind" aria-hidden="true"/>}
    <span className="flex min-w-0 items-baseline gap-2">
      <span className="shrink-0 text-xs tabular-nums text-slate-400">{task.original_code}</span>
      <span className="min-w-0 flex-1 truncate text-sm text-slate-950">{task.title}</span>
    </span>
    <span className="flex flex-wrap items-center gap-1.5">
      <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
      {late && <Pill tone="orange">{task.variance.days}d late</Pill>}
      {earlyDays > 0 && <Pill tone="blue">{earlyDays}d early</Pill>}
      {task.category && <span className="truncate text-xs text-slate-500">{task.category}</span>}
    </span>
  </button>;
}

function DayColumn({ label, tasks, expanded, onExpand, onOpen, isToday }) {
  const visible = expanded ? tasks : tasks.slice(0, VISIBLE_PER_COLUMN);
  const remaining = tasks.length - visible.length;
  return <article aria-label={`${label.kind}, ${label.formatted}`} className={`grid min-w-0 gap-2 rounded-[20px] border p-3 ${isToday ? "border-slate-950 bg-white" : "border-line bg-white/60"}`}>
    <header className="flex items-baseline justify-between gap-2 px-1 pb-1">
      <span className={`text-[15px] ${isToday ? "font-medium text-slate-950" : "text-slate-700"}`}>{label.kind}</span>
      <span className="text-xs text-slate-500">{label.formatted} · {tasks.length} {tasks.length === 1 ? "task" : "tasks"}</span>
    </header>
    <div className="grid min-w-0 gap-2">
      {visible.length ? visible.map(task => <TaskCard key={task.id} task={task} onOpen={onOpen}/>) : <p className="rounded-xl border border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">No tasks</p>}
    </div>
    {remaining > 0 && <Button size="sm" variant="ghost" onClick={onExpand}>Show all {tasks.length}</Button>}
  </article>;
}

// Supervisor: the 3-day (Yesterday/Today/Tomorrow) operations board that
// replaces the old Tasks + Timeline tabs for this role. Fetches its own
// tasks and project membership, same pattern the old TaskExecutionBoard used.
export function SupervisorOperationsBoard({ projectId, user }) {
  const [tasks, setTasks] = useState([]);
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedColumns, setExpandedColumns] = useState(() => new Set());
  const [attentionFilter, setAttentionFilter] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const items = await taskExecutionApi.list(projectId);
      setTasks(items);
    } catch (caught) {
      setError(caught?.message || "The operations board could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId]);
  useEffect(() => {
    let active = true;
    setProject(null);
    projectsApi.detail(projectId).then(detail => { if (active) setProject(detail); }).catch(() => { if (active) setProject(null); });
    return () => { active = false; };
  }, [projectId]);
  useEffect(() => { setExpandedColumns(new Set()); setAttentionFilter(null); setSearch(""); setTypeFilter("all"); }, [projectId]);

  const today = todayAsDay();
  const candidates = (project?.memberships || []).filter(m => m.project_role === "internal_employee");
  const selectedTask = tasks.find(task => task.id === selectedTaskId) || null;

  const term = search.trim().toLowerCase();
  const searchedTasks = useMemo(() => {
    const typed = tasks.filter(task => matchesTaskType(task, typeFilter));
    if (!term) return typed;
    return typed.filter(task => [task.original_code, task.title, task.category, task.phase].some(value => value && value.toLowerCase().includes(term)));
  }, [tasks, term, typeFilter]);

  const columns = useMemo(() => {
    if (!today) return [];
    return [
      { key: "yesterday", day: offsetDay(today, -1), kind: "Yesterday" },
      { key: "today", day: today, kind: "Today" },
      { key: "tomorrow", day: offsetDay(today, 1), kind: "Tomorrow" },
    ].map(({ key, day, kind }) => ({
      key,
      label: columnLabel(day, kind),
      tasks: sortByAttention(searchedTasks.filter(task => taskOccupiesDay(task, day, today))),
    }));
  }, [searchedTasks, today]);

  // Attention Required is scoped to the same window the board shows - the
  // union of tasks appearing in any of the three columns, not the whole
  // project - since this board answers "what needs attention right now,"
  // not "what needs attention eventually."
  const windowTasks = useMemo(() => {
    const seen = new Map();
    for (const column of columns) for (const task of column.tasks) seen.set(task.id, task);
    return Array.from(seen.values());
  }, [columns]);

  const attentionCounts = ATTENTION_KEYS.map(([key, label, Icon, predicate]) => ({
    key, label, Icon, count: windowTasks.filter(predicate).length,
  }));

  const visibleColumns = attentionFilter
    ? columns.map(column => ({ ...column, tasks: column.tasks.filter(ATTENTION_KEYS.find(([key]) => key === attentionFilter)[3]) }))
    : columns;

  function toggleExpand(key) {
    setExpandedColumns(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  if (loading) return <div className="rounded-[20px] border border-line bg-white p-8"><LoadingSpinner label="Loading operations board..."/></div>;
  if (error) return <div className="rounded-[20px] border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">{error}</div>;
  if (!tasks.length) return <EmptyState icon={<CalendarClock size={21}/>} title="No execution tasks yet" description="This project's baseline has no tasks to execute."/>;

  const flagged = attentionCounts.filter(item => item.count > 0);
  const todayLabel = new Date(`${todayIso()}T00:00:00Z`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

  return <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-[17px] font-medium text-slate-950">3-Day Operations Board</h3>
        <p className="mt-0.5 text-sm text-slate-500">{todayLabel} · {windowTasks.length} {windowTasks.length === 1 ? "task" : "tasks"} from yesterday to tomorrow</p>
      </div>
    </header>

    <div className="flex flex-wrap items-center gap-2 rounded-[20px] border border-line bg-white p-2">
      <label className="relative min-w-[200px] flex-1">
        <span className="sr-only">Search tasks</span>
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
        <input value={search} onChange={event => setSearch(event.target.value)} autoComplete="off" placeholder="Search code, title, phase or trade"
          className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-950 outline-none placeholder:text-slate-400 focus:border-blue-600 focus:bg-white"/>
      </label>
      <select value={typeFilter} onChange={event => setTypeFilter(event.target.value)} aria-label="Filter by task type"
        className={`h-9 rounded-lg border bg-white px-2.5 text-sm outline-none focus:border-blue-600 ${typeFilter !== "all" ? "border-slate-950 text-slate-950" : "border-slate-200 text-slate-700"}`}>
        {TASK_TYPE_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select>
      <section aria-label="Attention required" className="flex flex-wrap items-center gap-1.5">
        {flagged.length === 0
          ? <span className="px-1 text-sm text-ok">Nothing needs attention</span>
          : attentionCounts.filter(item => item.count > 0 || attentionFilter === item.key).map(({ key, label, Icon, count }) => <button key={key} type="button"
              onClick={() => setAttentionFilter(attentionFilter === key ? null : key)} aria-pressed={attentionFilter === key}
              className={`inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-[13px] transition ${attentionFilter === key ? "bg-slate-950 text-white" : "bg-orange-50 text-orange-800 hover:bg-orange-100"}`}>
              <Icon size={14} aria-hidden="true"/> {count} {label}
            </button>)}
        {attentionFilter && <button type="button" onClick={() => setAttentionFilter(null)} className="px-1 text-sm text-blue-700 hover:underline">Clear</button>}
      </section>
    </div>

    {/* items-start: a grid row would otherwise stretch every column to the
        tallest one, leaving uneven gaps once "Show all" makes them differ. */}
    <div className="grid items-start gap-3 md:grid-cols-3">
      {visibleColumns.map(column => <DayColumn
        key={column.key}
        label={column.label}
        tasks={column.tasks}
        isToday={column.key === "today"}
        expanded={expandedColumns.has(column.key)}
        onExpand={() => toggleExpand(column.key)}
        onOpen={setSelectedTaskId}
      />)}
    </div>

    {selectedTask && <TaskDetailDrawer
      key={selectedTask.id}
      projectId={projectId}
      project={project}
      task={selectedTask}
      user={user}
      candidates={candidates}
      onClose={() => setSelectedTaskId(null)}
      onChanged={load}
    />}
  </div>;
}
