import { Activity, CalendarCheck, Gauge, Layers3, Pencil, ShieldCheck, Truck, UsersRound } from "lucide-react";
import { initials } from "../../../utils/format";
import { planGap, scheduleWindow } from "../../../utils/schedule";
import { useEffect, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Alert, Button, LoadingSpinner, Pill } from "../../../components/ui";
import { ProjectActivityPane } from "./ProjectActivityPane";
import { ProjectDashboard } from "./ProjectDashboard";
import { ProjectDependencies } from "./ProjectDependencies";
import { ProjectExternalGates } from "./ProjectExternalGates";
import { ProjectLifecyclePane } from "./ProjectLifecyclePane";
import { ProjectOverviewPane } from "./ProjectOverviewPane";
import { ProjectSetupPane } from "./ProjectSetupPane";
import { ProjectTeamPane } from "./ProjectTeamPane";
import { ProjectTemplateReview } from "./ProjectTemplateReview";
import { ProjectVendorPanel } from "./ProjectVendorPanel";

const statusTone = { draft: "gray", active: "green", on_hold: "orange", completed: "blue", archived: "gray" };
const longDate = value => (value
  ? new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
  : "Not set");

// Time used vs work done, in one line: the question a PM asks first when a
// project opens. Drafts and undated projects have no plan to compare yet.
function ScheduleBar({ project, summary }) {
  if (project.status === "draft") return null;
  const window = scheduleWindow(project);
  if (!window) return null;
  const done = typeof summary?.progress_pct === "number" ? summary.progress_pct : null;
  const gap = done == null ? null : planGap(project, done);
  const behind = Boolean(gap?.behind);
  let status;
  if (project.status === "completed") status = { text: "Handed over", tone: "text-blue-700" };
  else if (window.notStarted) status = { text: `Starts in ${window.daysToStart} ${window.daysToStart === 1 ? "day" : "days"}`, tone: "text-slate-600" };
  else if (behind) status = { text: `Behind plan by ${gap.gap} points`, tone: "text-orange-700" };
  else if (gap) status = { text: "On plan", tone: "text-emerald-700" };

  return <div className="mt-3 grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-4">
    <div className="relative h-1.5 rounded-full bg-slate-100" role="img" aria-label={`${window.planned}% of planned time used${done != null ? `, ${done}% of tasks complete` : ""}`}>
      <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${window.planned}%`, background: behind ? "var(--color-behind-soft)" : "var(--color-blue-100)" }}/>
      {done > 0 && <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${done}%`, background: behind ? "var(--color-behind)" : "var(--color-blue-600)" }}/>}
      {!window.notStarted && project.status !== "completed" && <span className="absolute -top-[5px] h-4 w-0.5 rounded bg-slate-950" style={{ left: `calc(${window.planned}% - 1px)` }}/>}
    </div>
    <p className="flex flex-wrap items-center gap-x-3 text-xs text-slate-500">
      {!window.notStarted && project.status !== "completed" && <span>Day {window.day} of {window.total}</span>}
      {done != null && <span><span className="text-slate-950">{done}%</span> done</span>}
      {status && <span className={status.tone}>{status.text}</span>}
    </p>
  </div>;
}

// Supervisors and Internal Employees have no template-authoring role, and
// the matching backend routes reject them - hiding the panes keeps the tab
// strip honest rather than offering a guaranteed 403.
const PLANNING_PANES = ["template-review", "dependencies", "external-gates"];

// Nine sections read as clutter in one flat strip, so they are grouped by
// what the reader is doing: looking (Overview, Dashboard), planning the
// schedule, managing people, and checking the record.
const PANE_GROUPS = [["look", null], ["planning", "Planning"], ["people", "People"], ["records", "Records"]];

function panesFor(project, role) {
  const first = project.status === "draft"
    ? ["overview", Layers3, "Setup", "look"]
    : ["overview", CalendarCheck, "Overview", "look"];
  const planning = [
    // Label only. The pane key stays "template-review" because it is in
    // shared URLs and matches the backend's own route names.
    ["template-review", Layers3, "Task Review", "planning"],
    ["dependencies", Layers3, "Dependencies", "planning"],
    ["external-gates", ShieldCheck, "External Gates", "planning"],
  ];
  return [
    first,
    ...(project.status === "draft" ? [] : [["dashboard", Gauge, "Dashboard", "look"]]),
    ...(["supervisor", "internal_employee"].includes(role) ? [] : planning),
    ["team", UsersRound, "Team", "people"],
    ["vendors", Truck, "Vendors", "people"],
    ["lifecycle", ShieldCheck, "Lifecycle", "records"],
    ["activity", Activity, "Activity", "records"],
  ];
}

