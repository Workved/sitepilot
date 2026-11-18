import { useEffect, useRef, useState } from "react";
import { CalendarCheck, CalendarRange, ClipboardList, FolderKanban, GitBranch, Plus, ShieldCheck } from "lucide-react";
import { projectsApi } from "../../api/projectsApi";
import { EmptyState, LoadingSpinner, RefreshButton, Select } from "../../components/ui";
import { readRoute } from "../../lib/route";
import { canAddTasks } from "../projects/components/TaskScope";
import { AddRunningTaskModal } from "./components/AddRunningTaskModal";
import { DependencyControlView } from "./components/DependencyControlView";
import { ExecutionCalendarView } from "./components/ExecutionCalendarView";
import { ExternalApprovalsPanel } from "./components/ExternalApprovalsPanel";
import { MyAssignedWorkList } from "./components/MyAssignedWorkList";
import { SupervisorOperationsBoard } from "./components/SupervisorOperationsBoard";
import { TaskActionView } from "./components/TaskActionView";

// U2 (Task Execution Engine, Phase 1) through this redesign: the old shared
// "Tasks" + "Timeline" tabs are now one role-specific view - an Execution
// Calendar for Admin/PM/Super Admin, a 3-Day Operations Board for
// Supervisor, and a My Assigned Work list (+ its own Task Detail Action
// View) for Internal Employee. Each owns its own task fetch, count tiles and
// filters; this page only decides which one to mount and still owns the
// Dependencies/External Approvals tabs and project-picker header, unchanged.

function roleViewMeta(role) {
  if (role === "internal_employee") return { key: "work", label: "My Work", Icon: ClipboardList };
  if (role === "supervisor") return { key: "board", label: "3-Day Board", Icon: CalendarRange };
  return { key: "calendar", label: "Execution Calendar", Icon: CalendarRange };
}

