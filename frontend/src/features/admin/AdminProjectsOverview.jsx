import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, History, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { adminVisibilityApi } from "../../api/adminVisibilityApi";
import { projectsApi } from "../../api/projectsApi";
import { Alert, EmptyState, LoadingSpinner, RefreshButton } from "../../components/ui";
import { cn } from "../../utils/cn";
import { formatDateShort, relativeAge } from "../../utils/format";
import { paginationItems } from "../../utils/pagination";
import { plannedPercent, standingOf } from "../../utils/schedule";

/*
 * Portfolio: every project side by side, plus what changed across the
 * company. The Overview answers "what needs me today"; this page is for
 * comparing projects, so it is a dense, sortable table rather than cards.
 *
 * Data: /admin/projects-overview (task counts per project) joined with
 * /projects/timeline (dates, forecast, days late) - both existing reads.
 * Health uses the same standingOf rule as the Overview, so the two pages
 * always agree about which projects are on track.
 */

const STANDING = {
  on_track: { label: "On track", className: "bg-emerald-50 text-emerald-800" },
  at_risk: { label: "At risk", className: "bg-orange-50 text-orange-800" },
  delayed: { label: "Delayed", className: "bg-rose-50 text-rose-800" },
  completed: { label: "Completed", className: "bg-blue-50 text-blue-800" },
  on_hold: { label: "On hold", className: "bg-slate-100 text-slate-700" },
  draft: { label: "Draft", className: "bg-slate-100 text-slate-700" },
  archived: { label: "Archived", className: "bg-slate-100 text-slate-500" },
};
const CHIPS = ["all", "on_track", "at_risk", "delayed", "on_hold", "completed", "draft", "archived"];
// Worst first, so the default sort puts trouble at the top.
const SEVERITY = { delayed: 0, at_risk: 1, on_hold: 2, on_track: 3, draft: 4, completed: 5, archived: 6 };
const PAGE_SIZES = [10, 25, 50];
const RUNNING = new Set(["active", "on_hold"]);

export function portfolioStanding(project, timelineRow) {
  if (project.status === "archived") return "archived";
  if (project.status === "draft") return "draft";
  if (project.status === "completed") return "completed";
  const row = { status: project.status, health: timelineRow?.health || project.health, progress_pct: project.progress_percent };
  const planned = timelineRow && RUNNING.has(project.status) ? plannedPercent(timelineRow) : null;
  const standing = standingOf(row, planned);
  return project.status === "on_hold" && standing === "on_track" ? "on_hold" : standing;
}

const COLUMNS = [
  ["name", "Project"],
  ["pm", "PM"],
  ["standing", "Health"],
  ["progress", "Progress vs plan"],
  ["overdue", "Overdue"],
  ["blocked", "Blocked"],
  ["no_update", "No update"],
  ["handover", "Handover"],
  ["last_update", "Last update"],
];

function sortValue(project, key) {
  switch (key) {
    case "name": return project.name.toLowerCase();
    case "pm": return (project.pm_name || "~").toLowerCase();
    case "standing": return SEVERITY[project.standing] ?? 9;
    case "progress": return project.progress_percent;
    case "overdue": return project.overdue_count;
    case "blocked": return project.blocked_count;
    case "no_update": return project.no_update_count;
    case "handover": return project.handover ? new Date(`${project.handover}T00:00:00`).getTime() : Infinity;
    case "last_update": return project.last_update ? new Date(project.last_update.occurred_at).getTime() : 0;
    default: return 0;
  }
}

export function sortPortfolio(list, key, direction) {
  const sign = direction === "desc" ? -1 : 1;
  return [...list].sort((a, b) => {
    const left = sortValue(a, key);
    const right = sortValue(b, key);
    if (left < right) return -1 * sign;
    if (left > right) return 1 * sign;
    return a.name.localeCompare(b.name);
  });
}

function StandingLabel({ standing }) {
  const meta = STANDING[standing] || STANDING.draft;
  return <span className={cn("inline-flex w-fit rounded-md px-2 py-0.5 text-xs", meta.className)}>{meta.label}</span>;
}

