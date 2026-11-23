import { useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { Button, Pill, Select, Textarea } from "../../../components/ui";

const RESPONSE_OPTIONS = [
  ["accepted", "Accepted"],
  ["declined", "Declined"],
  ["clarification_requested", "Clarification requested"],
];
const RESPONSE_TONE = { accepted: "green", declined: "red", clarification_requested: "orange" };
// Mirrors VendorAcknowledgementService.RESOLVED_ASSIGNMENT_STATUSES - once
// resolved, a further acknowledgement attempt is a 409 on the backend, so
// this form hides rather than surfacing a doomed submit.
const RESOLVED_STATUSES = new Set(["acknowledged", "declined"]);

// U3: PM records a vendor's response on its behalf (R4 - there is no
// vendor-identity auth here). append-only history; 'clarification_requested'
// never resolves the assignment, so the form stays available after one.
export function VendorAcknowledgementForm({ projectId, task, assignment, canManage = true, onChanged }) {
  const [response, setResponse] = useState("accepted");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await vendorAssignmentApi.acknowledge(projectId, task.id, assignment.id, { response, note: note.trim() || null });
      setNote("");
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This acknowledgement could not be recorded.");
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="mt-3 border-t border-slate-100 pt-3">
    <h5 className="text-xs font-medium text-slate-500">Acknowledgement</h5>
    {assignment.acknowledgements.length > 0 && <div className="mt-2 grid gap-1">{assignment.acknowledgements.map(ack => <div key={ack.id} className="flex flex-wrap items-center gap-2 text-xs"><Pill tone={RESPONSE_TONE[ack.response] || "gray"}>{ack.response.replaceAll("_", " ")}</Pill><span className="text-slate-500">{new Date(ack.created_at).toLocaleString("en-GB")}</span>{ack.note && <span className="text-slate-500">- {ack.note}</span>}</div>)}</div>}
    {!canManage ? null : assignment.ends_at ? <p className="mt-2 text-xs text-slate-500">This assignment was unassigned; no further acknowledgement can be recorded.</p> : RESOLVED_STATUSES.has(assignment.status) ? <p className="mt-2 text-xs text-slate-500">This assignment is resolved; no further acknowledgement can be recorded.</p> : <form className="mt-2 grid gap-2 sm:grid-cols-[160px_1fr_auto]" onSubmit={submit}>
      <Select value={response} onChange={event => setResponse(event.target.value)}>{RESPONSE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select>
      <Textarea className="min-h-9" value={note} onChange={event => setNote(event.target.value)} placeholder="Note (optional)"/>
      <Button type="submit" size="sm" loading={submitting}>Record</Button>
      {error && <p className="text-xs font-bold text-rose-700 sm:col-span-3">{error}</p>}
    </form>}
  </div>;
}
