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

  if (!actorCanAct(action, user?.role)) {
    return <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-bold text-slate-500">
      <Hourglass size={15}/> {AWAITING_MESSAGE[action]}
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
    <section className="rounded-xl border border-violet-200 bg-violet-50 p-4">
      <h4 className="text-xs font-medium text-violet-800">{action === "verify" ? "Supervisor verification" : "PM approval"}</h4>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => open("positive")}>{positiveLabel}</Button>
        <Button size="sm" variant="danger" onClick={() => open("rejected")}>Reject</Button>
      </div>
    </section>

    {pendingDecision && <Modal title={`${overrideRoleLabel} is currently assigned`} subtitle={`${task.original_code} - ${task.title}`} onClose={() => setPendingDecision(null)} className="sm:max-w-xl">
      <div className="grid gap-5">
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <ShieldAlert size={20} className="mt-0.5 shrink-0 text-amber-700"/>
          <p className="text-sm font-bold text-amber-900">This project has an active {overrideRoleLabel}. Continue as Admin instead of leaving this to them?</p>
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
        {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="button" variant="secondary" disabled={submitting} onClick={() => setDecision(null)}>Cancel</Button>
          <Button type="submit" variant={decision === "rejected" ? "danger" : "primary"} loading={submitting}>{decision === "rejected" ? "Confirm rejection" : confirmLabel}</Button>
        </div>
      </form>
    </Modal>}
  </>;
}
