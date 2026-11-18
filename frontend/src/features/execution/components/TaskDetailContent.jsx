import { AlertTriangle, CalendarClock, GitBranch, History, ShieldAlert, ShieldCheck, User, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, DetailGrid, Field, LoadingSpinner, Modal, Textarea } from "../../../components/ui";
import { formatDateShort, todayIso } from "../../../utils/format";
import { TaskApprovalSummary } from "./TaskApprovalSummary";
import { TaskBlockerDelayPanel } from "./TaskBlockerDelayPanel";
import { TaskDecisionModal } from "./TaskDecisionModal";
import { TaskLifecycleStepper } from "./TaskLifecycleStepper";
import { TaskProgressForm } from "./TaskProgressForm";
import { TaskSupportAssignmentPanel } from "./TaskSupportAssignmentPanel";
import { TaskTerminalSummary } from "./TaskTerminalSummary";
import { ReferenceMaterial } from "./ReferenceMaterial";
import { TaskReferenceManager } from "./TaskReferenceManager";
import { canAddTasks } from "../../projects/components/TaskScope";
import { projectsApi } from "../../../api/projectsApi";
import { TaskVendorDelegationForm } from "./TaskVendorDelegationForm";

// This is the single source of truth for what a task's detail looks like and
// which controls it offers, shared by every role-specific execution view
// (ExecutionCalendarView's/SupervisorOperationsBoard's TaskDetailDrawer, and
// Internal Employee's TaskActionView). It renders one of three panes
// (Overview / Action Forms / Activity Log) depending on `activeTab` - the
// data-fetch, permission checks and transition/decision logic below are
// shared across all three and live here exactly once, so no caller ever
// carries a second copy that could drift from the backend's own rules.

// U2: forward status-progression buttons, mirrored from
// TaskLifecycleService.ALLOWED_TRANSITIONS on the backend. This is a UX
// convenience only - the backend's allow-list is the actual authority, and
// a 409 from an out-of-band attempt is the real backstop. Verify/approve/
// reject aren't plain buttons - those are TaskDecisionModal, since they also
// write a decision record.
const FORWARD_TRANSITIONS = {
  planned: ["ready"],
  ready: ["in_progress"],
  in_progress: ["submitted"],
  rejected: ["in_progress"],
};
const CANCELLABLE_STATUSES = ["planned", "ready", "in_progress", "submitted", "verified", "approval_pending", "rejected"];
export const TRANSITION_LABEL = { ready: "Mark Ready", in_progress: "Start Task", submitted: "Submit For Review" };
export const STATUS_TONE = {
  planned: "gray", ready: "blue", in_progress: "blue", submitted: "orange",
  verified: "orange", approval_pending: "orange", rejected: "red", completed: "green", cancelled: "gray",
};

const EXECUTOR_TARGETS = ["in_progress", "submitted"];

// U6: every authority check below is keyed on the actor's membership of THIS
// project, not on their global role. The backend has always worked that way -
// `_can_cancel`, `_require_role_for_transition` and
// `TaskSupportAssignmentService._require_controller` all resolve the actor's
// V2ProjectMembership rows first.
//
// Admin and Super Admin are the one genuine global authority: they short-
// circuit every backend check, so they short-circuit these too.
function isPlatformAdmin(user) {
  return user?.role === "admin" || user?.role === "super_admin";
}

// Roles the actor holds on this specific project, derived from the project's
// active memberships. Empty for a non-member.
export function actorProjectRoles(project, user) {
  if (!project || !user) return [];
  return (project.memberships || [])
    .filter(membership => membership.user_id === user.id && !membership.ends_at)
    .map(membership => membership.project_role);
}

// Mirrors task_lifecycle.py's `_can_cancel`: Admin/Super Admin, or the
// project's own PM.
function canCancel(user, roles) {
  return isPlatformAdmin(user) || roles.includes("project_manager");
}

// Mirrors TaskBlockerService._require_resolver: the project's Supervisor or
// PM, or an Admin, may resolve a blocker; anyone else would be refused.
function canResolveBlockers(user, roles) {
  return isPlatformAdmin(user) || roles.includes("site_supervisor") || roles.includes("project_manager");
}

// Mirrors TaskSupportAssignmentService._require_controller: the Supervisor
// controls support for work tasks, the PM for approval gates, and a milestone
// has no support concept at all.
function canAssignSupport(detail, user, roles) {
  if (isPlatformAdmin(user)) return true;
  if (detail.task_kind === "approval_gate") return roles.includes("project_manager");
  if (detail.task_kind === "milestone") return false;
  return roles.includes("site_supervisor");
}

