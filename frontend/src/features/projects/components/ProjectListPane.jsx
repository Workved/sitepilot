import { Check, ChevronDown, ChevronsUpDown, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pill } from "../../../components/ui";
import { initials, relativeAge } from "../../../utils/format";

const statusTone = { draft: "gray", active: "green", on_hold: "orange", completed: "blue", archived: "gray" };
const statusLabel = value => value.replace("_", " ");

// "All" deliberately excludes archived: an archived project is closed
// business, and letting it accumulate in the default-widest filter makes
// that filter useless within a year. The Archived option only appears when
// there is something archived to look at.
const BASE_FILTERS = [["active", "Active"], ["draft", "Draft"], ["on_hold", "On hold"], ["completed", "Completed"], ["all", "All"]];

export const SORTS = [
  ["attention", "Needs attention first"],
  ["recent", "Recent activity"],
  ["name", "Name"],
];

export function filterProjects(projects, filter) {
  if (filter === "all") return projects.filter(item => item.status !== "archived");
  return projects.filter(item => item.status === filter);
}

export function sortProjects(projects, sort, { attentionByProject = {}, summaries = {} } = {}) {
  const byName = (a, b) => a.name.localeCompare(b.name);
  const lastActivity = project => {
    const value = summaries?.[project.id]?.last_activity_at;
    return value ? new Date(value).getTime() : 0;
  };
  const list = [...projects];
  if (sort === "name") return list.sort(byName);
  if (sort === "recent") return list.sort((a, b) => lastActivity(b) - lastActivity(a) || byName(a, b));
  return list.sort((a, b) => (attentionByProject[b.id] || 0) - (attentionByProject[a.id] || 0) || lastActivity(b) - lastActivity(a) || byName(a, b));
}

function setupCount(project) {
  return [
    project.setup?.has_project_manager,
    project.setup?.has_site_supervisor,
    project.setup?.has_template,
    project.setup?.has_target_handover_date,
  ].filter(Boolean).length;
}

// Initials tile tint per lifecycle status - the same soft tints the
// Overview project cards use, so a project looks the same everywhere.
const tileTone = {
  draft: "bg-slate-100 text-slate-700",
  active: "bg-blue-50 text-blue-800",
  on_hold: "bg-orange-50 text-orange-800",
  completed: "bg-emerald-50 text-emerald-800",
  archived: "bg-slate-100 text-slate-500",
};

// One figure and one thin bar: setup readiness for a draft, task progress
// otherwise. Nothing at all when the summaries read model is unavailable,
// rather than a permanently empty bar that reads as "0% done".
function progressFor(project, summary) {
  if (project.status === "draft") {
    const ready = setupCount(project);
    return { label: `${ready}/4`, title: "Setup steps complete", width: ready * 25, color: "var(--color-behind)" };
  }
  if (!summary || typeof summary.progress_pct !== "number") return null;
  return { label: `${summary.progress_pct}%`, title: "Tasks complete", width: summary.progress_pct, color: "var(--color-blue-600)" };
}

function ProjectRow({ project, summary, attentionCount, active, showStatus, onOpen }) {
  const age = relativeAge(summary?.last_activity_at);
  const pm = project.memberships?.find(item => item.project_role === "project_manager")?.name;
  const progress = progressFor(project, summary);
  return <button
    type="button"
    onClick={() => onOpen(project)}
    aria-current={active ? "true" : undefined}
    className={`block w-full rounded-xl px-2.5 pb-2 pt-2.5 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 ${active ? "bg-white shadow-[0_0_0_1px_var(--color-slate-200),0_1px_3px_rgba(21,23,26,.06)]" : "hover:bg-white"}`}
  >
    <span className="flex items-center gap-2.5">
      <span className={`grid size-8 shrink-0 place-items-center rounded-lg text-[11px] font-medium ${tileTone[project.status] || tileTone.draft}`} aria-hidden="true">{initials(project.name)}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <strong className="min-w-0 flex-1 truncate text-sm font-medium text-slate-950">{project.name}</strong>
          {attentionCount > 0 && <span className="grid h-[18px] min-w-[18px] shrink-0 place-items-center rounded-md bg-rose-600 px-1 text-[11px] text-white" title={`${attentionCount} need attention`}>{attentionCount}</span>}
          {progress && <span className="shrink-0 text-xs tabular-nums text-slate-700" title={progress.title}>{progress.label}</span>}
        </span>
        <span className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
          {showStatus && <Pill tone={statusTone[project.status]} className="py-0 text-[11px]">{statusLabel(project.status)}</Pill>}
          <span className="min-w-0 flex-1 truncate">{[project.client_name, pm || "No PM"].filter(Boolean).join(", ")}</span>
          {age && <span className="shrink-0">{age}</span>}
        </span>
      </span>
    </span>
    {progress && <span className="ml-[42px] mt-2 block h-[3px] overflow-hidden rounded-full bg-slate-200/70" aria-hidden="true">
      <span className="block h-full rounded-full" style={{ width: `${progress.width}%`, background: progress.color }}/>
    </span>}
  </button>;
}

