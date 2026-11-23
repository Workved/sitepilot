import { Check, Clock3, History, X } from "lucide-react";
import { useEffect, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, Field, LoadingSpinner, Modal, Pill, Textarea } from "../../../components/ui";

function label(value) {
  if (value === "not_applicable") return "Not Applicable";
  if (value === "applicable") return "Applicable";
  return "Pending Review";
}

function tone(value) {
  if (value === "not_applicable") return "red";
  if (value === "applicable") return "green";
  return "orange";
}

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
}

export function GateApplicabilityControls({ projectId, gate, onDecided, canDecide }) {
  const [decision, setDecision] = useState(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [history, setHistory] = useState([]);

  function openDecision(next) {
    setDecision(next);
    setReason("");
    setError("");
  }

  async function submit(event) {
    event.preventDefault();
    const normalized = reason.trim();
    if (decision === "not_applicable" && !normalized) {
      setError("A reason is required when marking a gate Not Applicable.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await projectsApi.decideGateApplicability(projectId, gate.id, {
        decision,
        reason: normalized || null,
      });
      setDecision(null);
      setReason("");
      onDecided?.();
    } catch (caught) {
      setError(caught?.message || "The gate applicability decision could not be saved.");
    } finally {
      setSubmitting(false);
    }
  }

  async function openHistory() {
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryError("");
    try {
      setHistory(await projectsApi.gateApplicabilityHistory(projectId, gate.id));
    } catch (caught) {
      setHistoryError(caught?.message || "Gate decision history could not be loaded.");
    } finally {
      setHistoryLoading(false);
    }
  }

  return <>
    <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end">
      {canDecide && <>
        <Button size="sm" variant="secondary" disabled={gate.applicability_state === "applicable"} onClick={() => openDecision("applicable")}><Check size={14}/> Applicable</Button>
        <Button size="sm" variant="danger" disabled={gate.applicability_state === "not_applicable"} onClick={() => openDecision("not_applicable")}><X size={14}/> Not Applicable</Button>
      </>}
      <Button size="sm" variant="ghost" className="col-span-2" onClick={openHistory}><History size={14}/> History</Button>
    </div>

    {decision && <Modal title={decision === "not_applicable" ? "Mark gate Not Applicable" : "Mark gate Applicable"} subtitle={`${gate.code} - ${gate.approval_name}`} onClose={() => { if (!submitting) setDecision(null); }} className="sm:max-w-xl">
      <form className="grid gap-5" onSubmit={submit}>
        <div className={`rounded-2xl border p-4 ${decision === "not_applicable" ? "border-rose-100 bg-rose-50" : "border-emerald-100 bg-emerald-50"}`}>
          <p className={`text-sm ${decision === "not_applicable" ? "text-rose-950" : "text-emerald-950"}`}>{decision === "not_applicable" ? "This gate will be retained but excluded from the project requirement set." : "This gate will remain part of the project requirement set."}</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">The decision is project-specific, append-only in history, and does not change the source template.</p>
        </div>
        <Field label={decision === "not_applicable" ? "Reason (required)" : "Reason (optional)"} htmlFor="gate-decision-reason">
          <Textarea id="gate-decision-reason" value={reason} onChange={event => setReason(event.target.value)} maxLength={2000} placeholder={decision === "not_applicable" ? "Explain why this gate does not apply" : "Optional confirmation note"}/>
        </Field>
        {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button variant="secondary" disabled={submitting} onClick={() => setDecision(null)}>Cancel</Button>
          <Button type="submit" variant={decision === "not_applicable" ? "danger" : "primary"} loading={submitting}>{decision === "not_applicable" ? "Confirm Not Applicable" : "Confirm Applicable"}</Button>
        </div>
      </form>
    </Modal>}

    {historyOpen && <Modal title="Gate applicability history" subtitle={`${gate.code} - ${gate.approval_name}`} onClose={() => setHistoryOpen(false)} className="sm:max-w-xl">
      {historyLoading ? <div className="grid min-h-48 place-items-center"><LoadingSpinner label="Loading gate history..."/></div>
        : historyError ? <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{historyError}</div>
        : history.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center"><History className="mx-auto text-slate-400" size={22}/><p className="mt-3 font-medium text-slate-900">No decisions recorded</p><p className="mt-1 text-sm text-slate-500">This gate is still Pending Review.</p></div>
        : <ol className="grid gap-3">{history.map(item => <li key={item.id} className="rounded-2xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-2"><Pill tone={tone(item.decision)}>{label(item.decision)}</Pill><span className="inline-flex items-center gap-1 text-xs font-bold text-slate-500"><Clock3 size={13}/>{formatTime(item.decided_at)}</span></div><p className="mt-3 text-sm leading-6 text-slate-700">{item.reason}</p><p className="mt-2 text-xs font-bold text-slate-500">By {item.actor_name}</p></li>)}</ol>}
    </Modal>}
  </>;
}