// Mirrors task_lifecycle.py's `_require_role_for_transition`: "start"
// (in_progress) and "submit completion" (submitted) belong to the assigned
// Internal Employee once one is actively support-assigned to the task.
// Everything else stays Supervisor/PM/Admin. Shared with the "Log progress"
// form: whoever may drive start/submit is exactly who may log the progress
// evidence those transitions consume.
export function canExecute(detail, user, roles) {
  const hasAssignedEmployee = (detail.support_assignments || []).some(a => a.status === "active");
  const isAssignedActor = user?.role === "internal_employee" && detail.actor_is_assigned_support;
  if (isPlatformAdmin(user)) return true;
  if (hasAssignedEmployee) return isAssignedActor;
  // Approval-gate work has no Supervisor/PM self-execute fallback: the
  // backend refuses to let anyone start it until an Internal Employee is
  // delegated. Offering the button here would always 409.
  if (detail.task_kind === "approval_gate") return false;
  return roles.includes("site_supervisor") || roles.includes("project_manager");
}

export function forwardTargetsFor(detail, user, roles) {
  const targets = FORWARD_TRANSITIONS[detail.lifecycle_status] || [];
  if (!targets.length) return [];
  // Scheduling (`ready`) is Supervisor/PM authority on this project, plus the
  // actively assigned employee (task_lifecycle.py lets them mark it ready so
  // a busy Supervisor/PM doesn't block its start); start/submit follow the
  // executor rule in canExecute.
  const canSchedule = isPlatformAdmin(user)
    || roles.includes("site_supervisor")
    || roles.includes("project_manager")
    || Boolean(detail.actor_is_assigned_support);
  const canExec = canExecute(detail, user, roles);

  return targets.filter(target => (
    EXECUTOR_TARGETS.includes(target) ? canExec : canSchedule
  ));
}

// Mirrors task_lifecycle.py's own "submitted" precondition exactly: an update
// is spent once a verification or approval decision has covered it (the
// backend sets `reviewed_at`, for either outcome). Submission needs at least
// one unreviewed update, plus a file on one of them when evidence is
// required. Applies to work tasks and approval-gate tasks alike; only
// milestones (never submitted by hand) are exempt. Returns null when the task
// can be submitted for review, otherwise which precondition is unmet.
export function submitBlocker(detail) {
  if (detail.task_kind === "milestone") return null;
  const unreviewed = (detail.progress_updates || []).filter(update => update.reviewed_at == null);
  if (!unreviewed.length) return "progress";
  if (detail.evidence_required && !unreviewed.some(update => (update.evidence || []).length > 0)) return "evidence";
  return null;
}

const SUBMIT_BLOCKER_MESSAGE = {
  progress: "Log a new progress update (a note and/or evidence) below before submitting for review.",
  evidence: "This task requires evidence. Attach a photo or PDF to a new progress update below before submitting for review.",
};