function Count({ value, tone }) {
  return <span className={cn("tabular-nums", value ? tone : "text-slate-300")}>{value}</span>;
}

function ProgressCell({ project }) {
  const behind = project.standing === "at_risk" && project.planned != null && project.planned > project.progress_percent;
  const mix = `${project.completed_count} completed, ${project.active_count} active, ${project.planned_count} planned of ${project.total_count} tasks`;
  return <div className="min-w-[180px]" title={mix}>
    <div className="relative h-2 rounded-full bg-slate-100" aria-hidden="true">
      {project.planned != null && <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${project.planned}%`, background: behind ? "var(--color-behind-soft)" : "var(--color-blue-100)" }} />}
      {project.progress_percent > 0 && <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${project.progress_percent}%`, background: behind ? "var(--color-behind)" : "var(--color-blue-600)" }} />}
      {project.planned != null && <span className="absolute -top-1 h-4 w-0.5 rounded bg-slate-950" style={{ left: `calc(${project.planned}% - 1px)` }} />}
    </div>
    <p className="mt-1.5 text-xs tabular-nums text-slate-500"><span className="text-slate-950">{project.progress_percent}% done</span>{project.planned != null ? `, ${project.planned}% time` : ""}</p>
  </div>;
}

function HandoverCell({ project }) {
  if (!project.handover) return <span className="text-xs text-slate-400">Not set</span>;
  return <div className="whitespace-nowrap">
    <span className="block text-sm text-slate-800">{formatDateShort(project.handover)}</span>
    {project.days_late > 0
      ? <span className="block text-xs text-rose-700">{project.days_late} {project.days_late === 1 ? "day" : "days"} late</span>
      : <span className="block text-xs text-slate-500">{project.standing === "completed" ? "Handed over" : "On time"}</span>}
  </div>;
}

function SortHeader({ column, label, sort, onSort, align }) {
  const active = sort.key === column;
  return <th scope="col" aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"} className={cn("px-4 py-3 font-normal", align === "right" && "text-right")}>
    <button type="button" onClick={() => onSort(column)} className={cn("inline-flex items-center gap-1 rounded text-[13px] transition-colors hover:text-slate-950", active ? "text-slate-950" : "text-slate-500")}>
      {label}
      {active && (sort.direction === "asc" ? <ArrowUp size={13} aria-hidden="true" /> : <ArrowDown size={13} aria-hidden="true" />)}
    </button>
  </th>;
}

function PortfolioTable({ projects, sort, onSort, onOpen, onOpenActivity }) {
  return <div className="so-scroll hidden overflow-x-auto md:block">
    <table className="w-full min-w-[1100px] border-collapse text-left text-sm">
      <thead className="border-b border-line bg-slate-50">
        <tr>{COLUMNS.map(([key, label]) => <SortHeader key={key} column={key} label={label} sort={sort} onSort={onSort} align={["overdue", "blocked", "no_update"].includes(key) ? "right" : undefined} />)}</tr>
      </thead>
      <tbody className="divide-y divide-line">
        {projects.map(project => <tr key={project.id} onClick={() => onOpen(project)} className="cursor-pointer transition-colors hover:bg-slate-50">
          <td className="px-4 py-3">
            <button type="button" onClick={event => { event.stopPropagation(); onOpen(project); }} aria-label={`Open ${project.name}`} className="block max-w-[260px] text-left">
              <span className="block truncate text-sm text-slate-950">{project.name}</span>
              <span className="block truncate text-xs text-slate-500">{[project.code, project.site].filter(Boolean).join(", ")}</span>
            </button>
          </td>
          <td className="px-4 py-3 text-sm">{project.pm_name ? <span className="text-slate-800">{project.pm_name}</span> : <span className="text-orange-700">Unassigned</span>}</td>
          <td className="px-4 py-3"><StandingLabel standing={project.standing} /></td>
          <td className="px-4 py-3"><ProgressCell project={project} /></td>
          <td className="px-4 py-3 text-right"><Count value={project.overdue_count} tone="text-rose-700" /></td>
          <td className="px-4 py-3 text-right"><Count value={project.blocked_count} tone="text-rose-700" /></td>
          <td className="px-4 py-3 text-right"><Count value={project.no_update_count} tone="text-orange-700" /></td>
          <td className="px-4 py-3"><HandoverCell project={project} /></td>
          <td className="px-4 py-3" onClick={event => event.stopPropagation()}><LastUpdateCell update={project.last_update} onOpen={() => onOpenActivity(project.id)} /></td>
        </tr>)}
      </tbody>
    </table>
  </div>;
}