function ViewMenu({ filters, counts, filter, onFilterChange, sort, onSortChange }) {
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
  const current = filters.find(([key]) => key === filter)?.[1] || "All";

  return <div className="relative shrink-0" ref={holder}>
    <button type="button" onClick={() => setOpen(value => !value)} aria-haspopup="true" aria-expanded={open} aria-label={`Showing ${current} projects. Change filter or sort`}
      className="flex h-10 items-center gap-1.5 rounded-xl border border-slate-200 bg-white pl-3 pr-2 text-[13px] text-slate-800 transition hover:border-slate-300">
      {current}<span className="tabular-nums text-slate-400">{counts[filter]}</span><ChevronDown size={15} className="text-slate-500" aria-hidden="true"/>
    </button>
    {open && <div role="menu" aria-label="Filter and sort projects" className="absolute right-0 top-[calc(100%+6px)] z-30 w-60 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      <p className="px-2.5 pb-1 pt-1.5 text-xs text-slate-500">Status</p>
      {filters.map(([key, label]) => <button key={key} type="button" role="menuitemradio" aria-checked={filter === key}
        onClick={() => { onFilterChange(key); setOpen(false); }}
        className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-slate-800 hover:bg-slate-50">
        <span className="flex-1">{label}</span>
        <span className="tabular-nums text-xs text-slate-400">{counts[key]}</span>
        <Check size={15} className={filter === key ? "text-slate-950" : "invisible"} aria-hidden="true"/>
      </button>)}
      <div className="my-1.5 h-px bg-line"/>
      <p className="px-2.5 pb-1 pt-1 text-xs text-slate-500">Sort by</p>
      {SORTS.map(([key, label]) => <button key={key} type="button" role="menuitemradio" aria-checked={sort === key}
        onClick={() => { onSortChange(key); setOpen(false); }}
        className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-slate-800 hover:bg-slate-50">
        <span className="flex-1">{label}</span>
        <Check size={15} className={sort === key ? "text-slate-950" : "invisible"} aria-hidden="true"/>
      </button>)}
    </div>}
  </div>;
}

export function ProjectListPane({ projects, summaries, attentionByProject, filter, onFilterChange, sort = "attention", onSortChange = () => {}, search, onSearchChange, selectedId, onOpen, actions }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const hasArchived = projects.some(item => item.status === "archived");
  const filters = hasArchived ? [...BASE_FILTERS, ["archived", "Archived"]] : BASE_FILTERS;

  const counts = useMemo(() => Object.fromEntries(
    filters.map(([key]) => [key, filterProjects(projects, key).length])
  ), [projects, hasArchived]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    const matched = filterProjects(projects, filter).filter(project => !term || [project.code, project.name, project.client_name, project.site_address]
      .some(value => String(value || "").toLowerCase().includes(term)));
    return sortProjects(matched, sort, { attentionByProject, summaries });
  }, [projects, filter, search, sort, attentionByProject, summaries]);

  const selected = projects.find(item => item.id === selectedId);
  // A single status filter already says the status; repeat it per row only
  // when the list mixes statuses.
  const showStatus = filter === "all";

  function open(project) {
    setMobileOpen(false);
    onOpen(project);
  }

  return <div className="flex min-h-0 min-w-0 flex-col border-b border-line bg-slate-50 lg:border-b-0 lg:border-r">
    {actions && <div className="flex items-center justify-between gap-2 px-3 pt-3">{actions}</div>}

    {/* Phone: the list folds behind the current project so the workspace
        gets the screen; desktop always shows it. */}
    <button type="button" onClick={() => setMobileOpen(value => !value)} aria-expanded={mobileOpen}
      className="mx-3 mt-3 flex h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-left lg:hidden">
      <span className="min-w-0 flex-1 truncate text-sm text-slate-950">{selected?.name || "Choose a project"}</span>
      <span className="text-xs text-slate-500">Projects {visible.length}</span>
      <ChevronsUpDown size={16} className="text-slate-500" aria-hidden="true"/>
    </button>

    <div className={`${mobileOpen ? "flex" : "hidden"} min-h-0 flex-1 flex-col lg:flex`}>
      <div className="flex items-center gap-2 p-3">
        <label className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 focus-within:border-blue-600 focus-within:ring-4 focus-within:ring-blue-600/10">
          <Search size={16} className="shrink-0 text-slate-500" aria-hidden="true"/>
          <input
            value={search}
            onChange={event => onSearchChange(event.target.value)}
            placeholder="Search projects"
            aria-label="Search projects"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
        </label>
        <ViewMenu filters={filters} counts={counts} filter={filter} onFilterChange={onFilterChange} sort={sort} onSortChange={onSortChange}/>
      </div>

      <nav aria-label="Project list" className="so-scroll grid max-h-[60vh] min-h-0 flex-1 content-start gap-0.5 overflow-y-auto px-2 pb-3 lg:max-h-none">
        {visible.length
          ? visible.map(project => <ProjectRow
              key={project.id}
              project={project}
              summary={summaries?.[project.id]}
              attentionCount={attentionByProject?.[project.id] || 0}
              active={selectedId === project.id}
              showStatus={showStatus}
              onOpen={open}
            />)
          : <p className="px-4 py-10 text-center text-sm text-slate-500">{search.trim() ? "No projects match this search." : "No projects in this filter."}</p>}
      </nav>
    </div>
  </div>;
}
