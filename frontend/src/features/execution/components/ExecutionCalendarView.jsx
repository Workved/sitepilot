import { BarChart3, CalendarDays, Check, Diamond, Info, RotateCcw, Search, SlidersHorizontal, Target, ZoomIn } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { targetsApi } from "../../../api/targetsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { EmptyState, LoadingSpinner } from "../../../components/ui";
import { MonthCalendar } from "./calendar/MonthCalendar";
import { ProjectGantt } from "./calendar/ProjectGantt";
import { ProjectTargetModal, TargetsList, targetSummary } from "./calendar/TargetsPanel";
import { TaskDetailDrawer } from "./TaskDetailDrawer";
import { executionCounts, matchesStatusBucket, matchesTaskType, TASK_TYPE_FILTERS, todayAsDay } from "./executionViewHelpers";

// The Execution calendar: two views of the same project's work.
//  - Gantt: tasks on a timeline (plan vs actual, lateness, dependencies);
//  - Month: a month grid of what starts, is due, finishes or is late.
// Cross-project comparison lives on the Portfolio page. Clicking a task
// opens its detail drawer.

const VIEWS = [
  { key: "gantt", label: "Gantt", Icon: BarChart3 },
  { key: "month", label: "Month", Icon: CalendarDays },
];
const GANTT_ZOOM_LABELS = [["day", "Day"], ["week", "Week"], ["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]];
const VIEW_KEY = "siteops.calendarView";

function rememberedView() {
  try { return VIEWS.some(v => v.key === window.localStorage.getItem(VIEW_KEY)) ? window.localStorage.getItem(VIEW_KEY) : "gantt"; } catch { return "gantt"; }
}

// Zoom is set once and rarely changed, so it is one compact menu, not a
// five-button bar competing with the filters for attention.
function ZoomMenu({ value, options, onChange }) {
  const current = options.find(([key]) => key === value)?.[1];
  return <Popover label={current} icon={ZoomIn} ariaLabel={`Zoom: ${current}. Change zoom`} width="w-40">
    {close => <div role="group" aria-label="Zoom" className="grid gap-0.5">
      {options.map(([key, text]) => <button key={key} type="button" aria-pressed={value === key} onClick={() => { onChange(key); close(); }}
        className={`flex h-9 items-center justify-between rounded-lg px-2.5 text-left text-sm ${value === key ? "bg-slate-100 text-slate-950" : "text-slate-600 hover:bg-slate-50"}`}>{text}{value === key && <Check size={15} aria-hidden="true"/>}</button>)}
    </div>}
  </Popover>;
}

// A small anchored panel that closes on outside click or Escape.
function Popover({ label, icon: Icon, badge, children, align = "right", ariaLabel, iconOnly = false, width = "w-72" }) {
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
  return <div ref={holder} className="relative">
    <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} aria-haspopup="true" aria-label={ariaLabel} title={iconOnly ? label : undefined}
      className={`flex h-9 items-center gap-1.5 rounded-lg border text-[13px] transition-colors ${iconOnly ? "w-9 justify-center" : "px-3"} ${badge ? "border-slate-950 text-slate-950" : "border-slate-200 text-slate-700 hover:border-slate-300"} bg-white`}>
      <Icon size={15} aria-hidden="true"/>{!iconOnly && label}{badge ? <span className="grid h-5 min-w-5 place-items-center rounded-md bg-slate-950 px-1 text-xs text-white">{badge}</span> : null}
    </button>
    {open && <div className={`absolute top-[calc(100%+6px)] z-30 rounded-2xl border border-line bg-white p-2 shadow-[0_18px_50px_rgba(21,23,26,.12)] ${width} ${align === "right" ? "right-0" : "left-0"}`}>{typeof children === "function" ? children(() => setOpen(false)) : children}</div>}
  </div>;
}

const LEGEND = [
  ["bg-blue-600", "In progress"],
  ["bg-emerald-600", "Done"],
  ["bg-violet-600", "Needs review"],
  ["bg-rose-600", "Blocked, or past the plan"],
  ["bg-slate-500", "Started, not yet active"],
];

const STAT_DOTS = { total: "bg-slate-400", ready: "bg-emerald-500", in_progress: "bg-blue-600", needs_review: "bg-violet-500", completed: "bg-emerald-600", delayed: "bg-orange-500", blocked: "bg-rose-600" };

export function ExecutionCalendarView({ projectId, user }) {
  const [view, setView] = useState(rememberedView);
  const [tasks, setTasks] = useState([]);
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [phaseFilter, setPhaseFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [vendorFilter, setVendorFilter] = useState("all");
  // Day view by default: the Gantt opens on today's work at full detail.
  const [ganttZoom, setGanttZoom] = useState("day");
  const [todaySignal, setTodaySignal] = useState(0);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [targets, setTargets] = useState([]);
  const [canAddTargets, setCanAddTargets] = useState(false);
  const [changes, setChanges] = useState([]);
  const [onlyTargets, setOnlyTargets] = useState(false);
  const [addingTarget, setAddingTarget] = useState(false);
  const today = useMemo(() => todayAsDay(), []);

  function chooseView(next) {
    setView(next);
    try { window.localStorage.setItem(VIEW_KEY, next); } catch { /* per-viewer convenience only */ }
  }

  // Targets and reschedule history are extras: the calendar still works
  // if either can't be loaded.
  function loadExtras() {
    targetsApi.list(projectId).then(data => { setTargets(data.items || []); setCanAddTargets(Boolean(data.can_add)); }).catch(() => setTargets([]));
    targetsApi.scheduleChanges(projectId).then(data => setChanges(Array.isArray(data) ? data : [])).catch(() => setChanges([]));
  }

  async function load() {
    setLoading(true); setError("");
    loadExtras();
    try {
      setTasks(await taskExecutionApi.list(projectId));
    } catch (caught) {
      setError(caught?.message || "The execution calendar could not be loaded.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let active = true;
    setProject(null);
    projectsApi.detail(projectId).then(detail => { if (active) setProject(detail); }).catch(() => {});
    return () => { active = false; };
  }, [projectId]);

  const counts = useMemo(() => executionCounts(tasks), [tasks]);
  const phases = useMemo(() => [...new Set(tasks.map(task => task.phase).filter(Boolean))], [tasks]);
  const vendors = useMemo(() => [...new Set(tasks.map(task => task.vendor_name).filter(Boolean))].sort(), [tasks]);
  const term = search.trim().toLowerCase();
  const targetedTaskIds = new Set(targets.filter(target => target.status === "active" && target.task_id).map(target => target.task_id));
  const summary = targetSummary(targets, today);
  const filtered = tasks.filter(task => {
    if (onlyTargets && !targetedTaskIds.has(task.id)) return false;
    if (!matchesStatusBucket(task, statusFilter)) return false;
    if (phaseFilter !== "all" && task.phase !== phaseFilter) return false;
    if (!matchesTaskType(task, typeFilter)) return false;
    if (vendorFilter !== "all" && task.vendor_name !== vendorFilter) return false;
    if (!term) return true;
    return [task.original_code, task.title, task.category, task.phase, task.vendor_name].some(value => value && value.toLowerCase().includes(term));
  });
  const filtersOn = term || onlyTargets || phaseFilter !== "all" || statusFilter !== "all" || typeFilter !== "all" || vendorFilter !== "all";
  const popoverFilters = [phaseFilter, typeFilter, vendorFilter].filter(value => value !== "all").length;
  function resetFilters() { setSearch(""); setOnlyTargets(false); setPhaseFilter("all"); setStatusFilter("all"); setTypeFilter("all"); setVendorFilter("all"); }

  const selectedTask = tasks.find(task => task.id === selectedTaskId) || null;
  const candidates = (project?.memberships || []).filter(m => m.project_role === "internal_employee");
  const selectClass = "h-9 rounded-lg border border-slate-200 bg-white px-2.5 text-sm text-slate-900 outline-none focus:border-blue-600";

  const statusChips = [["total", "All"], ["ready", "Ready"], ["in_progress", "In progress"], ["needs_review", "Needs review"], ["completed", "Completed"], ["delayed", "Delayed"], ["blocked", "Blocked"]]
    // A status nobody is in is noise; keep it only while it is the filter.
    .filter(([key]) => key === "total" || counts[key] > 0 || statusFilter === key);

  return <div className="grid min-w-0 gap-3">
    <div className="flex flex-wrap items-center gap-2 rounded-[20px] border border-line bg-white p-2">
      <div role="tablist" aria-label="Calendar view" className="flex gap-0.5 rounded-[10px] bg-slate-100 p-[3px]">
        {VIEWS.map(({ key, label, Icon }) => <button key={key} role="tab" type="button" aria-selected={view === key} onClick={() => chooseView(key)}
          className={`flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] transition ${view === key ? "bg-white text-slate-950 shadow-[0_1px_3px_rgba(21,23,26,.12)]" : "text-slate-500 hover:text-slate-950"}`}><Icon size={15}/>{label}</button>)}
      </div>

      {!loading && tasks.length > 0 && <div role="group" aria-label="Execution summary" className="so-scroll flex min-w-0 gap-1 overflow-x-auto">
        {statusChips.map(([key, label]) => {
          const selected = statusFilter === key || (key === "total" && statusFilter === "all");
          return <button key={key} type="button" onClick={() => setStatusFilter(key === "total" ? "all" : key)} aria-pressed={selected}
            className={`flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[13px] transition-colors ${selected ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
            {key !== "total" && <span className={`size-2 rounded-full ${STAT_DOTS[key]}`} aria-hidden="true"/>}{label} <span className={`tabular-nums ${selected ? "text-slate-300" : "text-slate-400"}`}>{counts[key]}</span>
          </button>;
        })}
      </div>}

      <div className="ml-auto flex flex-wrap items-center gap-1.5">
        {!loading && tasks.length > 0 && <>
          <label className="relative w-full sm:w-56">
            <span className="sr-only">Search tasks</span>
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
            <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search code, title, phase or vendor" className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-600 focus:bg-white"/>
          </label>
          <Popover label="Filters" icon={SlidersHorizontal} badge={popoverFilters}>
            <div className="grid gap-3 p-1">
              <label className="grid gap-1 text-xs text-slate-500">Phase<select aria-label="Phase" value={phaseFilter} onChange={event => setPhaseFilter(event.target.value)} className={selectClass}><option value="all">All phases</option>{phases.map(phase => <option key={phase} value={phase}>{phase}</option>)}</select></label>
              <label className="grid gap-1 text-xs text-slate-500">Task type<select aria-label="Task type" value={typeFilter} onChange={event => setTypeFilter(event.target.value)} className={selectClass}>{TASK_TYPE_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
              {vendors.length > 0 && <label className="grid gap-1 text-xs text-slate-500">Vendor<select aria-label="Vendor" value={vendorFilter} onChange={event => setVendorFilter(event.target.value)} className={selectClass}><option value="all">All vendors</option>{vendors.map(name => <option key={name} value={name}>{name}</option>)}</select></label>}
            </div>
          </Popover>
          <Popover label={summary.missed ? `Targets · ${summary.missed} missed` : summary.thisWeek ? `Targets · ${summary.thisWeek} this week` : "Targets"} icon={Diamond}
            badge={onlyTargets ? summary.active : 0} ariaLabel={`Targets: ${summary.active} active, ${summary.thisWeek} due this week, ${summary.missed} missed`} width="w-80">
            {close => <TargetsList targets={targets} canAdd={canAddTargets} onlyTargets={onlyTargets} onToggleOnly={() => setOnlyTargets(value => !value)}
              onOpenTask={id => { close(); setSelectedTaskId(id); }} onAddProjectTarget={() => { close(); setAddingTarget(true); }}/>}
          </Popover>
          {filtersOn && <button type="button" onClick={resetFilters} className="flex h-9 items-center gap-1 rounded-lg px-2 text-[13px] text-slate-600 hover:bg-slate-100"><RotateCcw size={14}/> Reset</button>}
        </>}
        {view === "gantt" && <ZoomMenu value={ganttZoom} options={GANTT_ZOOM_LABELS} onChange={setGanttZoom}/>}
        {view !== "month" && <button type="button" onClick={() => setTodaySignal(n => n + 1)} title={`Scroll to today, ${today.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}`} className="flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-[13px] text-slate-800 hover:border-slate-300"><Target size={14}/> Today</button>}
        {view === "gantt" && <Popover label="Legend" ariaLabel="Legend" icon={Info} iconOnly>
          <ul className="grid gap-2 p-1 text-[13px] text-slate-700">
            {LEGEND.map(([color, label]) => <li key={label} className="flex items-center gap-2"><span className={`h-2 w-5 rounded-full ${color}`}/>{label}</li>)}
            <li className="flex items-center gap-2 border-t border-line pt-2"><span className="h-3 w-5 rounded-full border border-dashed border-slate-400"/>The plan</li>
            <li className="flex items-center gap-2"><span className="h-1.5 w-5 rounded-full bg-blue-600"/>What actually happened (to today if still running)</li>
            <li className="flex items-center gap-2"><span className="h-3 w-5 rounded-full border border-dotted border-violet-300"/>Original plan, when a task was moved</li>
            <li className="flex items-center gap-2"><span className="mx-1 size-2.5 rotate-45 rounded-[2px] bg-blue-600"/>Target: blue open, orange due soon, green met, red missed</li>
            <li className="text-slate-600">Tags say how early or late a task started or finished. Arrows mean a task waits for another; the red column is today.</li>
            <li className="text-slate-600">Hover a bar for details, click to open the task.</li>
          </ul>
        </Popover>}
      </div>
    </div>

    {error && <div role="alert" className="rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}

    {loading ? <div className="rounded-[20px] border border-line bg-white p-8"><LoadingSpinner label="Loading tasks..."/></div>
      : !tasks.length ? <EmptyState icon={<CalendarDays size={21}/>} title="No execution tasks yet" description="This project's plan has no tasks to execute."/>
      : !filtered.length ? <EmptyState icon={<Search size={21}/>} title="No tasks match" description="Try a different search or filter."/>
      : view === "month"
        ? <MonthCalendar tasks={filtered} project={project} today={today} todaySignal={todaySignal} onOpenTask={setSelectedTaskId} targets={targets}/>
        : <ProjectGantt tasks={filtered} project={project} zoom={ganttZoom} today={today} todaySignal={todaySignal} onOpenTask={setSelectedTaskId} targets={targets} changes={changes}/>}

    {addingTarget && <ProjectTargetModal projectId={projectId} tasks={tasks} onClose={() => setAddingTarget(false)} onSaved={() => { setAddingTarget(false); loadExtras(); }}/>}

    {selectedTask && <TaskDetailDrawer key={selectedTask.id} projectId={projectId} project={project} task={selectedTask} user={user} candidates={candidates}
      onClose={() => setSelectedTaskId(null)} onChanged={load}/>}
  </div>;
}
