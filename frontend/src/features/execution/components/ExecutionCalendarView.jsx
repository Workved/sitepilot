import { BarChart3, CalendarDays, LayoutList, RotateCcw, Search, Target } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { EmptyState, LoadingSpinner } from "../../../components/ui";
import { PortfolioTimeline } from "./calendar/PortfolioTimeline";
import { MonthCalendar } from "./calendar/MonthCalendar";
import { ProjectGantt } from "./calendar/ProjectGantt";
import { TaskDetailDrawer } from "./TaskDetailDrawer";
import { executionCounts, matchesStatusBucket, matchesTaskType, STATUS_BUCKETS, TASK_TYPE_FILTERS, todayAsDay } from "./executionViewHelpers";

// The Execution calendar: three views of the same work.
//  - Gantt: this project's tasks on a timeline (plan vs actual, lateness,
//    dependencies);
//  - Month: a month grid of what starts, is due, finishes or is late;
//  - Portfolio: every project you can see, start to handover, with health.
// Clicking a task opens its detail drawer; clicking a running project in the
// portfolio switches the page to that project's Gantt.

const VIEWS = [
  { key: "gantt", label: "Gantt", Icon: BarChart3 },
  { key: "month", label: "Month", Icon: CalendarDays },
  { key: "portfolio", label: "Portfolio", Icon: LayoutList },
];
const GANTT_ZOOM_LABELS = [["day", "Day"], ["week", "Week"], ["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]];
const PORTFOLIO_ZOOM_LABELS = [["week", "Week"], ["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]];
const VIEW_KEY = "siteops.calendarView";

function rememberedView() {
  try { return VIEWS.some(v => v.key === window.localStorage.getItem(VIEW_KEY)) ? window.localStorage.getItem(VIEW_KEY) : "gantt"; } catch { return "gantt"; }
}

function Segmented({ label, value, options, onChange }) {
  return <div role="group" aria-label={label} className="inline-flex overflow-hidden rounded-xl border border-slate-200 bg-white">
    {options.map(([key, text]) => <button key={key} type="button" aria-pressed={value === key} onClick={() => onChange(key)}
      className={`min-h-9 px-3 text-xs font-black transition ${value === key ? "bg-blue-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}>{text}</button>)}
  </div>;
}

const STAT_TONES = { total: "text-slate-700", ready: "text-emerald-700", in_progress: "text-blue-700", needs_review: "text-violet-700", completed: "text-emerald-700", delayed: "text-rose-700", blocked: "text-rose-700" };

export function ExecutionCalendarView({ projectId, user, onSelectProject }) {
  const [view, setView] = useState(rememberedView);
  const [tasks, setTasks] = useState([]);
  const [project, setProject] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [phaseFilter, setPhaseFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [vendorFilter, setVendorFilter] = useState("all");
  const [ganttZoom, setGanttZoom] = useState("week");
  const [portfolioZoom, setPortfolioZoom] = useState("quarter");
  const [todaySignal, setTodaySignal] = useState(0);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const today = useMemo(() => todayAsDay(), []);

  function chooseView(next) {
    setView(next);
    try { window.localStorage.setItem(VIEW_KEY, next); } catch { /* per-viewer convenience only */ }
  }

  async function load() {
    setLoading(true); setError("");
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
  useEffect(() => {
    if (view !== "portfolio" || portfolio) return;
    projectsApi.timeline().then(setPortfolio).catch(caught => { setPortfolio([]); setError(caught?.message || "The portfolio could not be loaded."); });
  }, [view, portfolio]);

  const counts = useMemo(() => executionCounts(tasks), [tasks]);
  const phases = useMemo(() => [...new Set(tasks.map(task => task.phase).filter(Boolean))], [tasks]);
  const vendors = useMemo(() => [...new Set(tasks.map(task => task.vendor_name).filter(Boolean))].sort(), [tasks]);
  const term = search.trim().toLowerCase();
  const filtered = tasks.filter(task => {
    if (!matchesStatusBucket(task, statusFilter)) return false;
    if (phaseFilter !== "all" && task.phase !== phaseFilter) return false;
    if (!matchesTaskType(task, typeFilter)) return false;
    if (vendorFilter !== "all" && task.vendor_name !== vendorFilter) return false;
    if (!term) return true;
    return [task.original_code, task.title, task.category, task.phase, task.vendor_name].some(value => value && value.toLowerCase().includes(term));
  });
  const filtersOn = term || phaseFilter !== "all" || statusFilter !== "all" || typeFilter !== "all" || vendorFilter !== "all";
  function resetFilters() { setSearch(""); setPhaseFilter("all"); setStatusFilter("all"); setTypeFilter("all"); setVendorFilter("all"); }

  const selectedTask = tasks.find(task => task.id === selectedTaskId) || null;
  const candidates = (project?.memberships || []).filter(m => m.project_role === "internal_employee");
  const selectClass = "min-h-9 rounded-xl border border-slate-200 bg-white px-3 text-xs font-bold text-slate-700 outline-none focus:border-blue-500";

  return <div className="grid min-w-0 gap-3">
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-white p-2">
      <div role="tablist" aria-label="Calendar view" className="flex flex-wrap gap-1">
        {VIEWS.map(({ key, label, Icon }) => <button key={key} role="tab" type="button" aria-selected={view === key} onClick={() => chooseView(key)}
          className={`flex min-h-9 items-center gap-1.5 rounded-xl px-3 text-sm font-black transition ${view === key ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}><Icon size={15}/>{label}</button>)}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {view === "gantt" && <Segmented label="Zoom" value={ganttZoom} options={GANTT_ZOOM_LABELS} onChange={setGanttZoom}/>}
        {view === "portfolio" && <Segmented label="Zoom" value={portfolioZoom} options={PORTFOLIO_ZOOM_LABELS} onChange={setPortfolioZoom}/>}
        {view !== "month" && <button type="button" onClick={() => setTodaySignal(n => n + 1)} className="flex min-h-9 items-center gap-1.5 rounded-xl border border-blue-200 bg-blue-50 px-3 text-xs font-black text-blue-700 hover:bg-blue-100"><Target size={14}/> Today</button>}
      </div>
    </div>

    {view !== "portfolio" && !loading && tasks.length > 0 && <>
      <div role="group" className="flex flex-wrap gap-1.5" aria-label="Execution summary">
        {[["total", "Total"], ["ready", "Ready"], ["in_progress", "In progress"], ["needs_review", "Needs review"], ["completed", "Completed"], ["delayed", "Delayed"], ["blocked", "Blocked"]].map(([key, label]) =>
          <button key={key} type="button" onClick={() => setStatusFilter(key === "total" ? "all" : key)} aria-pressed={statusFilter === key || (key === "total" && statusFilter === "all")}
            className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold ${statusFilter === key || (key === "total" && statusFilter === "all") ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
            <span className={`font-black ${STAT_TONES[key]}`}>{counts[key]}</span><span className="text-slate-600">{label}</span>
          </button>)}
      </div>
      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-2">
        <label className="relative min-w-[180px] flex-1">
          <span className="sr-only">Search tasks</span>
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/>
          <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search code, title, phase or vendor" className="min-h-9 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none focus:border-blue-500"/>
        </label>
        <select aria-label="Phase" value={phaseFilter} onChange={event => setPhaseFilter(event.target.value)} className={selectClass}><option value="all">All phases</option>{phases.map(phase => <option key={phase} value={phase}>{phase}</option>)}</select>
        <select aria-label="Status" value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className={selectClass}>{STATUS_BUCKETS.map(([key, label]) => <option key={key} value={key}>{key === "all" ? "All statuses" : label}</option>)}</select>
        <select aria-label="Task type" value={typeFilter} onChange={event => setTypeFilter(event.target.value)} className={selectClass}>{TASK_TYPE_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
        {vendors.length > 0 && <select aria-label="Vendor" value={vendorFilter} onChange={event => setVendorFilter(event.target.value)} className={selectClass}><option value="all">All vendors</option>{vendors.map(name => <option key={name} value={name}>{name}</option>)}</select>}
        {filtersOn && <button type="button" onClick={resetFilters} className="flex min-h-9 items-center gap-1 rounded-xl px-2 text-xs font-black text-slate-500 hover:bg-slate-100"><RotateCcw size={13}/> Reset</button>}
      </div>
    </>}

    {error && <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>}

    {view === "portfolio"
      ? (portfolio === null ? <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading projects..."/></div>
        : portfolio.length ? <PortfolioTimeline rows={portfolio} zoom={portfolioZoom} today={today} todaySignal={todaySignal} onOpenProject={id => { onSelectProject?.(id); chooseView("gantt"); }}/>
        : <EmptyState icon={<LayoutList size={21}/>} title="No projects to show" description="Projects you're part of appear here."/>)
      : loading ? <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading tasks..."/></div>
      : !tasks.length ? <EmptyState icon={<CalendarDays size={21}/>} title="No execution tasks yet" description="This project's plan has no tasks to execute."/>
      : !filtered.length ? <EmptyState icon={<Search size={21}/>} title="No tasks match" description="Try a different search or filter."/>
      : view === "month"
        ? <MonthCalendar tasks={filtered} project={project} today={today} todaySignal={todaySignal} onOpenTask={setSelectedTaskId}/>
        : <ProjectGantt tasks={filtered} project={project} zoom={ganttZoom} today={today} todaySignal={todaySignal} onOpenTask={setSelectedTaskId}/>}

    {view === "gantt" && tasks.length > 0 && <p className="text-xs font-semibold text-slate-500">● start ━ duration ● end · colour = status (blue in progress, green done, violet needs review, red blocked, grey not started) · +Nd = days late · arrows = waits for another task · red in the date header = today · hover for details, click to open</p>}

    {selectedTask && <TaskDetailDrawer key={selectedTask.id} projectId={projectId} project={project} task={selectedTask} user={user} candidates={candidates}
      onClose={() => setSelectedTaskId(null)} onChanged={load}/>}
  </div>;
}
