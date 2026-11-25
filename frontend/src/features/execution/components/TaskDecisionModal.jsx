import { Hourglass, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Modal, Textarea } from "../../../components/ui";

const AWAITING_MESSAGE = {
  verify: "Awaiting Supervisor verification",
  approve: "Awaiting PM approval",
};

// task_kind is nullable - a task whose template row never had a kind
// assigned during authoring still needs a real completion path, so it's
// treated as ordinary `work` here, matching TaskVerificationService.verify
// and build_approval_metadata's `is_work_task_kind` normalization. Only an
// explicit "approval_gate" (or "milestone", which never reaches this modal
// since milestones auto-complete) opts a task out of the work path.
function isWorkTaskKind(taskKind) {
  return taskKind !== "milestone" && taskKind !== "approval_gate";
}

// U4: Supervisor verification / PM approval decisions (BR-008). Mirrors
// TaskApplicabilityDecisionModal.jsx's shape - buttons plus a conditional
// modal, a required reason only on reject, and an onDecided?.() callback
// that refreshes the board row rather than the whole page.
function resolveAction(task) {
  if (isWorkTaskKind(task.task_kind) && task.lifecycle_status === "submitted") return "verify";
  if (task.task_kind === "approval_gate" && task.lifecycle_status === "submitted") return "approve";
  if (isWorkTaskKind(task.task_kind) && task.task_class === "class_a" && task.lifecycle_status === "verified") return "approve";
  return null;
}

// Mirrors the backend's actual authority (task_verification.py
// `_require_verifier`, task_approval.py `_require_approver`): the
// Supervisor may verify (or stand in as an audited PM fallback), but only
// the PM (or Admin/Super Admin) may record a PM approval decision - a
// Supervisor must never see an Approve action it cannot actually use.
function actorCanAct(action, role) {
  if (!role) return false;
  if (role === "admin" || role === "super_admin") return true;
  if (action === "verify") return role === "supervisor" || role === "project_manager";
  if (action === "approve") return role === "project_manager";
  return false;
}

// Whether an active project member holds `projectRole` right now, mirroring
// the backend's own check (task_verification.py `_has_active_supervisor`,
// task_approval.py `_has_active_pm`): an active membership has no `ends_at`.
function hasActiveRole(project, projectRole) {
  return (project?.memberships || []).some(m => m.project_role === projectRole && !m.ends_at);
}

// The backend's verification takes the task's latest progress update as the
// submission (task_verification.py `_latest_submission`) and refuses to let
// whoever submitted it also verify it, unless they are Admin/Super Admin.
function latestSubmitter(task) {
  const updates = [...(task.progress_updates || [])].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  return updates[0]?.submitted_by || null;
}

function memberName(project, projectRole) {
  return (project?.memberships || []).find(m => m.project_role === projectRole && !m.ends_at)?.name || null;
}

// Everything the drawer needs to know about the review step, in one place:
// which decision is due, whether this user may record it, and if not, who is
// expected to. Used by the decision panel below and the drawer footer, so the
// two can never disagree.
export function reviewStateFor(task, user, project) {
  const action = task ? resolveAction(task) : null;
  if (!action) return { action: null, canAct: false, selfSubmitted: false, waitingOn: null };
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const selfSubmitted = action === "verify" && !isAdmin && Boolean(user?.id) && latestSubmitter(task) === user.id;
  const canAct = actorCanAct(action, user?.role) && !selfSubmitted;
  let waitingOn;
  if (action === "approve") waitingOn = memberName(project, "project_manager") || "the PM";
  else if (selfSubmitted) {
    // Anyone else who qualifies may verify; name the other accountable member.
    const other = user.role === "project_manager" ? memberName(project, "site_supervisor") : memberName(project, "project_manager");
    waitingOn = other ? `${other} or an admin` : "another Supervisor, the PM or an admin";
  } else waitingOn = memberName(project, "site_supervisor") || "the Supervisor";
  return { action, canAct, selfSubmitted, waitingOn };
}

const OVERRIDE_ROLE_FOR_ACTION = { verify: "site_supervisor", approve: "project_manager" };
const OVERRIDE_ROLE_LABEL = { verify: "Supervisor", approve: "PM" };

