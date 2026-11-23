import { useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Input, Pill, Select } from "../../../components/ui";

function EndAssignmentControl({ projectId, task, assignment, onChanged }) {
  const [open, setOpen] = useState(false);
  const [reasonCode, setReasonCode] = useState("");
  const [reasonDetail, setReasonDetail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function end(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await taskExecutionApi.endSupportAssignment(projectId, task.id, assignment.id, {
        reason_code: reasonCode.trim(), reason_detail: reasonDetail.trim() || null,
      });
      setOpen(false);
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This support assignment could not be ended.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>End</Button>;

  return <form className="mt-2 grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:grid-cols-[1fr_1fr_auto]" onSubmit={end}>
    <Field label="Reason code"><Input value={reasonCode} onChange={event => setReasonCode(event.target.value)} placeholder="e.g. reassigned" required/></Field>
    <Field label="Detail (optional)"><Input value={reasonDetail} onChange={event => setReasonDetail(event.target.value)}/></Field>
    <div className="flex items-end gap-2">
      <Button type="submit" size="sm" variant="danger" loading={submitting} disabled={!reasonCode.trim()}>Confirm</Button>
      <Button type="button" size="sm" variant="ghost" disabled={submitting} onClick={() => setOpen(false)}>Cancel</Button>
    </div>
    {error && <p className="text-xs font-bold text-rose-700 sm:col-span-3">{error}</p>}
  </form>;
}

// Task-level support assignment (BR-005). The Supervisor controls support for
// work tasks and the PM for approval gates - the backend remains the
// authority, and `canAssign` mirrors its rule so the form is only offered to
// an actor who can actually use it.
//
// `candidates` is passed in rather than fetched here. This panel used to load
// the project once per expanded task purely for that list, and an actor who
// could not read the project got an empty dropdown reading "No internal
// employees on this project" - which describes the project rather than the
// actor's authority, and is the wrong explanation entirely.
export function TaskSupportAssignmentPanel({ projectId, task, candidates = [], canAssign = false, onChanged }) {
  const [employeeId, setEmployeeId] = useState("");
  const [responsibility, setResponsibility] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function assign(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await taskExecutionApi.assignSupport(projectId, task.id, { employee_id: employeeId, responsibility: responsibility.trim() });
      setEmployeeId("");
      setResponsibility("");
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This support assignment could not be created.");
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="grid gap-2">
    <div className="grid gap-2">
      {task.support_assignments.map(assignment => <div key={assignment.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2"><Pill tone={assignment.status === "active" ? "green" : "gray"}>{assignment.status}</Pill><span className="text-slate-700">{assignment.responsibility}</span></div>
          {assignment.status === "active" && <EndAssignmentControl projectId={projectId} task={task} assignment={assignment} onChanged={onChanged}/>}
        </div>
      </div>)}
      {!task.support_assignments.length && <p className="text-sm text-slate-500">No support employees assigned.</p>}
    </div>
    {!canAssign ? (
      <p className="border-t border-slate-100 pt-3 text-sm text-slate-500">
        {task.task_kind === "milestone"
          ? "A milestone is derived from its predecessors, so no one works on it directly."
          : task.task_kind === "approval_gate"
            ? "Only this project's PM can assign follow-up support on an approval gate."
            : "Only this project's Supervisor can assign support on a work task."}
      </p>
    ) : (
    <form className="grid gap-2 border-t border-slate-100 pt-3 sm:grid-cols-[1fr_1fr_auto]" onSubmit={assign}>
      <Field label="Support employee">
        <Select value={employeeId} onChange={event => setEmployeeId(event.target.value)} required>
          <option value="">{candidates.length ? "Select employee" : "No internal employees on this project"}</option>
          {candidates.map(candidate => <option key={candidate.employee_id} value={candidate.employee_id}>{candidate.name}</option>)}
        </Select>
      </Field>
      <Field label="Responsibility"><Input value={responsibility} onChange={event => setResponsibility(event.target.value)} placeholder="What will they help with?" required/></Field>
      <div className="flex items-end"><Button type="submit" size="sm" loading={submitting} disabled={!employeeId || !responsibility.trim()}>Assign</Button></div>
    </form>
    )}
    {error && <p className="text-xs font-bold text-rose-700">{error}</p>}
  </div>;
}
