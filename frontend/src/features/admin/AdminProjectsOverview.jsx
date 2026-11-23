import {
  Activity, AlertTriangle, ArrowRight, Boxes, CheckCircle2, ChevronLeft, ChevronRight,
  Clock, FileText, Layers, LayoutGrid, List, Search, ShieldAlert, SlidersHorizontal, UserRound, X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { adminVisibilityApi } from "../../api/adminVisibilityApi";
import { EmptyState, LoadingSpinner, Pill, RefreshButton } from "../../components/ui";
import { cn } from "../../utils/cn";
import { relativeAge } from "../../utils/format";
import { paginationItems } from "../../utils/pagination";

const HEALTH_META = {
  on_track: { label: "Active", subtitle: "On Track", tone: "green" },
  at_risk: { label: "At Risk", subtitle: "Needs Attention", tone: "orange" },
  delayed: { label: "Delayed", subtitle: "Behind Schedule", tone: "red" },
  completed: { label: "Completed", subtitle: "Handover Done", tone: "blue" },
  on_hold: { label: "On Hold", subtitle: "Paused", tone: "gray" },
  draft: { label: "Draft", subtitle: "Not Started", tone: "gray" },
  archived: { label: "Archived", subtitle: "Closed", tone: "gray" },
};

const COUNT_TILES = [
  ["planned_count", "Planned", "slate"],
  ["active_count", "Active", "slate"],
  ["completed_count", "Completed", "emerald"],
  ["blocked_count", "Blocked", "rose"],
  ["delayed_count", "Delayed", "amber"],
  ["overdue_count", "Overdue", "rose"],
  ["no_update_count", "No Update", "amber"],
];

const TILE_TONE_CLASSES = {
  slate: "border-slate-200 bg-slate-50 text-slate-950",
  rose: "border-rose-300 bg-rose-50 text-rose-700",
  amber: "border-amber-300 bg-amber-50 text-amber-700",
  emerald: "border-emerald-300 bg-emerald-50 text-emerald-700",
};

const SORT_OPTIONS = [
  ["name_asc", "Name (A-Z)"],
  ["name_desc", "Name (Z-A)"],
  ["progress_desc", "Progress (High-Low)"],
  ["progress_asc", "Progress (Low-High)"],
  ["status", "Status"],
];

const PAGE_SIZE_OPTIONS = [10, 25, 50];

function sortProjects(list, sortBy) {
  const arr = [...list];
  if (sortBy === "name_desc") arr.sort((a, b) => b.name.localeCompare(a.name));
  else if (sortBy === "progress_desc") arr.sort((a, b) => b.progress_percent - a.progress_percent);
  else if (sortBy === "progress_asc") arr.sort((a, b) => a.progress_percent - b.progress_percent);
  else if (sortBy === "status") arr.sort((a, b) => a.health.localeCompare(b.health) || a.name.localeCompare(b.name));
  else arr.sort((a, b) => a.name.localeCompare(b.name));
  return arr;
}

function activityIcon(action = "") {
  if (action.includes("OVERDUE") || action.includes("BLOCK")) return { Icon: AlertTriangle, tone: "text-amber-600 bg-amber-50" };
  if (action.includes("COMPLETED") || action.includes("STATUS")) return { Icon: CheckCircle2, tone: "text-emerald-600 bg-emerald-50" };
  if (action.includes("BASELINE") || action.includes("LOCKED")) return { Icon: FileText, tone: "text-blue-600 bg-blue-50" };
  if (action.includes("ROLE") || action.includes("ASSIGN")) return { Icon: UserRound, tone: "text-violet-600 bg-violet-50" };
  return { Icon: Activity, tone: "text-slate-500 bg-slate-100" };
}

function formatAction(action = "") {
  return action.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function StatTile({ icon, tone, label, value, hint, className }) {
  return <div className={cn("flex items-center gap-3 rounded-2xl border p-4", tone, className)}>
    <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-white/70">{icon}</span>
    <div className="min-w-0">
      <p className="text-xs font-bold text-slate-500">{label}</p>
      <p className="text-2xl font-normal leading-tight text-slate-950">{value}</p>
      {hint && <p className="text-[11px] font-semibold text-slate-500">{hint}</p>}
    </div>
  </div>;
}

function ProjectRow({ project, dense, onOpen }) {
  const health = HEALTH_META[project.health] || HEALTH_META.draft;
  return <article className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 transition hover:border-blue-200">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <span className="text-xs font-medium text-slate-500">{project.code}</span>
        <h3 className="mt-0.5 truncate font-black text-slate-950">{project.name}</h3>
        <p className="mt-0.5 truncate text-xs font-semibold text-slate-500">
          {project.pm_name ? `PM: ${project.pm_name}` : "PM: Unassigned"} &bull; Site: {project.site}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <div className="text-right">
          <Pill tone={health.tone}>{health.label}</Pill>
          <p className="mt-1 text-[11px] font-bold text-slate-400">{health.subtitle}</p>
        </div>
        <button type="button" onClick={onOpen} aria-label={`Open ${project.name}`}
          className="grid size-10 shrink-0 place-items-center rounded-xl border border-slate-200 text-slate-500 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700">
          <ArrowRight size={17} />
        </button>
      </div>
    </div>

    <div className="flex items-center gap-3">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-blue-600" style={{ width: `${project.progress_percent}%` }} />
      </div>
      <span className="w-10 shrink-0 text-right text-xs font-black text-slate-700">{project.progress_percent}%</span>
    </div>

    {!dense && <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
      {COUNT_TILES.map(([key, label, tone]) => <div key={key} className={cn("rounded-xl border p-2 text-center", TILE_TONE_CLASSES[project[key] > 0 ? tone : "slate"])}>
        <p className="text-xs font-medium text-slate-500">{label}</p>
        <p className="text-lg font-black text-slate-950">{project[key]}</p>
      </div>)}
    </div>}
  </article>;
}

export function AdminProjectsOverview({ onOpenProject }) {
  const [projects, setProjects] = useState([]);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [healthFilter, setHealthFilter] = useState(() => new Set());
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sortBy, setSortBy] = useState("name_asc");
  const [viewMode, setViewMode] = useState("cards");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [activityExpanded, setActivityExpanded] = useState(false);

  const filtersRef = useRef(null);
  const listTopRef = useRef(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [overview, events] = await Promise.all([
        adminVisibilityApi.projectsOverview(),
        adminVisibilityApi.activity({ limit: 50 }),
      ]);
      setProjects(overview);
      setActivity(events);
    } catch (caught) {
      setError(caught?.message || "The portfolio overview could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  useEffect(() => {
    function onClickOutside(event) {
      if (filtersRef.current && !filtersRef.current.contains(event.target)) setFiltersOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => { setPage(1); }, [search, healthFilter, sortBy, pageSize]);

  const summary = useMemo(() => ({
    total: projects.length,
    active: projects.filter(p => p.health === "on_track").length,
    atRisk: projects.filter(p => p.health === "at_risk").length,
    delayed: projects.filter(p => p.health === "delayed").length,
    completed: projects.filter(p => p.health === "completed").length,
    overdueItems: projects.reduce((sum, p) => sum + p.overdue_count, 0),
    noUpdateItems: projects.reduce((sum, p) => sum + p.no_update_count, 0),
    flagged: projects.filter(p => ["at_risk", "delayed"].includes(p.health) || p.overdue_count > 0 || p.no_update_count > 0).length,
  }), [projects]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return projects.filter(p => {
      if (healthFilter.size > 0 && !healthFilter.has(p.health)) return false;
      if (!term) return true;
      return [p.code, p.name, p.pm_name, p.site].some(field => field?.toLowerCase().includes(term));
    });
  }, [projects, search, healthFilter]);

  const sorted = useMemo(() => sortProjects(filtered, sortBy), [filtered, sortBy]);
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const pageSafe = Math.min(page, totalPages);
  const pageProjects = sorted.slice((pageSafe - 1) * pageSize, pageSafe * pageSize);
  const visibleActivity = activityExpanded ? activity : activity.slice(0, 5);

  function toggleHealth(key) {
    setHealthFilter(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  function focusAttention(keys) {
    setHealthFilter(new Set(keys));
    setSearch("");
    listTopRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (loading) return <div className="grid min-h-40 place-items-center"><LoadingSpinner label="Loading portfolio overview..." /></div>;

  return <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
    <div className="grid min-w-0 gap-6">
      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>}

      <section ref={listTopRef} className="grid gap-5 rounded-2xl border border-slate-200 bg-white p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-medium text-slate-500">Portfolio</p>
            <h2 className="mt-2 text-3xl font-normal tracking-tight text-slate-950">Portfolio Rollup</h2>
            <span className="mt-2 block text-sm text-slate-500">Cross-project performance, status, and activity overview</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <RefreshButton loading={loading} onClick={load}/>
            <div className="relative">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search projects..."
                className="min-h-11 w-56 rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm font-medium text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" />
            </div>
            <div ref={filtersRef} className="relative">
              <button type="button" onClick={() => setFiltersOpen(v => !v)}
                className={cn("flex min-h-11 items-center gap-2 rounded-xl border px-3.5 text-sm font-bold transition", healthFilter.size > 0 ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50")}>
                <SlidersHorizontal size={16} /> Filters {healthFilter.size > 0 && <span className="grid size-5 place-items-center rounded-full bg-blue-600 text-[10px] font-black text-white">{healthFilter.size}</span>}
              </button>
              {filtersOpen && <div className="absolute right-0 top-[calc(100%+8px)] z-20 grid w-56 gap-1 rounded-xl border border-slate-200 bg-white p-2 shadow-[0_18px_50px_rgba(15,23,42,.14)]">
                {Object.entries(HEALTH_META).map(([key, meta]) => <label key={key} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                  <input type="checkbox" checked={healthFilter.has(key)} onChange={() => toggleHealth(key)} className="size-4 rounded border-slate-300 text-blue-600 focus:ring-blue-600" />
                  {meta.label}
                </label>)}
                {healthFilter.size > 0 && <button type="button" onClick={() => setHealthFilter(new Set())} className="mt-1 flex items-center justify-center gap-1 rounded-lg border border-slate-200 py-1.5 text-xs font-bold text-slate-500 hover:bg-slate-50"><X size={12} /> Clear filters</button>}
              </div>}
            </div>
            <select value={sortBy} onChange={e => setSortBy(e.target.value)}
              className="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-700 outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10">
              {SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>Sort by: {label}</option>)}
            </select>
            <div className="flex items-center gap-1 rounded-xl border border-slate-200 bg-white p-1">
              <button type="button" onClick={() => setViewMode("cards")} aria-pressed={viewMode === "cards"}
                className={cn("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-black transition", viewMode === "cards" ? "bg-blue-700 text-white" : "text-slate-500 hover:bg-slate-50")}><LayoutGrid size={14} /> Cards</button>
              <button type="button" onClick={() => setViewMode("list")} aria-pressed={viewMode === "list"}
                className={cn("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-black transition", viewMode === "list" ? "bg-blue-700 text-white" : "text-slate-500 hover:bg-slate-50")}><List size={14} /> List</button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile icon={<Boxes size={20} className="text-slate-600" />} tone="border-slate-200 bg-slate-50" label="Total Projects" value={summary.total} hint="Across all sites" />
          <StatTile icon={<Activity size={20} className="text-emerald-600" />} tone="border-emerald-200 bg-emerald-50" label="Active" value={summary.active} hint={summary.total ? `${Math.round(summary.active / summary.total * 100)}% of total` : undefined} />
          <StatTile icon={<ShieldAlert size={20} className="text-amber-600" />} tone="border-amber-200 bg-amber-50" label="At Risk" value={summary.atRisk} hint={summary.total ? `${Math.round(summary.atRisk / summary.total * 100)}% of total` : undefined} />
          <StatTile icon={<Clock size={20} className="text-rose-600" />} tone="border-rose-200 bg-rose-50" label="Delayed" value={summary.delayed} hint={summary.total ? `${Math.round(summary.delayed / summary.total * 100)}% of total` : undefined} />
          <StatTile icon={<CheckCircle2 size={20} className="text-blue-600" />} tone="border-blue-200 bg-blue-50" label="Completed" value={summary.completed} hint={summary.total ? `${Math.round(summary.completed / summary.total * 100)}% of total` : undefined} className="col-span-2 sm:col-span-1" />
        </div>
      </section>

      <section className="grid gap-3">
        <div className="flex items-center justify-between px-1">
          <h3 className="flex items-center gap-2 text-sm font-black text-slate-950"><Layers size={16} /> Projects ({sorted.length})</h3>
          {healthFilter.size > 0 && <button type="button" onClick={() => setHealthFilter(new Set())} className="text-xs font-bold text-blue-700 hover:underline">Clear filters</button>}
        </div>

        {pageProjects.length === 0
          ? <EmptyState title="No projects match" description="Try a different search term or clear your filters."/>
          : <div className="grid gap-3">{pageProjects.map(project => <ProjectRow key={project.id} project={project} dense={viewMode === "list"} onOpen={() => onOpenProject?.(project.code)} />)}</div>}

        {sorted.length > 0 && <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3">
          <span className="text-xs font-semibold text-slate-500">Showing {(pageSafe - 1) * pageSize + 1} to {Math.min(pageSafe * pageSize, sorted.length)} of {sorted.length} projects</span>
          <div className="flex items-center gap-1">
            <button type="button" disabled={pageSafe === 1} onClick={() => setPage(pageSafe - 1)} className="grid size-8 place-items-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-50 disabled:pointer-events-none disabled:opacity-40"><ChevronLeft size={15} /></button>
            {paginationItems(pageSafe, totalPages).map((item, i) => item === "..."
              ? <span key={`ellipsis-${i}`} className="px-1 text-xs font-bold text-slate-400">...</span>
              : <button key={item} type="button" onClick={() => setPage(item)} className={cn("grid size-8 place-items-center rounded-lg text-xs font-black transition", item === pageSafe ? "bg-blue-700 text-white" : "text-slate-600 hover:bg-slate-50")}>{item}</button>)}
            <button type="button" disabled={pageSafe === totalPages} onClick={() => setPage(pageSafe + 1)} className="grid size-8 place-items-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-50 disabled:pointer-events-none disabled:opacity-40"><ChevronRight size={15} /></button>
          </div>
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-500">Rows per page:
            <select value={pageSize} onChange={e => setPageSize(Number(e.target.value))} className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-bold text-slate-700 outline-none focus:border-blue-600">
              {PAGE_SIZE_OPTIONS.map(size => <option key={size} value={size}>{size}</option>)}
            </select>
          </label>
        </div>}
      </section>
    </div>

    <div className="grid min-w-0 gap-6">
      <section className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-black text-slate-950">Attention Needed
            {summary.flagged > 0 && <span className="grid min-w-5 place-items-center rounded-full bg-rose-600 px-1.5 py-0.5 text-[10px] font-black text-white">{summary.flagged}</span>}
          </h3>
          <button type="button" onClick={() => focusAttention(["at_risk", "delayed"])} className="text-xs font-bold text-blue-700 hover:underline">View all</button>
        </div>
        <div className="grid gap-1.5">
          <button type="button" onClick={() => focusAttention(["at_risk"])} className="flex items-center justify-between rounded-xl px-2 py-2 text-left transition hover:bg-slate-50">
            <span className="flex items-center gap-2 text-sm font-semibold text-slate-700"><ShieldAlert size={16} className="text-rose-600" /> High Risk Projects</span>
            <span className="font-black text-slate-950">{summary.atRisk}</span>
          </button>
          <button type="button" onClick={() => focusAttention(["delayed"])} className="flex items-center justify-between rounded-xl px-2 py-2 text-left transition hover:bg-slate-50">
            <span className="flex items-center gap-2 text-sm font-semibold text-slate-700"><Clock size={16} className="text-amber-600" /> Delayed Projects</span>
            <span className="font-black text-slate-950">{summary.delayed}</span>
          </button>
          <div className="flex items-center justify-between rounded-xl px-2 py-2">
            <span className="flex items-center gap-2 text-sm font-semibold text-slate-700"><AlertTriangle size={16} className="text-rose-600" /> Overdue Items</span>
            <span className="font-black text-slate-950">{summary.overdueItems}</span>
          </div>
          <div className="flex items-center justify-between rounded-xl px-2 py-2">
            <span className="flex items-center gap-2 text-sm font-semibold text-slate-700"><Activity size={16} className="text-slate-500" /> No Update &gt; 7 Days</span>
            <span className="font-black text-slate-950">{summary.noUpdateItems}</span>
          </div>
        </div>
      </section>

      <section className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-black text-slate-950">Recent Activity</h3>
        </div>
        {visibleActivity.length === 0
          ? <EmptyState title="No activity recorded" description="Audit events across all projects will appear here." />
          : <div className={cn("grid gap-1", activityExpanded && "max-h-[calc(100vh-14rem)] overflow-y-auto overscroll-contain pr-1")}>{visibleActivity.map(event => {
              const { Icon, tone } = activityIcon(event.action);
              return <div key={event.id} className="flex items-start gap-3 rounded-xl px-2 py-2 transition hover:bg-slate-50">
                <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", tone)}><Icon size={15} /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <strong className="truncate text-xs font-black text-slate-900">{formatAction(event.action)}</strong>
                    <span className="shrink-0 text-[11px] font-semibold text-slate-400">{relativeAge(event.occurred_at)}</span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-slate-500">{event.actor_name} &bull; {event.reason}</p>
                </div>
              </div>;
            })}</div>}
        {activity.length > 5 && <button type="button" onClick={() => setActivityExpanded(v => !v)} className="flex items-center justify-center gap-1 rounded-xl border border-slate-200 py-2 text-xs font-bold text-blue-700 hover:bg-blue-50">
          {activityExpanded ? "Show less" : "View all activity"} <ArrowRight size={13} />
        </button>}
      </section>
    </div>
  </div>;
}