// U23: whether starting this task now would be starting it ahead of plan.
// Mirrors task_lifecycle.py's own early-start condition exactly - target
// `in_progress`, no actual start recorded yet, a planned start date exists,
// and today is before it.
function isEarlyStart(task) {
  if (!task?.planned_start_date) return false;
  if (task.actual_start_at) return false;
  return todayIso() < task.planned_start_date;
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// --- Presentation helpers: converting backend vocabulary into copy a user
// can read, and resolving ids to names instead of ever printing one. ---

function humanizeStatus(value) {
  if (!value) return "—";
  const spaced = String(value).replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// Exported so the Dependencies tab's own control view (DependencyControlView)
// uses the exact same human-readable labels rather than a second copy that
// could drift from this one.
export const DEPENDENCY_TYPE_LABEL = {
  finish_to_start: "Finish-to-Start",
  start_to_start: "Start-to-Start",
  finish_to_finish: "Finish-to-Finish",
  start_to_finish: "Start-to-Finish",
};
const DEPENDENCY_REQUIRED_TEXT = {
  finish_to_start: "Previous task must be completed",
  start_to_start: "Previous task must have started",
  finish_to_finish: "Previous task must finish before this one can finish",
  start_to_finish: "Previous task must start before this one can finish",
};

// A date/instant field is rendered through `formatDateShort`, which appends
// "T00:00:00" to whatever string it's handed and expects a date-only value
// like planned_start_date already is. Actuals/`created_at` are full ISO
// instants, so they're trimmed to their calendar day first - passing the
// instant straight through would concatenate a second time offset onto the
// first and print "Invalid Date".
function formatInstantShort(value) {
  return formatDateShort(value?.slice(0, 10));
}

// Resolves a raw user/employee id against the project's own membership list
// to a display name - never falls back to printing the id itself. `key`
// picks which membership column the id is compared against, since some
// fields on the payload (progress_updates.submitted_by, delays.recorded_by)
// are user ids and others (blockers.owner_employee_id,
// support_assignments.employee_id) are employee ids.
function resolveActorName(project, id, key = "user_id") {
  if (!id) return null;
  return (project?.memberships || []).find(member => member[key] === id)?.name || null;
}

// Per the product's ownership rule: the Site Supervisor is the Primary
// Responsible person for every execution task on their project by default -
// not "whoever happens to be support-assigned." A task with no internal
// employee delegated to it still has an owner; a project with no active
// Supervisor membership genuinely doesn't, which is a data problem worth
// flagging distinctly from "nobody's working on this specific task."
function primaryResponsible(project) {
  const supervisor = (project?.memberships || []).find(member => member.project_role === "site_supervisor" && !member.ends_at);
  return supervisor ? { name: supervisor.name } : null;
}
function projectManagerName(project) {
  return (project?.memberships || []).find(member => member.project_role === "project_manager" && !member.ends_at)?.name || null;
}

// Turns the readiness engine's blocking reasons into the structured,
// resolved (never-a-raw-id) cards the Overview tab shows. Dependency reasons
// are resolved against the already-loaded `predecessors`; approval reasons
// are resolved against the project's external approvals (fetched once
// alongside the task detail). Either resolution can legitimately fail (the
// engine and the two lookup lists are populated by different queries), and
// the fallback text is exactly what a user should see instead of an id:
// "External approval pending" / "External approval details unavailable".
function buildBlockingItems(detail, externalApprovals) {
  const reasons = detail.readiness?.reasons || [];
  return reasons.map(reason => {
    if (reason.kind === "dependency") {
      const predecessor = detail.predecessors.find(dep => dep.id === reason.subject_id);
      if (predecessor) {
        return {
          key: `dependency-${reason.subject_id}`, kind: "dependency",
          title: `${predecessor.original_code} ${predecessor.title}`,
          lines: [
            `Dependency: ${DEPENDENCY_TYPE_LABEL[predecessor.dependency_type] || humanizeStatus(predecessor.dependency_type)}`,
            `Required: ${DEPENDENCY_REQUIRED_TEXT[predecessor.dependency_type] || "Previous task must reach the required state"}`,
            `Current Status: ${humanizeStatus(predecessor.lifecycle_status)}`,
          ],
        };
      }
      return { key: `dependency-${reason.subject_id}`, kind: "dependency", title: "Dependent task", lines: ["A predecessor task is holding this one back."] };
    }
    if (reason.kind === "approval") {
      const approval = externalApprovals.find(item => item.id === reason.subject_id || item.project_gate_id === reason.subject_id);
      if (approval) {
        return {
          key: `approval-${reason.subject_id}`, kind: "approval",
          title: approval.gate_name || approval.gate_code || "External approval",
          lines: ["Type: External Approval", `Status: ${humanizeStatus(approval.status)}`, `Owner: ${approval.assigned_to_name || "Unassigned"}`],
        };
      }
      return { key: `approval-${reason.subject_id}`, kind: "approval", title: "External approval pending", lines: ["External approval details unavailable"] };
    }
    return { key: `${reason.kind}-${reason.subject_id}`, kind: reason.kind, title: humanizeStatus(reason.kind), lines: [reason.detail || "Blocked."] };
  });
}

// One unified, chronological history from every source the detail payload
// carries - nothing here is a second copy of business logic, only a merge
// and a sort. Vendor delegation history is NOT included: it lives behind its
// own endpoint (TaskVendorDelegationForm fetches it independently) and
// pulling it in here would mean a second fetch just for this list: it stays
// visible on the Action Forms tab instead.
function buildActivityLog(detail, project) {
  const entries = [];
  for (const event of detail.audit_events || []) {
    entries.push({
      id: `audit-${event.id}`, at: event.occurred_at, actor: event.actor_name || "System",
      action: `Status changed: ${humanizeStatus(event.before_status)} → ${humanizeStatus(event.after_status)}`,
      comment: event.reason,
    });
  }
  for (const update of detail.progress_updates || []) {
    entries.push({
      id: `progress-${update.id}`, at: update.created_at,
      actor: resolveActorName(project, update.submitted_by) || "Team member",
      action: update.evidence?.length ? "Progress update with evidence" : "Progress update",
      comment: update.note,
    });
  }
  for (const verification of detail.verifications || []) {
    entries.push({
      id: `verification-${verification.id}`, at: verification.verified_at,
      actor: verification.verified_by_name || "Supervisor",
      action: verification.decision === "verified" ? "Verified completion" : "Rejected at verification",
      comment: verification.remarks,
    });
  }
  for (const approval of detail.approvals || []) {
    entries.push({
      id: `approval-${approval.id}`, at: approval.decided_at,
      actor: approval.decided_by_name || "Project Manager",
      action: approval.decision === "approved" ? "Approved" : "Rejected at approval",
      comment: approval.remarks,
    });
  }
  for (const blocker of detail.blockers || []) {
    entries.push({
      id: `blocker-${blocker.id}-open`, at: blocker.started_at || blocker.created_at,
      actor: resolveActorName(project, blocker.owner_employee_id, "employee_id") || "Team member",
      action: `Blocker reported: ${blocker.type}`, comment: blocker.description,
    });
    if (blocker.resolved_at) {
      entries.push({
        id: `blocker-${blocker.id}-resolved`, at: blocker.resolved_at,
        actor: resolveActorName(project, blocker.resolved_by) || "Team member",
        action: `Blocker resolved: ${blocker.type}`, comment: null,
      });
    }
  }
  for (const delay of detail.delays || []) {
    entries.push({
      id: `delay-${delay.id}`, at: delay.created_at,
      actor: resolveActorName(project, delay.recorded_by) || "Team member",
      action: `Delay reported: ${delay.impact_days} day${delay.impact_days === 1 ? "" : "s"} (${humanizeStatus(delay.responsibility_type)})`,
      comment: delay.reason,
    });
  }
  for (const assignment of detail.support_assignments || []) {
    const employeeName = resolveActorName(project, assignment.employee_id, "employee_id") || "Team member";
    entries.push({
      id: `support-${assignment.id}-start`, at: assignment.starts_at || assignment.created_at,
      actor: resolveActorName(project, assignment.assigned_by) || "Team member",
      action: `Support assigned: ${employeeName}${assignment.responsibility ? ` (${assignment.responsibility})` : ""}`, comment: null,
    });
    if (assignment.ends_at) {
      entries.push({ id: `support-${assignment.id}-end`, at: assignment.ends_at, actor: null, action: `Support assignment ended: ${employeeName}`, comment: null });
    }
  }
  return entries.filter(entry => entry.at).sort((a, b) => new Date(b.at) - new Date(a.at));
}

function CancelControl({ projectId, task, onChanged }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function cancel() {
    setBusy(true);
    setError("");
    try {
      await taskExecutionApi.transitionStatus(projectId, task.id, { target_status: "cancelled", reason });
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This task could not be cancelled.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="flex flex-wrap items-center gap-2">
    <input
      value={reason}
      onChange={event => setReason(event.target.value)}
      placeholder="Reason for cancellation (required)"
      className="min-h-9 min-w-[220px] flex-1 rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-rose-500"
    />
    <Button size="sm" variant="danger" disabled={!reason.trim()} loading={busy} onClick={cancel}>Cancel task</Button>
    {error && <span className="text-xs font-bold text-rose-700">{error}</span>}
  </div>;
}

// U23: collects the reason the backend requires before an early start,
// rather than letting the user click Start and be refused with a 422 they
// cannot answer.
function EarlyStartModal({ task, onConfirm, onClose }) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    const cleanReason = reason.trim();
    if (!cleanReason) {
      setError("A reason is required to start this task before its planned start date.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await onConfirm(cleanReason);
    } catch (caught) {
      setError(caught?.message || "This task could not be started early.");
      setSubmitting(false);
    }
  }

  return <Modal
    title="Start this task early"
    subtitle={`${task.original_code} - ${task.title}`}
    onClose={() => { if (!submitting) onClose(); }}
    className="sm:max-w-xl"
  >
    <form className="grid gap-4" onSubmit={submit}>
      <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-bold text-amber-800">
        This task is planned to start on {formatDateShort(task.planned_start_date)}. Starting it now is ahead of the baseline, so it needs a reason for the record.
      </p>
      <Field label="Reason for starting early (required)">
        <Textarea
          value={reason}
          onChange={event => setReason(event.target.value)}
          required
          placeholder="Explain why this task is starting ahead of its planned date"
        />
      </Field>
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
      <div className="grid gap-2 sm:grid-cols-2">
        <Button type="button" variant="secondary" disabled={submitting} onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={!reason.trim()} loading={submitting}>Confirm early start</Button>
      </div>
    </form>
  </Modal>;
}

function Card({ title, icon: Icon, children, className = "" }) {
  return <section className={`rounded-2xl border border-slate-200 bg-white p-4 ${className}`}>
    {title && <h4 className="mb-3 flex items-center gap-1.5 text-xs font-black uppercase tracking-wide text-slate-500">{Icon && <Icon size={14}/>} {title}</h4>}
    {children}
  </section>;
}

// --- Overview: read-only / summary. ---

function OverviewPane({ task, detail, project, candidates, externalApprovals, onDownloadReference, projectId, canManageReferences, onReferencesChanged }) {
  const activeAssignments = (detail.support_assignments || []).filter(a => a.status === "active");
  const nameFor = employeeId => candidates?.find(c => c.employee_id === employeeId)?.name || "Assigned";
  const supervisor = primaryResponsible(project);
  const pmName = projectManagerName(project);
  const isTerminal = detail.lifecycle_status === "completed" || detail.lifecycle_status === "cancelled";
  const blockingItems = detail.readiness?.state === "blocked" ? buildBlockingItems(detail, externalApprovals) : [];

  const taskDetailItems = [
    { label: "Planned start", value: formatDateShort(detail.planned_start_date) },
    { label: "Planned finish", value: formatDateShort(detail.planned_end_date) },
    { label: "Actual start", value: formatInstantShort(detail.actual_start_at) },
    { label: "Actual finish", value: formatInstantShort(detail.actual_finish_at) },
    { label: "Reported on", value: formatInstantShort(detail.created_at) },
  ];

  return <div className="grid gap-4">
    <TaskLifecycleStepper status={detail.lifecycle_status} approvalRequired={detail.approval?.approval_required}/>

    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Task Details"><DetailGrid items={taskDetailItems} className="!border-0 !bg-transparent !p-0 sm:!grid-cols-1"/></Card>

      <Card title="Instructions">
        <p className="text-sm leading-6 text-slate-600">{detail.description || "No specific instructions added."}</p>
        {detail.added_after_start && <p className="mt-3 flex items-start gap-1.5 rounded-xl border border-violet-200 bg-violet-50 px-3 py-2 text-xs font-bold text-violet-800">
          <CalendarClock size={13} className="mt-0.5 shrink-0"/> Added after the project started{detail.added_by_name ? ` by ${detail.added_by_name}` : ""}{detail.added_reason ? `: ${detail.added_reason}` : ""}
        </p>}
        {detail.early_start_reason && <p className="mt-3 flex items-start gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800">
          <CalendarClock size={13} className="mt-0.5 shrink-0"/> Started early: {detail.early_start_reason}
        </p>}
        <ReferenceMaterial className="mt-4 border-t border-slate-100 pt-4" instructions={detail.evidence_instructions} files={detail.reference_files} onDownload={onDownloadReference}
          onRemove={canManageReferences ? async file => {
            if (!window.confirm(`Remove ${file.filename} from this task?`)) return;
            try {
              await projectsApi.removeTaskReference(projectId, file.id);
              await onReferencesChanged();
            } catch (caught) {
              window.alert(caught?.message || "This file could not be removed.");
            }
          } : undefined}/>
        {canManageReferences && <div className="mt-3"><TaskReferenceManager projectId={projectId} taskId={task.id} onChanged={onReferencesChanged}/></div>}
      </Card>

      <Card title="Ownership">
        <div className="grid gap-3">
          <div className="flex items-start gap-2">
            <User size={15} className="mt-0.5 shrink-0 text-slate-400"/>
            <div>
              <span className="block text-[10px] font-black uppercase tracking-wide text-slate-400">Primary Responsible</span>
              {supervisor ? <>
                <strong className="block text-sm text-slate-900">{supervisor.name}</strong>
                <span className="text-xs text-slate-500">Role: Site Supervisor</span>
              </> : <span className="mt-0.5 flex items-center gap-1 text-sm font-bold text-amber-700"><AlertTriangle size={13}/> Supervisor not assigned</span>}
            </div>
          </div>
          <div className="flex items-start gap-2">
            <Users size={15} className="mt-0.5 shrink-0 text-slate-400"/>
            <div>
              <span className="block text-[10px] font-black uppercase tracking-wide text-slate-400">Support / Delegated To</span>
              {activeAssignments.length ? (
                <span className="text-sm text-slate-800">{activeAssignments.map(a => nameFor(a.employee_id)).join(", ")}</span>
              ) : <span className="text-sm text-slate-500">Not delegated</span>}
            </div>
          </div>
          {pmName && <div className="flex items-start gap-2">
            <ShieldCheck size={15} className="mt-0.5 shrink-0 text-slate-400"/>
            <div>
              <span className="block text-[10px] font-black uppercase tracking-wide text-slate-400">PM / Approval Owner</span>
              <span className="text-sm text-slate-800">{pmName}</span>
            </div>
          </div>}
        </div>
      </Card>

      <Card title="Status & Readiness">
        <DetailGrid
          className="!border-0 !bg-transparent !p-0 sm:!grid-cols-1"
          items={[
            { label: "Lifecycle status", value: humanizeStatus(detail.lifecycle_status) },
            { label: "Readiness", value: humanizeStatus(detail.readiness?.state) },
            { label: "Delay status", value: task.variance?.status === "late" ? `${task.variance.days}d late` : "On schedule" },
            { label: "Blocker status", value: `${detail.blockers.filter(b => !b.resolved_at).length} open` },
          ]}
        />
        {blockingItems.length > 0 && <div className="mt-3 border-t border-slate-100 pt-3">
          <p className="text-xs font-black text-rose-700">Task is blocked by {blockingItems.length} item{blockingItems.length === 1 ? "" : "s"}</p>
          <ol className="mt-2 grid gap-2">
            {blockingItems.map((item, index) => <li key={item.key} className="rounded-xl border border-rose-100 bg-rose-50/60 p-3 text-sm">
              <div className="flex items-center gap-1.5 font-bold text-slate-900">
                {item.kind === "dependency" ? <GitBranch size={13} className="shrink-0 text-rose-600"/> : <ShieldAlert size={13} className="shrink-0 text-rose-600"/>}
                {index + 1}. {item.title}
              </div>
              <div className="mt-1 grid gap-0.5 pl-[19px] text-xs text-slate-600">{item.lines.map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</div>
            </li>)}
          </ol>
        </div>}
        <div className="mt-3 border-t border-slate-100 pt-3"><TaskApprovalSummary task={detail}/></div>
      </Card>
    </div>

    {isTerminal && <TaskTerminalSummary task={detail} onDownloadEvidence={() => {}}/>}
  </div>;
}

// --- Action Forms: everything editable. ---

function ActionFormsPane({ projectId, project, task, detail, user, roles, candidates, autoOpenBlockerDelay, forwardTargets, showCancel, blocker, earlyStart, transitioning, onTransition, onStartEarly, earlyStartOpen, setEarlyStartOpen, refreshAll, downloadEvidence, isTerminal }) {
  if (isTerminal) {
    return <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm font-bold text-slate-500">
      No actions available - this task is {detail.lifecycle_status}.
    </div>;
  }

  return <div className="grid gap-4">
    {earlyStartOpen && <EarlyStartModal task={detail} onConfirm={onStartEarly} onClose={() => setEarlyStartOpen(false)}/>}

    <div id="action-status" className="grid gap-4">
      {(forwardTargets.length > 0 || showCancel) && <Card title="Status Action">
        <div className="flex flex-wrap items-center gap-2">
          {forwardTargets.map(target => {
            const isBlockedSubmit = target === "submitted" && blocker !== null;
            const isEarly = target === "in_progress" && earlyStart;
            return <Button
              key={target}
              loading={transitioning === target}
              disabled={isBlockedSubmit}
              title={isBlockedSubmit ? SUBMIT_BLOCKER_MESSAGE[blocker] : undefined}
              onClick={() => (isEarly ? setEarlyStartOpen(true) : onTransition(target))}
            >{isEarly ? "Start work early" : (TRANSITION_LABEL[target] || target)}</Button>;
          })}
        </div>
        {detail.readiness?.state === "blocked" && forwardTargets.includes("ready") && <p className="mt-2 flex items-center gap-1.5 text-xs font-bold text-rose-700">
          <AlertTriangle size={13}/> Cannot mark ready yet. Resolve dependencies/approvals first.
        </p>}
        {forwardTargets.includes("in_progress") && earlyStart && <p className="mt-2 flex items-center gap-1.5 text-xs font-bold text-amber-700">
          <CalendarClock size={13}/> Planned to start {formatDateShort(detail.planned_start_date)} - starting now needs a reason.
        </p>}
        {forwardTargets.includes("submitted") && blocker && <p className="mt-2 text-xs font-bold text-blue-800">{SUBMIT_BLOCKER_MESSAGE[blocker]}</p>}
        {showCancel && <div className="mt-3 border-t border-slate-100 pt-3"><CancelControl projectId={projectId} task={detail} onChanged={refreshAll}/></div>}
      </Card>}

      <TaskDecisionModal projectId={projectId} project={project} task={detail} user={user} onDecided={refreshAll}/>
    </div>

    <div id="action-progress" className="grid gap-4">
      {detail.lifecycle_status === "in_progress" && canExecute(detail, user, roles) && <TaskProgressForm projectId={projectId} task={detail} onSubmitted={refreshAll}/>}

      {detail.progress_updates.length > 0 && <Card title="Progress & Evidence History">
        <div className="grid gap-2">{detail.progress_updates.map(update => <article key={update.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-bold text-slate-800">{update.note || "Evidence submitted."}</span><time className="text-xs text-slate-400">{new Date(update.created_at).toLocaleString("en-GB")}</time></div>
          {update.evidence.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{update.evidence.map(file => <button key={file.id} type="button" onClick={() => downloadEvidence(file.file_id)} className="rounded-md bg-blue-100 px-2 py-1 text-xs font-bold text-blue-700 hover:bg-blue-200">{file.original_filename}</button>)}</div>}
        </article>)}</div>
      </Card>}
    </div>

    {/* U5: blockers/delays are independent of lifecycle_status, so this
        panel is always visible while the task is still in flight, not
        gated by task state or role - any active project member may log
        one. */}
    <div id="action-blockers-delays"><TaskBlockerDelayPanel projectId={projectId} task={detail} onChanged={refreshAll} autoOpen={autoOpenBlockerDelay} canResolve={canResolveBlockers(user, roles)}/></div>

    <Card title="Support Assignment" icon={Users}>
      <TaskSupportAssignmentPanel projectId={projectId} task={detail} candidates={candidates} canAssign={canAssignSupport(detail, user, roles)} onChanged={refreshAll}/>
    </Card>

    <div className="[&>section]:rounded-2xl [&>section]:border [&>section]:border-slate-200 [&>section]:bg-white [&>section]:p-4">
      <TaskVendorDelegationForm projectId={projectId} task={detail} user={user} onChanged={refreshAll}/>
    </div>
  </div>;
}

// --- Activity Log: chronological history. ---

function ActivityLogPane({ detail, project }) {
  const entries = buildActivityLog(detail, project);
  if (!entries.length) return <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6 text-center text-sm font-bold text-slate-500">No activity recorded yet.</div>;

  return <ol className="grid gap-3">
    {entries.map(entry => <li key={entry.id} className="flex gap-3">
      <div className="mt-1 grid size-7 shrink-0 place-items-center rounded-full bg-slate-100 text-slate-400"><History size={13}/></div>
      <div className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-bold text-slate-900">{entry.action}</span>
          <time className="text-xs font-bold text-slate-400">{new Date(entry.at).toLocaleString("en-GB")}</time>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
          {entry.actor && <span className="font-bold text-slate-600">{entry.actor}</span>}
          {entry.comment && <span>- {entry.comment}</span>}
        </div>
      </div>
    </li>)}
  </ol>;
}

// `autoOpenBlockerDelay` ("blocker" | "delay" | undefined): lets a caller
// (TaskDetailDrawer's "Report Delay - Blocker" quick action) land the user
// directly on the right form inside TaskBlockerDelayPanel instead of just
// scrolling to a closed panel.
//
// `onDetailLoaded`/`onFooterState` (optional): handed the full detail
// payload and the drawer's sticky-footer descriptor every time either
// changes, so the caller (TaskDetailDrawer) can render its own footer chrome
// around the SAME transition handler this component already owns, without a
// second copy of the transition logic.
export function TaskDetailContent({ projectId, project, task, user, roles, candidates, onChanged, autoOpenBlockerDelay, onDetailLoaded, onFooterState, activeTab = "overview" }) {
  const [detail, setDetail] = useState(null);
  const [externalApprovals, setExternalApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [transitioning, setTransitioning] = useState("");
  const [earlyStartOpen, setEarlyStartOpen] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [data, approvals] = await Promise.all([
        taskExecutionApi.detail(projectId, task.id),
        taskExecutionApi.listExternalApprovals(projectId).catch(() => []),
      ]);
      setDetail(data);
      setExternalApprovals(approvals);
      onDetailLoaded?.(data);
    } catch (caught) {
      setError(caught?.message || "This task's detail could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId, task.id]);

  async function refreshAll() {
    await load();
    await onChanged();
  }

  async function transition(targetStatus) {
    setTransitioning(targetStatus);
    setError("");
    try {
      await taskExecutionApi.transitionStatus(projectId, task.id, { target_status: targetStatus });
      await refreshAll();
    } catch (caught) {
      setError(caught?.message || "This transition could not be completed.");
    } finally {
      setTransitioning("");
    }
  }

  async function startEarly(reason) {
    setTransitioning("in_progress");
    setError("");
    try {
      await taskExecutionApi.transitionStatus(projectId, task.id, { target_status: "in_progress", reason });
      setEarlyStartOpen(false);
      await refreshAll();
    } finally {
      setTransitioning("");
    }
  }

  async function downloadEvidence(fileId) {
    try {
      const { blob, filename } = await taskExecutionApi.downloadEvidence(projectId, task.id, fileId);
      triggerDownload(blob, filename);
    } catch (caught) {
      setError(caught?.message || "This evidence file could not be downloaded.");
    }
  }

  // Lifts the sticky-footer descriptor up to the drawer whenever the facts
  // it's built from change - same shape every time, computed here so the
  // footer's button calls the exact `transition`/`startEarly` handlers above
  // rather than a second implementation of "what should this button do."
  useEffect(() => {
    if (!onFooterState) return;
    if (!detail) { onFooterState(null); return; }
    const isTerminal = detail.lifecycle_status === "completed" || detail.lifecycle_status === "cancelled";
    if (isTerminal) {
      onFooterState({ helpText: `Task is ${detail.lifecycle_status}.`, tone: "gray", primary: null, secondary: null });
      return;
    }
    const targets = forwardTargetsFor(detail, user, roles);
    const blockerReason = submitBlocker(detail);
    const early = isEarlyStart(detail);
    if (detail.readiness?.state === "blocked" && targets.includes("ready")) {
      onFooterState({ helpText: "Cannot mark ready yet. Resolve dependencies/approvals first.", tone: "red", primary: { label: "Mark Ready", disabled: true }, secondary: null });
      return;
    }
    if (targets.includes("in_progress")) {
      onFooterState({
        helpText: "Task is ready to start.", tone: "blue",
        primary: { label: early ? "Start work early" : "Start Task", onClick: () => (early ? setEarlyStartOpen(true) : transition("in_progress")), loading: transitioning === "in_progress" },
        secondary: null,
      });
      return;
    }
    if (targets.includes("submitted")) {
      onFooterState({
        helpText: blockerReason ? SUBMIT_BLOCKER_MESSAGE[blockerReason] : "Work is currently in progress.", tone: blockerReason ? "amber" : "blue",
        primary: { label: "Submit For Review", onClick: () => transition("submitted"), loading: transitioning === "submitted", disabled: Boolean(blockerReason) },
        secondary: null,
      });
      return;
    }
    if (targets.includes("ready")) {
      onFooterState({ helpText: "This task can be marked ready.", tone: "blue", primary: { label: "Mark Ready", onClick: () => transition("ready"), loading: transitioning === "ready" }, secondary: null });
      return;
    }
    if (["submitted", "verified", "approval_pending"].includes(detail.lifecycle_status)) {
      onFooterState({ helpText: "Awaiting review.", tone: "amber", primary: null, secondary: null });
      return;
    }
    onFooterState({ helpText: "No action available for your role right now.", tone: "gray", primary: null, secondary: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail, user, roles, transitioning]);

  if (loading) return <div className="grid min-h-32 place-items-center"><LoadingSpinner label="Loading task detail..."/></div>;
  if (!detail) return <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">{error || "Task detail unavailable."}</div>;

  const forwardTargets = forwardTargetsFor(detail, user, roles);
  const showCancel = canCancel(user, roles) && CANCELLABLE_STATUSES.includes(detail.lifecycle_status);
  const blocker = submitBlocker(detail);
  const earlyStart = isEarlyStart(detail);
  // Terminal = no further outgoing transitions - none of the execution
  // controls below apply anymore. `rejected` is deliberately excluded: the
  // backend always bounces it straight back to `in_progress` in the same
  // call, so it never persists as a state a user actually sees sitting still.
  const isTerminal = detail.lifecycle_status === "completed" || detail.lifecycle_status === "cancelled";

  return <div className="grid gap-4">
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>}

    {activeTab === "overview" && <OverviewPane task={task} detail={detail} project={project} candidates={candidates} externalApprovals={externalApprovals} onDownloadReference={file => taskExecutionApi.downloadTaskReference(projectId, task.id, file.id)}
      projectId={projectId} canManageReferences={canAddTasks(user) && !["completed", "cancelled"].includes(detail.lifecycle_status)} onReferencesChanged={load}/>}

    {activeTab === "actions" && <ActionFormsPane
      projectId={projectId} project={project} task={task} detail={detail} user={user} roles={roles} candidates={candidates}
      autoOpenBlockerDelay={autoOpenBlockerDelay} forwardTargets={forwardTargets} showCancel={showCancel} blocker={blocker}
      earlyStart={earlyStart} transitioning={transitioning} onTransition={transition} onStartEarly={startEarly}
      earlyStartOpen={earlyStartOpen} setEarlyStartOpen={setEarlyStartOpen} refreshAll={refreshAll} downloadEvidence={downloadEvidence}
      isTerminal={isTerminal}
    />}

    {activeTab === "activity" && <ActivityLogPane detail={detail} project={project}/>}
  </div>;
}