// A person who answers for the project, shown as a small card so the role
// reads as a role, not as one more fact in a run-on line.
function PersonChip({ role, name }) {
  const missing = !name;
  return <div className="flex min-w-0 items-center gap-2.5 rounded-xl border border-line bg-white py-1.5 pl-1.5 pr-3">
    <span className={`grid size-8 shrink-0 place-items-center rounded-lg text-xs font-medium ${missing ? "bg-orange-50 text-orange-800" : "bg-blue-50 text-blue-800"}`} aria-hidden="true">{missing ? "?" : initials(name)}</span>
    <span className="min-w-0 leading-tight">
      <span className={`block truncate text-[13px] ${missing ? "text-orange-800" : "text-slate-950"}`}>{name || "Not assigned"}</span>
      <span className="block truncate text-xs text-slate-500">{role}</span>
    </span>
  </div>;
}

export function ProjectWorkspace({ projectId, references, templates = [], user, summary, attention, pane, onPaneChange, onEdit, onChanged, onDeleted }) {
  const [project, setProject] = useState(null);
  const [activity, setActivity] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setError("");
    try {
      const [detail, events] = await Promise.all([projectsApi.detail(projectId), projectsApi.activity(projectId)]);
      setProject(detail);
      setActivity(events);
    } catch (caught) {
      setError(caught?.message || "This project could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setProject(null);
    load();
  }, [projectId]);

  async function changed() {
    await load();
    await onChanged();
  }

  if (loading) return <div className="p-6"><LoadingSpinner label="Opening project…"/></div>;
  if (error) return <Alert tone="danger" className="m-4">{error}</Alert>;
  if (!project) return null;

  const panes = panesFor(project, user.role);
  const activePane = panes.some(([key]) => key === pane) ? pane : "overview";
  const pmName = project.memberships?.find(item => item.project_role === "project_manager")?.name;
  const supervisorName = project.memberships?.find(item => item.project_role === "site_supervisor")?.name;
  const canEdit = ["admin", "super_admin"].includes(user.role)
    || project.memberships?.some(item => item.project_role === "project_manager" && item.user_id === user.id);

  function renderPane() {
    switch (activePane) {
      case "overview":
        return project.status === "draft"
          ? <ProjectSetupPane project={project} activity={activity} templates={templates} user={user} onChanged={changed} onOpenPane={onPaneChange}/>
          : <ProjectOverviewPane project={project} summary={summary} attention={attention} onOpenPane={onPaneChange}/>;
      case "dashboard": return <ProjectDashboard project={project}/>;
      case "template-review": return <ProjectTemplateReview projectId={project.id} user={user} projectStatus={project.status}/>;
      case "dependencies": return <ProjectDependencies project={project} user={user}/>;
      case "external-gates": return <ProjectExternalGates project={project} user={user}/>;
      case "team": return <ProjectTeamPane project={project} references={references} user={user} onChanged={changed}/>;
      case "vendors": return <ProjectVendorPanel project={project} user={user}/>;
      case "lifecycle": return <ProjectLifecyclePane project={project} user={user} onChanged={changed} onDeleted={onDeleted}/>;
      case "activity": return <ProjectActivityPane activity={activity}/>;
      default: return null;
    }
  }

  return <div className="flex min-h-0 min-w-0 flex-1 flex-col">
    <header className="shrink-0 border-b border-line bg-white px-4 pb-0 pt-4 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
            <h2 className="min-w-0 truncate text-[22px] font-normal leading-tight tracking-[-0.02em] text-slate-950">{project.name}</h2>
            <Pill tone={statusTone[project.status]}>{project.status.replace("_", " ")}</Pill>
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-slate-500">
            {project.client_name && <span className="text-slate-700">{project.client_name}</span>}
            <span>{longDate(project.start_date)} to {longDate(project.target_handover_date)}</span>
            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{project.code}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PersonChip role="Project manager" name={pmName}/>
          <PersonChip role="Site supervisor" name={supervisorName}/>
          {canEdit && <Button variant="secondary" size="sm" className="h-11" onClick={() => onEdit(project)}><Pencil size={15} aria-hidden="true"/> Edit</Button>}
        </div>
      </div>

      <ScheduleBar project={project} summary={summary}/>

      <nav aria-label="Project sections" className="so-scroll -mx-4 mt-3 flex items-end overflow-x-auto px-4 sm:-mx-6 sm:px-6">
        {PANE_GROUPS.map(([group, groupLabel], groupIndex) => {
          const items = panes.filter(item => item[3] === group);
          if (!items.length) return null;
          return <div key={group} role="group" aria-label={groupLabel || "Summary"} className={`flex shrink-0 items-end ${groupIndex > 0 ? "ml-3 border-l border-line pl-3" : ""}`}>
            {groupLabel && <span className="mb-[13px] mr-1 hidden text-[11px] text-slate-400 xl:inline">{groupLabel}</span>}
            {items.map(([key, , label]) => {
              const active = activePane === key;
              return <button
                key={key}
                type="button"
                onClick={() => onPaneChange(key)}
                aria-current={active ? "page" : undefined}
                className={`inline-flex min-h-11 shrink-0 items-center whitespace-nowrap px-2.5 text-sm transition-colors ${active ? "text-slate-950 shadow-[inset_0_-2px_0_var(--color-slate-950)]" : "text-slate-500 hover:text-slate-950"}`}
              >{label}</button>;
            })}
          </div>;
        })}
      </nav>
    </header>

    <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">{renderPane()}</div>
  </div>;
}