export function TaskDecisionModal({ projectId, project, task, user, onDecided }) {
  const action = resolveAction(task);
  const [decision, setDecision] = useState(null); // "positive" | "rejected"
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // Admin/Super Admin get a speed bump - not a block - when acting while
  // the role that normally owns this decision (Supervisor for verify, PM
  // for approve) is actually active on the project, so overriding them is
  // a deliberate choice rather than a habit. `pendingDecision` holds which
  // decision ("positive"/"rejected") is waiting on that confirmation.
  // Mirrors the backend's decision_mode tagging (admin_override vs
  // admin_fallback), which persists the same distinction to the audit
  // trail regardless of what happens here.
  const [pendingDecision, setPendingDecision] = useState(null);

  if (!action) return null;
  const review = reviewStateFor(task, user, project);

  if (review.selfSubmitted) {
    return <div id="action-review" className="flex items-start gap-2 rounded-2xl border border-line bg-white px-4 py-3 text-sm text-slate-600">
      <Hourglass size={15} className="mt-0.5 shrink-0 text-slate-400"/>
      <span>You submitted this work, so someone else has to verify it: {review.waitingOn}.</span>
    </div>;
  }

  if (!actorCanAct(action, user?.role)) {
    return <div id="action-review" className="flex items-center gap-2 rounded-2xl border border-line bg-white px-4 py-3 text-sm text-slate-600">
      <Hourglass size={15} className="shrink-0 text-slate-400"/> {AWAITING_MESSAGE[action]}
    </div>;
  }

  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const overrideRoleLabel = OVERRIDE_ROLE_LABEL[action];
  const needsOverrideConfirm = isAdmin && hasActiveRole(project, OVERRIDE_ROLE_FOR_ACTION[action]);

  const positiveDecision = action === "verify" ? "verified" : "approved";
  const positiveLabel = action === "verify" ? "Verify completion" : "Approve";
  const modalTitle = action === "verify" ? "Verify task completion" : "Approve task";
  const confirmLabel = action === "verify" ? "Confirm verification" : "Confirm approval";

  function open(next) {
    setError("");
    if (needsOverrideConfirm) {
      setPendingDecision(next);
      return;
    }
    setRemarks("");
    setDecision(next);
  }

  function confirmOverride() {
    setPendingDecision(null);
    setRemarks("");
    setDecision(pendingDecision);
  }

  async function submit(event) {
    event.preventDefault();
    const cleanRemarks = remarks.trim();
    if (decision === "rejected" && !cleanRemarks) {
      setError("A correction reason is required to reject this task.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const call = action === "verify" ? taskExecutionApi.verify : taskExecutionApi.approve;
      await call(projectId, task.id, {
        decision: decision === "rejected" ? "rejected" : positiveDecision,
        remarks: cleanRemarks || null,
      });
      setDecision(null);
      await onDecided();
    } catch (caught) {
      setError(caught?.message || "This decision could not be recorded.");
    } finally {
      setSubmitting(false);
    }
  }

  return <>
    <section id="action-review" className="rounded-2xl border border-slate-950 bg-white p-4">
      <h4 className="text-[15px] font-medium text-slate-950">{action === "verify" ? "Supervisor verification" : "PM approval"}</h4>
      <p className="mt-0.5 text-sm text-slate-500">{action === "verify" ? "Check the progress and evidence below, then verify or send it back." : "Verified work waiting for your approval."}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => open("positive")}>{positiveLabel}</Button>
        <Button size="sm" variant="danger" onClick={() => open("rejected")}>Reject</Button>
      </div>
    </section>

    {pendingDecision && <Modal title={`${overrideRoleLabel} is currently assigned`} subtitle={`${task.original_code} - ${task.title}`} onClose={() => setPendingDecision(null)} className="sm:max-w-xl">
      <div className="grid gap-5">
        <div className="flex items-start gap-3 rounded-2xl border border-orange-200 bg-orange-50 p-4">
          <ShieldAlert size={20} className="mt-0.5 shrink-0 text-orange-700"/>
          <p className="text-sm text-orange-900">This project has an active {overrideRoleLabel}. Continue as Admin instead of leaving this to them?</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Button variant="secondary" onClick={() => setPendingDecision(null)}>Cancel</Button>
          <Button onClick={confirmOverride}>Continue as Admin</Button>
        </div>
      </div>
    </Modal>}

    {decision && <Modal title={decision === "rejected" ? "Reject and reopen task" : modalTitle} subtitle={`${task.original_code} - ${task.title}`} onClose={() => { if (!submitting) setDecision(null); }} className="sm:max-w-xl">
      <form className="grid gap-4" onSubmit={submit}>
        <Field label={decision === "rejected" ? "Correction reason (required)" : "Remarks (optional)"}>
          <Textarea value={remarks} onChange={event => setRemarks(event.target.value)} required={decision === "rejected"} placeholder={decision === "rejected" ? "Explain what needs correcting before resubmission" : "Optional remarks"}/>
        </Field>
        {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="button" variant="secondary" disabled={submitting} onClick={() => setDecision(null)}>Cancel</Button>
          <Button type="submit" variant={decision === "rejected" ? "danger" : "primary"} loading={submitting}>{decision === "rejected" ? "Confirm rejection" : confirmLabel}</Button>
        </div>
      </form>
    </Modal>}
  </>;
}
