import { useEffect, useRef, useState } from "react";
import { CalendarCheck, CalendarRange, ChevronDown, ClipboardList, FolderKanban, GitBranch, Plus, ShieldCheck } from "lucide-react";
import { projectsApi } from "../../api/projectsApi";
import { Button, EmptyState, LoadingSpinner } from "../../components/ui";
import { formatDateShort } from "../../utils/format";
import { scheduleWindow } from "../../utils/schedule";
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
  // A link such as ?tab=execution&project=<code>&pane=approvals opens that
  // project's External
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
  // Bumped by the shell's refresh (which remounts this page) and after a task
  // is added. Included in the two effects below so
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
  const schedule = scheduleWindow(selectedProject);
  const sections = user.role === "internal_employee"
    ? [[viewMeta.key, viewMeta.label, viewMeta.Icon], ["approvals", "External Approvals", ShieldCheck]]
    : [
        [viewMeta.key, viewMeta.label, viewMeta.Icon],
        // Supervisors keep their 3-day board and get the calendar too.
        ...(user.role === "supervisor" ? [["calendar", "Calendar", CalendarCheck]] : []),
        ["dependencies", "Dependencies", GitBranch],
        ["approvals", "External Approvals", ShieldCheck],
      ];

  return (
    // minmax(0,1fr): an unsized grid column grows to its widest child - here
    // the project <select>, which sizes to its longest option - and pushes
    // the page past a phone screen.
    <section className="grid grid-cols-[minmax(0,1fr)] gap-5">
      {/* The project picker IS the title, so the name shows once; the
          section tabs live in the same card, like a project's workspace. */}
      <header className="rounded-[20px] border border-line bg-white px-4 pt-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {user.role === "internal_employee" && <p className="text-[13px] text-slate-500">Your assigned tasks</p>}
            <label className="relative flex max-w-full items-center">
              <span className="sr-only">Active project</span>
              <select value={projectId} onChange={event => setProjectId(event.target.value)} disabled={projectsLoading}
                className="max-w-full cursor-pointer appearance-none truncate rounded-lg bg-transparent py-0.5 pl-1 pr-8 -ml-1 text-[24px] font-normal tracking-[-0.02em] text-slate-950 outline-none hover:bg-slate-50 focus-visible:ring-4 focus-visible:ring-blue-600/10 disabled:cursor-wait">
                <option value="">{projectsLoading ? "Loading..." : "Select project"}</option>
                {projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
              <ChevronDown size={20} className="pointer-events-none absolute right-1.5 text-slate-500" aria-hidden="true"/>
            </label>
            {selectedProject && <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-slate-500">
              <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{selectedProject.code}</span>
              {selectedProject.client_name && <span className="text-slate-700">{selectedProject.client_name}</span>}
              {(selectedProject.start_date || selectedProject.target_handover_date) && <span>{formatDateShort(selectedProject.start_date) || "No start"} to {formatDateShort(selectedProject.target_handover_date) || "no handover"}</span>}
              {schedule && !schedule.notStarted && <span>Day {schedule.day} of {schedule.total}</span>}
              {schedule?.notStarted && <span>Starts in {schedule.daysToStart} {schedule.daysToStart === 1 ? "day" : "days"}</span>}
            </p>}
          </div>
          {canAddTasks(user) && projectId && project && <Button onClick={() => setAddingTask(true)}><Plus size={16}/> Add task</Button>}
        </div>

        {(view || (user.role === "internal_employee" && selectedProject)) && <nav aria-label="Execution sections" className="so-scroll -mx-4 mt-3 flex gap-1 overflow-x-auto px-4 sm:-mx-6 sm:px-6">
          {sections.map(([key, label]) => {
            const active = activeTab === key;
            return <button key={key} type="button" onClick={() => setActiveTab(key)} aria-current={active ? "page" : undefined}
              className={`inline-flex min-h-11 shrink-0 items-center gap-2 whitespace-nowrap px-2.5 text-sm transition-colors ${active ? "text-slate-950 shadow-[inset_0_-2px_0_var(--color-slate-950)]" : "text-slate-500 hover:text-slate-950"}`}>
              {label}
            </button>;
          })}
        </nav>}
      </header>

      {addingTask && <AddRunningTaskModal projectId={projectId} project={project} user={user} onClose={() => setAddingTask(false)} onAdded={() => setReloadToken(token => token + 1)}/>}

      {error && <div role="alert" className="rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}

      {!projectsLoading && !projects.length ? (
        <EmptyState icon={<FolderKanban size={21}/>} title="No activated projects yet" description="A task baseline appears here once Admin activates a project from its draft setup."/>
      ) : detailLoading ? (
        <div className="rounded-[20px] border border-line bg-white p-8"><LoadingSpinner label="Loading task baseline..."/></div>
      ) : (view || (user.role === "internal_employee" && selectedProject)) ? (
        <>
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

          {activeTab === viewMeta.key && !["internal_employee", "supervisor"].includes(user.role) && <ExecutionCalendarView key={reloadToken} projectId={projectId} user={user}/>}

          {activeTab === "calendar" && user.role === "supervisor" && <ExecutionCalendarView key={reloadToken} projectId={projectId} user={user}/>}

          {activeTab === "dependencies" && <DependencyControlView key={reloadToken} projectId={projectId} project={project} user={user} dependencies={dependencies}/>}

          {activeTab === "approvals" && <ExternalApprovalsPanel key={reloadToken} projectId={projectId} project={project} user={user}/>}        </>
      ) : !error && (
        <EmptyState icon={<CalendarCheck size={21}/>} title="Select an active project" description="Choose an activated project above to view its task baseline."/>
      )}
    </section>
  );
}
