import { CalendarClock, ClipboardCheck, Clock3, Rocket, Search, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, LoadingSpinner, Pill, Select } from "../../../components/ui";
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
  const formatted = date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  return { kind, formatted: `${formatted} (${weekday})` };
}

const ATTENTION_KEYS = [
  ["delayed", "Delayed", Clock3, task => task.variance?.status === "late"],
  ["started_early", "Started Early", Rocket, task => startedEarlyDays(task) > 0],
  ["blocked", "Blocked", ShieldAlert, task => task.readiness?.state === "blocked"],
  ["needs_review", "Needs Review", ClipboardCheck, needsReview],
  ["approval_pending", "Approval Pending", ShieldCheck, task => task.lifecycle_status === "approval_pending"],
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
  return <button type="button" onClick={() => onOpen(task.id)} className="grid w-full min-w-0 gap-1 rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:border-blue-300 hover:shadow-sm">
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <span className="font-mono text-[11px] font-black text-blue-700">{task.original_code}</span>
      <span className="min-w-0 flex-1 truncate text-sm font-bold text-slate-900">{task.title}</span>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      {task.category && <span className="text-xs text-slate-500">{task.category}</span>}
      <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
      {late && <Pill tone="orange">{task.variance.days}d late</Pill>}
      {earlyDays > 0 && <Pill tone="blue">{earlyDays}d early</Pill>}
    </div>
  </button>;
}

function DayColumn({ label, tasks, expanded, onExpand, onOpen }) {
  const visible = expanded ? tasks : tasks.slice(0, VISIBLE_PER_COLUMN);
  const remaining = tasks.length - visible.length;
  return <article className="grid min-w-0 gap-2 rounded-2xl border border-slate-200 bg-slate-50/60 p-3">
    <header className="text-center">
      <div className="text-xs font-medium text-slate-500">{label.kind}</div>
      <div className="text-xs font-bold text-slate-700">{label.formatted}</div>
    </header>
    <div className="grid min-w-0 gap-2">
      {visible.length ? visible.map(task => <TaskCard key={task.id} task={task} onOpen={onOpen}/>) : <p className="rounded-xl border border-dashed border-slate-200 bg-white p-3 text-center text-xs text-slate-400">No tasks</p>}
    </div>
    {remaining > 0 && <Button size="sm" variant="ghost" onClick={onExpand}>View all ({tasks.length})</Button>}
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

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading operations board..."/></div>;
  if (error) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm font-bold text-rose-700">{error}</div>;
  if (!tasks.length) return <EmptyState icon={<CalendarClock size={21}/>} title="No execution tasks yet" description="This project's baseline has no tasks to execute."/>;

  {/* TaskDetailDrawer is a fixed-position overlay now, not a split column -
      no grid-cols split needed to host it. */}
  return <div className="grid gap-4">
    <div className="grid min-w-0 gap-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 flex items-center gap-2 font-serif text-lg text-slate-950"><CalendarClock size={18}/> 3-Day Operations Board</h3>
        <span className="text-xs font-bold text-slate-500">Today: {new Date(`${todayIso()}T00:00:00Z`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" })}</span>
      </header>

      <div className="flex flex-wrap items-center gap-2">
      <label className="relative min-w-[200px] flex-1">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18}/>
        <input value={search} onChange={event => setSearch(event.target.value)} className="min-h-10 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" placeholder="Search task code, title, phase or category"/>
      </label>
      <Select value={typeFilter} onChange={event => setTypeFilter(event.target.value)} aria-label="Filter by task type" className="min-h-10 w-auto min-w-[150px]">
        {TASK_TYPE_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </Select>
      </div>

      {/* items-start: without it, a CSS Grid row stretches every column to
          match its tallest sibling by default. Each DayColumn is itself a
          2-row grid (header, task list) with no fixed row heights, so once
          "View all" made the columns' real task counts diverge, the leftover
          stretch height landed as an uneven gap between a shorter column's
          header and its first card instead of just trailing empty space
          below it. Before expansion this was invisible - all columns are
          capped at VISIBLE_PER_COLUMN and stay nearly the same height. */}
      <div className="grid items-start gap-3 sm:grid-cols-3">
        {visibleColumns.map(column => <DayColumn
          key={column.key}
          label={column.label}
          tasks={column.tasks}
          expanded={expandedColumns.has(column.key)}
          onExpand={() => toggleExpand(column.key)}
          onOpen={setSelectedTaskId}
        />)}
      </div>

      <section className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4" aria-label="Attention required">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-medium text-amber-800">Attention Required</h4>
          {attentionFilter && <button type="button" onClick={() => setAttentionFilter(null)} className="text-xs font-bold text-blue-700 hover:underline">Clear filter</button>}
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {attentionCounts.map(({ key, label, Icon, count }) => (
            <button
              key={key}
              type="button"
              onClick={() => setAttentionFilter(attentionFilter === key ? null : key)}
              aria-pressed={attentionFilter === key}
              className={`flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-bold transition ${attentionFilter === key ? "border-amber-600 bg-amber-600 text-white" : "border-amber-200 bg-white text-amber-800 hover:bg-amber-100"}`}
            >
              <Icon size={13}/> {count} {label}
            </button>
          ))}
          {attentionCounts.every(item => item.count === 0) && <span className="text-xs font-bold text-emerald-700">Nothing needs attention right now.</span>}
        </div>
      </section>
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