// Phones: the same facts as the table row, stacked.
function PortfolioCards({ projects, onOpen }) {
  return <ul className="divide-y divide-line md:hidden">
    {projects.map(project => {
      const issues = [[project.overdue_count, "overdue"], [project.blocked_count, "blocked"], [project.no_update_count, "no update"]].filter(([value]) => value > 0);
      return <li key={project.id}>
        <button type="button" onClick={() => onOpen(project)} aria-label={`Open ${project.name}`} className="grid w-full gap-2 px-4 py-3.5 text-left">
          <span className="flex items-start justify-between gap-3">
            <span className="min-w-0"><span className="block truncate text-sm text-slate-950">{project.name}</span><span className="block truncate text-xs text-slate-500">{project.pm_name || "No PM"}{project.site ? `, ${project.site}` : ""}</span></span>
            <StandingLabel standing={project.standing} />
          </span>
          <ProgressCell project={project} />
          <span className="flex flex-wrap gap-x-3 text-xs">
            {issues.length ? issues.map(([value, label]) => <span key={label} className="text-rose-700">{value} {label}</span>) : <span className="text-slate-500">No open issues</span>}
            {project.handover && <span className="ml-auto text-slate-500">Handover {formatDateShort(project.handover)}</span>}
          </span>
        </button>
      </li>;
    })}
  </ul>;
}

// Event kinds, from the backend's audit action names.
export function eventKind(action = "") {
  if (action.includes("APPROVAL") || action.includes("GATE_APPLICABILITY")) return "approvals";
  if (action.startsWith("TASK_")) return "tasks";
  if (action.startsWith("PROJECT_ROLE") || action.startsWith("VENDOR_")) return "team";
  if (action.startsWith("PROJECT_")) return "setup";
  return "other";
}
const KINDS = [
  ["project", "Project events"],
  ["tasks", "Task updates"],
  ["approvals", "Approvals"],
  ["team", "Team and vendors"],
  ["setup", "Project setup"],
  ["all", "Everything"],
];
const matchesKind = (event, kind) => kind === "all" || (kind === "project" ? Boolean(event.project_id) : eventKind(event.action) === kind);

const WEEK = 7 * 86400000;

// "This week" in one line, from the same audit events.
export function weekDigest(events, now = Date.now()) {
  const recent = events.filter(event => now - new Date(event.occurred_at).getTime() <= WEEK);
  const count = predicate => recent.filter(predicate).length;
  const parts = [
    [count(event => eventKind(event.action) === "tasks"), "task update", "task updates"],
    [count(event => eventKind(event.action) === "approvals" && event.action.includes("DECIDED")), "approval decided", "approvals decided"],
    [count(event => event.action === "PROJECT_ACTIVATED"), "project activated", "projects activated"],
    [count(event => eventKind(event.action) === "team"), "team or vendor change", "team or vendor changes"],
  ].filter(([value]) => value > 0).map(([value, one, many]) => `${value} ${value === 1 ? one : many}`);
  return parts.length ? parts.join(", ") : "No recorded changes in the last 7 days";
}

const actionText = action => {
  const words = action.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};
const dayLabel = value => {
  const date = new Date(value);
  const today = new Date();
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
};

function groupByDay(events) {
  return events.reduce((groups, event) => {
    const key = dayLabel(event.occurred_at);
    const last = groups[groups.length - 1];
    if (last && last.day === key) last.events.push(event); else groups.push({ day: key, events: [event] });
    return groups;
  }, []);
}