export function ExecutionPage({ user }) {
  // A link such as ?tab=execution&project=<code>&pane=approvals (sent with a
  // Telegram external-approval review) opens that project's External
  // Approvals tab. Read once on mount; the page keeps its own state after.
  const [linked] = useState(readRoute);
  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectId, setProjectId] = useState("");
  const [view, setView] = useState(null);
  const [dependencies, setDependencies] = useState({ items: [], total: 0, excluded_warning_count: 0 });
  // U18: the project's memberships, which decide who may record an approval
  // decision - the same fact the backend checks, rather than the actor's
  // global role.
  const [project, setProject] = useState(null);
  const viewMeta = roleViewMeta(user.role);
  const [activeTab, setActiveTab] = useState(linked.pane === "approvals" ? "approvals" : viewMeta.key);
  const linkedTab = useRef(linked.pane === "approvals" ? "approvals" : null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  // Internal Employee only: which of their own tasks is open in the Task
  // Detail Action View. `myTasks` is the list MyAssignedWorkList fetched,
  // lifted up so TaskActionView can render the same row without a second
  // fetch of the same task.
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [myTasks, setMyTasks] = useState([]);
  // Bumped by the header Refresh button. Included in the two effects below so
  // they rerun on demand, and in the currently-mounted role view's `key` so
  // it remounts and refetches too (each role view owns its own task fetch -
  // see the module comment above).
  const [reloadToken, setReloadToken] = useState(0);
  const [addingTask, setAddingTask] = useState(false);

  useEffect(() => {
    let active = true;
    setProjectsLoading(true);
    projectsApi.list({ status: "active" })
      .then(items => {
        if (!active) return;
        setProjects(items);
        setProjectId(current => {
          if (items.some(project => project.id === current)) return current;
          const linkedProject = linked.project && items.find(project => project.code === linked.project);
          return linkedProject?.id || items[0]?.id || "";
        });
      })
      .catch(err => { if (active) setError(err.message || "Unable to load active projects."); })
      .finally(() => { if (active) setProjectsLoading(false); });
    return () => { active = false; };
  }, [reloadToken, linked.project]);

  useEffect(() => {
    if (!projectId) {
      setView(null);
      setDependencies({ items: [], total: 0, excluded_warning_count: 0 });
      setProject(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setError("");
    if (user.role === "internal_employee") {
      // executionTasks/dependencies/the project record are whole-project
      // baselines, not scoped to this actor - MyAssignedWorkList/
      // TaskActionView already fetch their own (server-filtered) task list
      // directly, so there's nothing project-wide for this role to load
      // here. The Dependencies tab this project record would authorise is
      // not offered to an Internal Employee either.
      setView(null);
      setDependencies({ items: [], total: 0, excluded_warning_count: 0 });
      setProject(null);
      setDetailLoading(false);
      return () => { active = false; };
    }
    Promise.all([projectsApi.executionTasks(projectId), projectsApi.dependencies(projectId), projectsApi.detail(projectId)])
      .then(([tasksResponse, dependenciesResponse, projectResponse]) => {
        if (!active) return;
        setView(tasksResponse);
        setDependencies(dependenciesResponse);
        setProject(projectResponse);
      })
      .catch(err => {
        if (!active) return;
        setView(null);
        setDependencies({ items: [], total: 0, excluded_warning_count: 0 });
        setProject(null);
        setError(err.message || "Unable to load this project's task baseline.");
      })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [projectId, user.role, reloadToken]);

  const selectedProject = projects.find(project => project.id === projectId);

  // A project switch must not leave the previous project's open task detail
  // behind for the new project. The first project chosen keeps a linked tab.
  useEffect(() => {
    setSelectedTaskId(null);
    setMyTasks([]);
    if (!projectId) return;
    setActiveTab(linkedTab.current || viewMeta.key);
    linkedTab.current = null;
  }, [projectId]);

  const selectedMyTask = myTasks.find(task => task.id === selectedTaskId) || null;

  return (
    <section className="grid gap-5">
      <header className="flex flex-col gap-4 rounded-[24px] border border-slate-200/80 bg-white p-5 shadow-[0_16px_50px_rgba(15,23,42,.06)] sm:p-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[.2em] text-blue-700"><CalendarCheck size={15}/> {user.role === "internal_employee" ? "Your assigned tasks" : "Active project task view"}</div>
          <h2 className="mt-2 text-2xl font-black tracking-[-.035em] text-slate-950 sm:text-3xl">{view?.project_name || selectedProject?.name || "Select an active project"}</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{user.role === "internal_employee" ? "Only tasks you're actively assigned to support appear here - update their status, log progress and upload evidence." : "Track and drive task execution for this activated project: status updates, evidence, verification/approval, blockers/delays and support assignment."}</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="grid min-w-[240px] gap-2 text-sm font-bold text-slate-700">
            <span>Active project</span>
            <Select value={projectId} onChange={event => setProjectId(event.target.value)} disabled={projectsLoading}>
              <option value="">{projectsLoading ? "Loading..." : "Select project"}</option>
              {projects.map(project => <option key={project.id} value={project.id}>{project.name} ({project.code})</option>)}
            </Select>
          </label>
          {canAddTasks(user) && projectId && project && <button type="button" onClick={() => setAddingTask(true)} className="flex min-h-11 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-black text-white hover:bg-blue-700"><Plus size={16}/> Add task</button>}
          <RefreshButton loading={projectsLoading || detailLoading} onClick={() => setReloadToken(token => token + 1)}/>
        </div>
      </header>

      {addingTask && <AddRunningTaskModal projectId={projectId} project={project} user={user} onClose={() => setAddingTask(false)} onAdded={() => setReloadToken(token => token + 1)}/>}

      {error && <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">{error}</div>}

      {!projectsLoading && !projects.length ? (
        <EmptyState icon={<FolderKanban size={21}/>} title="No activated projects yet" description="A task baseline appears here once Admin activates a project from its draft setup."/>
      ) : detailLoading ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading task baseline..."/></div>
      ) : (view || (user.role === "internal_employee" && selectedProject)) ? (
        <>
          <div className="rounded-2xl border border-slate-200 bg-white p-2">
            <div className="flex flex-wrap gap-2">
              {(user.role === "internal_employee"
                ? [[viewMeta.key, viewMeta.label, viewMeta.Icon], ["approvals", "External Approvals", ShieldCheck]]
                : [
                    [viewMeta.key, viewMeta.label, viewMeta.Icon],
                    // Supervisors keep their 3-day board and get the calendar too.
                    ...(user.role === "supervisor" ? [["calendar", "Calendar", CalendarCheck]] : []),
                    ["dependencies", "Dependencies", GitBranch],
                    ["approvals", "External Approvals", ShieldCheck],
                  ]
              ).map(([key, label, Icon]) => (
                <button key={key} onClick={() => setActiveTab(key)} className={`flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold transition ${activeTab === key ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}>
                  <Icon size={16}/>{label}
                </button>
              ))}
            </div>
          </div>

          {activeTab === viewMeta.key && user.role === "internal_employee" && (
            selectedMyTask
              ? <TaskActionView
                  key={selectedMyTask.id}
                  projectId={projectId}
                  project={project}
                  task={selectedMyTask}
                  user={user}
                  candidates={[]}
                  onBack={() => setSelectedTaskId(null)}
                  onChanged={() => {}}
                />
              : <MyAssignedWorkList key={reloadToken} projectId={projectId} onOpenTask={setSelectedTaskId} onTasksLoaded={setMyTasks}/>
          )}

          {activeTab === viewMeta.key && user.role === "supervisor" && <SupervisorOperationsBoard key={reloadToken} projectId={projectId} user={user}/>}

          {activeTab === viewMeta.key && !["internal_employee", "supervisor"].includes(user.role) && <ExecutionCalendarView key={reloadToken} projectId={projectId} user={user} onSelectProject={setProjectId}/>}

          {activeTab === "calendar" && user.role === "supervisor" && <ExecutionCalendarView key={reloadToken} projectId={projectId} user={user} onSelectProject={setProjectId}/>}

          {activeTab === "dependencies" && <DependencyControlView key={reloadToken} projectId={projectId} project={project} user={user} dependencies={dependencies}/>}

          {activeTab === "approvals" && <ExternalApprovalsPanel key={reloadToken} projectId={projectId} project={project} user={user}/>}        </>
      ) : !error && (
        <EmptyState icon={<CalendarCheck size={21}/>} title="Select an active project" description="Choose an activated project above to view its task baseline."/>
      )}
    </section>
  );
}
