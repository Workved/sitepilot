import { Check, Clock3, History, LockKeyhole, X } from "lucide-react";
import { useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, Field, LoadingSpinner, Modal, Pill, Textarea } from "../../../components/ui";

function eventState(event) {
  return event.decision_state === "excluded" ? "Excluded" : "Included";
}

function formatEventTime(value) {
  if (!value) return "Time unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
}

export function TaskApplicabilityControls({ projectId, task, onDecided, canDecide = true }) {
  const [decision, setDecision] = useState(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyEvents, setHistoryEvents] = useState([]);

  if (task.applicability !== "conditional") {
    return <div className="flex lg:justify-end"><Pill tone="gray"><LockKeyhole size={12}/> Mandatory - Locked</Pill></div>;
  }

  const isIncluded = task.included && task.decision_state !== "excluded";

  function openDecision(nextDecision) {
    setReason("");
    setDecisionError("");
    setDecision(nextDecision);
  }

  async function submitDecision(event) {
    event.preventDefault();
    const normalizedReason = reason.trim();
    if (decision === "excluded" && !normalizedReason) {
      setDecisionError("Explain why this conditional task is being excluded.");
      return;
    }
    setSubmitting(true);
    setDecisionError("");
    try {
      await projectsApi.decideTaskApplicability(projectId, task.id, { decision, reason: normalizedReason || null });
      setDecision(null);
      setReason("");
      onDecided?.();
    } catch (error) {
      setDecisionError(error?.message || "The applicability decision could not be saved.");
    } finally {
      setSubmitting(false);
    }
  }

  async function openHistory() {
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const events = await projectsApi.taskApplicabilityHistory(projectId, task.id);
      setHistoryEvents(events);
    } catch (error) {
      setHistoryError(error?.message || "Decision history could not be loaded.");
    } finally {
      setHistoryLoading(false);
    }
  }

  return <>
    {/* Scope decisions are Admin's. Everyone else who can reach this screen
        keeps History, so they can see what was decided and why. */}
    <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap lg:justify-end" aria-label={`Applicability controls for ${task.code}`}>
      {canDecide && <>
        <Button size="sm" variant="secondary" disabled={isIncluded} onClick={() => openDecision("included")}><Check size={14}/> Include</Button>
        <Button size="sm" variant="danger" disabled={!isIncluded} onClick={() => openDecision("excluded")}><X size={14}/> Exclude</Button>
      </>}
      <Button size="sm" variant="ghost" className={canDecide ? "col-span-2" : ""} onClick={openHistory}><History size={14}/> History</Button>
    </div>

    {decision && <Modal title={decision === "excluded" ? "Exclude conditional task" : "Re-include conditional task"} subtitle={`${task.code} - ${task.title}`} onClose={() => { if (!submitting) setDecision(null); }} className="sm:max-w-xl">
      <form className="grid gap-5" onSubmit={submitDecision}>
        <div className={`rounded-2xl border p-4 ${decision === "excluded" ? "border-rose-200 bg-rose-50" : "border-emerald-200 bg-emerald-50"}`}>
          <p className={`text-sm ${decision === "excluded" ? "text-rose-950" : "text-emerald-950"}`}>{decision === "excluded" ? "This task will leave the active project scope." : "This task will return to the active project scope."}</p>
          <p className={`mt-1 text-xs leading-5 ${decision === "excluded" ? "text-rose-700" : "text-emerald-700"}`}>The decision is project-specific, auditable, and does not change the source template.</p>
        </div>
        <Field label={decision === "excluded" ? "Reason (required)" : "Reason (optional)"} htmlFor="task-decision-reason">
          <Textarea id="task-decision-reason" value={reason} onChange={event => setReason(event.target.value)} placeholder={decision === "excluded" ? "State the site or scope reason for exclusion" : "Why is this task being restored?"} maxLength={2000} required={decision === "excluded"}/>
        </Field>
        {decisionError && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{decisionError}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button variant="secondary" disabled={submitting} onClick={() => setDecision(null)}>Cancel</Button>
          <Button type="submit" variant={decision === "excluded" ? "danger" : "primary"} loading={submitting}>{decision === "excluded" ? "Confirm exclusion" : "Confirm inclusion"}</Button>
        </div>
      </form>
    </Modal>}

    {historyOpen && <Modal title="Decision history" subtitle={`${task.code} - ${task.title}`} onClose={() => setHistoryOpen(false)} className="sm:max-w-xl">
      {historyLoading ? <div className="grid min-h-48 place-items-center"><LoadingSpinner label="Loading decision history..."/></div>
        : historyError ? <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">{historyError}</div>
        : historyEvents.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center"><History className="mx-auto text-slate-400" size={22}/><p className="mt-3 font-medium text-slate-900">No decisions recorded</p><p className="mt-1 text-sm text-slate-500">This conditional task has not been included or excluded manually.</p></div>
        : <ol className="grid gap-3">{historyEvents.map(event => <li key={event.id} className="rounded-2xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-2"><Pill tone={event.decision_state === "excluded" ? "red" : "green"}>{eventState(event)}</Pill><span className="inline-flex items-center gap-1 text-xs font-bold text-slate-500"><Clock3 size={13}/>{formatEventTime(event.decided_at)}</span></div><p className="mt-3 text-sm leading-6 text-slate-700">{event.reason || "No reason recorded."}</p><p className="mt-2 text-xs font-bold text-slate-500">By {event.actor_name || "System"}</p></li>)}</ol>}
    </Modal>}
  </>;
}
