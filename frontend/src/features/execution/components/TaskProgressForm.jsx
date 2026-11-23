import { useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Input, Textarea } from "../../../components/ui";

// U3: append-only progress note plus optional evidence file, using
// client.js's FormData-aware request handling. Submitting never changes
// lifecycle_status itself - it's evidence for a later `submitted`
// transition (U2) to reference.
export function TaskProgressForm({ projectId, task, onSubmitted }) {
  const [note, setNote] = useState("");
  const [statusClaim, setStatusClaim] = useState("");
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const formData = new FormData();
      if (note.trim()) formData.append("note", note.trim());
      if (statusClaim.trim()) formData.append("status_claim", statusClaim.trim());
      if (file) formData.append("evidence", file);
      await taskExecutionApi.submitProgress(projectId, task.id, formData);
      setNote("");
      setStatusClaim("");
      setFile(null);
      await onSubmitted();
    } catch (caught) {
      setError(caught?.message || "This progress update could not be submitted.");
    } finally {
      setSubmitting(false);
    }
  }

  return <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
    <h4 className="text-xs font-medium text-emerald-800">Log progress</h4>
    <form className="mt-3 grid gap-3" onSubmit={submit}>
      <Field label="Note"><Textarea className="min-h-20" value={note} onChange={event => setNote(event.target.value)} placeholder="Describe the work completed or in progress"/></Field>
      <Field label="Status claim (optional)"><Input value={statusClaim} onChange={event => setStatusClaim(event.target.value)} placeholder="e.g. Ready for Supervisor review"/></Field>
      {/* capture="environment" biases the mobile OS picker to the rear
          camera - PDFs still reachable via the same picker's "Files"
          option, since browsers keep that choice alongside capture rather
          than locking to camera-only. */}
      <label className="grid gap-2 text-sm font-bold text-slate-700">Evidence photo or PDF (optional)<input className="w-full cursor-pointer rounded-xl border border-slate-200 bg-white text-sm font-normal text-slate-600 file:mr-4 file:border-0 file:bg-emerald-700 file:px-3 file:py-2 file:font-bold file:text-white hover:file:bg-emerald-800" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" capture="environment" onChange={event => setFile(event.target.files?.[0] || null)}/></label>
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-bold text-rose-700">{error}</div>}
      <Button type="submit" size="sm" loading={submitting} disabled={!note.trim() && !statusClaim.trim() && !file}>Submit progress</Button>
    </form>
  </section>;
}
