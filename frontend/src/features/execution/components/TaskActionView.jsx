import { AlertTriangle, ArrowLeft, ClipboardEdit, History, LayoutGrid, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Pill } from "../../../components/ui";
import { actorProjectRoles, canExecute, forwardTargetsFor, STATUS_TONE, TaskDetailContent } from "./TaskDetailContent";

const TABS = [
  ["overview", "Overview", LayoutGrid],
  ["actions", "Action Forms", SlidersHorizontal],
  ["activity", "Activity Log", History],
];

function anchorTo(id) {
  document.getElementById(id)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

// Why this task needs attention right now, from the list-item summary alone
// (readiness/variance/lifecycle_status are all already on that payload) - no
// need to wait on the detail fetch just to decide whether to show the
// callout at all.
function attentionReason(task) {
  if (task.lifecycle_status === "rejected") return "This task was rejected and needs to be reworked.";
  if (task.readiness?.state === "blocked") return "This task is blocked - see the Overview tab for what it's waiting on.";
  if (task.variance?.status === "late") return `This task is running ${task.variance.days} day${task.variance.days === 1 ? "" : "s"} behind its planned schedule.`;
  return null;
}

// Internal Employee, detail mode ("Task Detail Action View"). Replaces the
// old inline accordion row for this role with a focused full-pane screen,
// using the same 3-tab (Overview/Action Forms/Activity Log) structure the
// drawer uses - the Action Center callout and Quick Info both read off the
// full detail payload, lifted from TaskDetailContent via `onDetailLoaded`
// rather than a second fetch of the same task.
export function TaskActionView({ projectId, project, task, user, candidates, onBack, onChanged }) {
  const [activeTab, setActiveTab] = useState("overview");
  const [detail, setDetail] = useState(null);
  const [blockerDelayRequest, setBlockerDelayRequest] = useState(null);
  const roles = actorProjectRoles(project, user);

  useEffect(() => { setActiveTab("overview"); }, [task.id]);

  const reason = attentionReason(task);
  const forwardTargets = detail ? forwardTargetsFor(detail, user, roles) : [];
  const showUpdateProgress = detail?.lifecycle_status === "in_progress" && canExecute(detail, user, roles);
  const showSubmit = forwardTargets.includes("submitted");
  const showReportDelay = detail && !["completed", "cancelled"].includes(detail.lifecycle_status);
  const showActionCenter = Boolean(reason) && (showUpdateProgress || showSubmit || showReportDelay);

  function goToActionForms(anchorId) {
    setActiveTab("actions");
    requestAnimationFrame(() => anchorTo(anchorId));
  }

  function requestBlockerDelay() {
    setBlockerDelayRequest({ kind: "blocker", nonce: Date.now() });
    goToActionForms("action-blockers-delays");
  }

  return <div className="grid gap-4">
    <header className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4">
      <button type="button" onClick={onBack} aria-label="Back to my assigned work" className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100">
        <ArrowLeft size={18}/>
      </button>
      <div className="min-w-0 flex-1">
        <span className="font-mono text-xs font-black text-blue-700">{task.original_code}</span>
        <h2 className="truncate text-lg font-black text-slate-950">{task.title}</h2>
        <span className="text-xs text-slate-500">{[task.phase, task.category].filter(Boolean).join(" / ")}</span>
      </div>
      <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
    </header>

    {showActionCenter && <section className="rounded-2xl border border-amber-300 bg-amber-50 p-4">
      <h3 className="flex items-center gap-2 text-sm font-black text-amber-900"><AlertTriangle size={16}/> Action Center</h3>
      <p className="mt-1 text-sm text-amber-800">{reason}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {showUpdateProgress && <Button size="sm" onClick={() => goToActionForms("action-progress")}><ClipboardEdit size={14}/> Update Progress</Button>}
        {showSubmit && <Button size="sm" onClick={() => goToActionForms("action-status")}><ShieldCheck size={14}/> Submit For Review</Button>}
        {showReportDelay && <Button size="sm" variant="secondary" onClick={requestBlockerDelay}><AlertTriangle size={14}/> Report Delay · Blocker</Button>}
      </div>
    </section>}

    {/* Dependencies/assignee/support/dates now live in TaskDetailContent's
        own Overview tab (shared across every view, not duplicated here) -
        Approvals Pending is the one Quick Info stat that tab doesn't carry,
        so it's the one kept here. */}
    {detail && <section className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4">
      <span className="flex items-center gap-1.5 text-xs font-medium text-slate-500"><ShieldCheck size={12}/> Approvals Pending</span>
      <strong className="text-xl text-slate-950">{detail.readiness?.reasons?.filter(item => item.kind === "approval").length || 0}</strong>
    </section>}

    <nav className="flex gap-1 rounded-2xl border border-slate-200 bg-white p-1" aria-label="Task detail tabs">
      {TABS.map(([key, label, Icon]) => (
        <button
          key={key}
          type="button"
          aria-current={activeTab === key ? "true" : undefined}
          onClick={() => setActiveTab(key)}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-bold transition ${activeTab === key ? "bg-blue-600 text-white" : "text-slate-500 hover:bg-slate-100"}`}
        ><Icon size={15}/> {label}</button>
      ))}
    </nav>

    <TaskDetailContent
      projectId={projectId}
      project={project}
      task={task}
      user={user}
      roles={roles}
      candidates={candidates}
      onChanged={onChanged}
      autoOpenBlockerDelay={blockerDelayRequest?.kind}
      onDetailLoaded={setDetail}
      activeTab={activeTab}
    />
  </div>;
}