function ActivityItem({ event, projectName }) {
  // minmax(0,1fr): a grid track otherwise grows to fit its longest line,
  // which is what pushed the feed past its column.
  return <li className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0.5 py-2.5">
    <div className="flex min-w-0 items-baseline justify-between gap-3">
      <p className="min-w-0 truncate text-sm text-slate-950">{actionText(event.action)}{projectName ? <span className="text-slate-500">, {projectName}</span> : null}</p>
      <time className="shrink-0 text-xs text-slate-500" dateTime={event.occurred_at}>{relativeAge(event.occurred_at)}</time>
    </div>
    <p className="truncate text-xs text-slate-500" title={event.reason}>by {event.actor_name}{event.reason ? `: ${event.reason}` : ""}</p>
  </li>;
}

function ActivityList({ events, projectNames }) {
  return groupByDay(events).map(group => <section key={group.day} className="min-w-0">
    <h4 className="pt-2 text-xs text-slate-500">{group.day}</h4>
    <ul className="divide-y divide-slate-100">{group.events.map(event => <ActivityItem key={event.id} event={event} projectName={projectNames.get(event.project_id)} />)}</ul>
  </section>);
}

function ActivityPanel({ events, projects, projectNames, initialProject = "", onClose }) {
  const [projectId, setProjectId] = useState(initialProject);
  const [kind, setKind] = useState("project");
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = event => { if (event.key === "Escape") closeRef.current(); };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previous; document.removeEventListener("keydown", onKey); };
  }, []);
  const shown = events.filter(event => (!projectId || String(event.project_id) === String(projectId)) && matchesKind(event, projectId ? "all" : kind));
  return createPortal(<div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <section role="dialog" aria-modal="true" aria-label="Activity" className="flex h-full w-full max-w-[540px] flex-col bg-white shadow-[-16px_0_50px_rgba(21,23,26,.14)]">
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div><h2 className="text-lg font-normal text-slate-950">Activity</h2><p className="text-[13px] text-slate-500">{shown.length} {shown.length === 1 ? "event" : "events"}, newest first</p></div>
        <button type="button" onClick={onClose} aria-label="Close panel" className="grid size-10 place-items-center rounded-xl border border-slate-200 text-slate-700 hover:bg-slate-50"><X size={18} /></button>
      </header>
      <div className="grid gap-2 border-b border-line px-5 py-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs text-slate-500">Project
          <select value={projectId} onChange={event => setProjectId(event.target.value)} className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-sm text-slate-900 outline-none focus:border-blue-600">
            <option value="">All projects</option>
            {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-slate-500">Kind
          <select value={projectId ? "all" : kind} disabled={Boolean(projectId)} onChange={event => setKind(event.target.value)} className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-sm text-slate-900 outline-none focus:border-blue-600 disabled:bg-slate-50 disabled:text-slate-500">
            {KINDS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
      </div>
      <div className="so-scroll min-h-0 flex-1 overflow-y-auto px-5 pb-5">
        {shown.length ? <ActivityList events={shown} projectNames={projectId ? new Map() : projectNames} /> : <p className="py-10 text-center text-sm text-slate-500">No activity matches these filters.</p>}
      </div>
    </section>
  </div>, document.body);
}

const STALE = 7 * 86400000;

function LastUpdateCell({ update, onOpen }) {
  if (!update) return <button type="button" onClick={onOpen} aria-label="No recent updates. Show this project's activity" className="text-left text-xs text-orange-700 hover:underline">None recently</button>;
  const stale = Date.now() - new Date(update.occurred_at).getTime() > STALE;
  return <button type="button" onClick={onOpen} aria-label={`Last update ${relativeAge(update.occurred_at)}: ${update.actor_name}, ${actionText(update.action).toLowerCase()}. Show this project's activity`} title={`${actionText(update.action)} by ${update.actor_name}${update.reason ? `: ${update.reason}` : ""}`} className="block max-w-[220px] text-left">
    <span className={cn("block text-sm", stale ? "text-orange-700" : "text-slate-800")}>{relativeAge(update.occurred_at)}</span>
    <span className="block truncate text-xs text-slate-500">{update.actor_name}, {actionText(update.action).toLowerCase()}</span>
  </button>;
}

export function AdminProjectsOverview({ onOpenProject }) {
  const [projects, setProjects] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [chip, setChip] = useState("all");
  const [sort, setSort] = useState({ key: "standing", direction: "asc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // null = closed, "" = all projects, an id = that project's events.
  const [activityFor, setActivityFor] = useState(null);

  async function load() {
    setLoading(true);
    setError("");
    // The timeline only adds dates and days late; the page still works
    // without it, so its failure must not blank the table.
    const [overview, events, rows] = await Promise.allSettled([
      adminVisibilityApi.projectsOverview(),
      adminVisibilityApi.activity({ limit: 500 }),
      projectsApi.timeline(),
    ]);
    if (overview.status === "fulfilled") setProjects(Array.isArray(overview.value) ? overview.value : []);
    else setError(overview.reason?.message || "The portfolio could not be loaded.");
    if (events.status === "fulfilled") setActivity(Array.isArray(events.value) ? events.value : []);
    if (rows.status === "fulfilled") setTimeline(Array.isArray(rows.value) ? rows.value : []);
    setLoading(false);
  }

  useEffect(() => { load(); }, []);
  useEffect(() => { setPage(1); }, [search, chip, sort, pageSize]);

  const enriched = useMemo(() => {
    const byId = new Map(timeline.map(row => [String(row.project_id), row]));
    // Events arrive newest first, so the first one seen per project is its latest.
    const latest = new Map();
    activity.forEach(event => { if (event.project_id && !latest.has(String(event.project_id))) latest.set(String(event.project_id), event); });
    return projects.map(project => {
      const row = byId.get(String(project.id));
      return {
        ...project,
        standing: portfolioStanding(project, row),
        planned: row && RUNNING.has(project.status) ? plannedPercent(row) : null,
        handover: row?.target_handover_date || null,
        days_late: row?.days_late || 0,
        last_update: latest.get(String(project.id)) || null,
      };
    });
  }, [projects, timeline, activity]);

  const counts = useMemo(() => Object.fromEntries(CHIPS.map(key => [key, key === "all"
    ? enriched.filter(project => project.standing !== "archived").length
    : enriched.filter(project => project.standing === key).length])), [enriched]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return enriched.filter(project => {
      if (chip === "all" ? project.standing === "archived" : project.standing !== chip) return false;
      return !term || [project.code, project.name, project.pm_name, project.site].some(value => value?.toLowerCase().includes(term));
    });
  }, [enriched, chip, search]);

  const sorted = useMemo(() => sortPortfolio(filtered, sort.key, sort.direction), [filtered, sort]);
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const pageSafe = Math.min(page, totalPages);
  const pageProjects = sorted.slice((pageSafe - 1) * pageSize, pageSafe * pageSize);
  const projectNames = useMemo(() => new Map(projects.map(project => [project.id, project.name])), [projects]);

  function onSort(key) {
    setSort(current => current.key === key
      ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
      // Counts read best biggest-first; names and dates read best A-Z / soonest.
      : { key, direction: ["overdue", "blocked", "no_update", "progress"].includes(key) ? "desc" : "asc" });
    // "Last update" ascending puts the quietest sites first, which is the point of sorting it.
  }

  const open = project => onOpenProject?.(project.code);

  if (loading) return <div className="grid min-h-40 place-items-center"><LoadingSpinner label="Loading portfolio..." /></div>;

  return <div className="grid min-w-0 gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[17px] font-medium text-slate-950">Every project, side by side</h2>
          <p className="mt-0.5 text-sm text-slate-500">Compare health, progress against plan and open issues across all sites.</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex h-10 w-full items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 focus-within:border-blue-600 focus-within:ring-4 focus-within:ring-blue-600/10 sm:w-64">
            <Search size={16} className="text-slate-500" aria-hidden="true" />
            <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search projects, PM or site" aria-label="Search projects" className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400" />
          </label>
          <button type="button" onClick={() => setActivityFor("")} className="flex h-10 shrink-0 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 hover:border-slate-300 hover:bg-slate-50"><History size={16} aria-hidden="true" />Activity <span className="tabular-nums text-slate-400">{activity.length}</span></button>
          <RefreshButton size="sm" className="h-10" loading={loading} onClick={load} />
        </div>
      </header>

      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-2xl border border-line bg-white px-4 py-3 text-sm text-slate-600">
        <span className="text-slate-950">This week</span>
        <span>{weekDigest(activity)}</span>
      </p>

      {error && <Alert tone="danger">{error}</Alert>}

      <div role="tablist" aria-label="Filter by health" className="so-scroll flex gap-1.5 overflow-x-auto pb-0.5">
        {CHIPS.filter(key => key === "all" || counts[key] > 0 || ["on_track", "at_risk", "delayed"].includes(key)).map(key => {
          const selected = chip === key;
          return <button key={key} type="button" role="tab" aria-selected={selected} onClick={() => setChip(key)} className={cn("flex h-9 shrink-0 items-center gap-1.5 rounded-lg border px-3 text-[13px] transition-colors", selected ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300")}>
            {key === "all" ? "All" : STANDING[key].label} <span className={cn("tabular-nums", selected ? "text-slate-300" : "text-slate-400")}>{counts[key]}</span>
          </button>;
        })}
      </div>

      <section aria-label="Projects" className="overflow-hidden rounded-[22px] border border-line bg-white">
        {pageProjects.length === 0
          ? <EmptyState className="m-4" title="No projects match" description={search.trim() ? "Try a different search term or another filter." : "No project is in this group right now."} />
          : <>
            <PortfolioTable projects={pageProjects} sort={sort} onSort={onSort} onOpen={open} onOpenActivity={id => setActivityFor(String(id))} />
            <PortfolioCards projects={pageProjects} onOpen={open} />
          </>}
        {sorted.length > 0 && <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-slate-50 px-4 py-2.5">
          <span className="text-xs text-slate-500">Showing {(pageSafe - 1) * pageSize + 1}–{Math.min(pageSafe * pageSize, sorted.length)} of {sorted.length}</span>
          {totalPages > 1 && <nav aria-label="Portfolio pages" className="flex items-center gap-1">
            <button type="button" aria-label="Previous page" disabled={pageSafe === 1} onClick={() => setPage(pageSafe - 1)} className="grid size-8 place-items-center rounded-lg text-slate-600 hover:bg-white disabled:opacity-40"><ChevronLeft size={16} /></button>
            {paginationItems(pageSafe, totalPages).map((item, index) => item === "..."
              ? <span key={`gap-${index}`} className="px-1 text-xs text-slate-400">...</span>
              : <button key={item} type="button" aria-current={item === pageSafe ? "page" : undefined} onClick={() => setPage(item)} className={cn("grid size-8 place-items-center rounded-lg text-xs tabular-nums", item === pageSafe ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-white")}>{item}</button>)}
            <button type="button" aria-label="Next page" disabled={pageSafe === totalPages} onClick={() => setPage(pageSafe + 1)} className="grid size-8 place-items-center rounded-lg text-slate-600 hover:bg-white disabled:opacity-40"><ChevronRight size={16} /></button>
          </nav>}
          <label className="flex items-center gap-2 text-xs text-slate-500">Rows
            <select value={pageSize} onChange={event => setPageSize(Number(event.target.value))} className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-800 outline-none focus:border-blue-600">
              {PAGE_SIZES.map(size => <option key={size} value={size}>{size}</option>)}
            </select>
          </label>
        </footer>}
      </section>

      {activityFor !== null && <ActivityPanel events={activity} projects={projects} projectNames={projectNames} initialProject={activityFor} onClose={() => setActivityFor(null)} />}
  </div>;
}
