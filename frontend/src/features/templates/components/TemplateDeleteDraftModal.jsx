import { AlertTriangle, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { templatesApi } from "../../../api/templatesApi";
import { Alert, Button, Input } from "../../../components/ui";

function messageFromApiError(error) {
  const detail = error?.details?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(item => item?.msg || item?.message).filter(Boolean).join(" ") || "The draft request was invalid.";
  if (detail && typeof detail === "object") return detail.message || detail.code || "The draft could not be deleted.";
  return error?.message || "The draft could not be deleted. Reload and retry.";
}

export function TemplateDeleteDraftModal({ version, onClose, onSuccess }) {
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const canSubmit = useMemo(() => reason.trim() && confirmation.trim().toUpperCase() === "DELETE", [reason, confirmation]);

  async function submit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true); setError("");
    try {
      const currentVersion = version.revision_token
        ? version
        : await templatesApi.getVersion(version.version_id);
      const response = await templatesApi.deleteDraftVersion(version.version_id, {
        revision_token: currentVersion.revision_token,
        reason: reason.trim(),
      });
      onSuccess(response);
    } catch (requestError) {
      setError(messageFromApiError(requestError));
    } finally { setSubmitting(false); }
  }

  return <div role="dialog" aria-modal="true" aria-labelledby="delete-draft-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/60 p-4">
    <form onSubmit={submit} className="w-full max-w-xl rounded-[24px] bg-white p-5 shadow-2xl sm:p-6">
      <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-rose-100 text-rose-700"><Trash2 size={19}/></span><div><h2 id="delete-draft-title" className="text-xl font-medium text-slate-950">Delete unused draft</h2><p className="mt-1 text-sm text-slate-600">Version {version.version_no} and its draft tasks, dependencies and gates will be permanently removed.</p></div></div>
      <Alert tone="danger" className="mt-5"><AlertTriangle size={18}/><div><strong>This cannot be undone.</strong><span className="mt-1 block font-medium">Published and archived versions cannot be deleted through this action.</span></div></Alert>
      <div className="mt-5 grid gap-4">
        <label className="grid gap-2 text-sm font-bold text-slate-700">Deletion reason<Input aria-label="Draft deletion reason" value={reason} onChange={event => setReason(event.target.value)} placeholder="Example: Remove test draft created during validation" required/></label>
        <label className="grid gap-2 text-sm font-bold text-slate-700">Type DELETE to confirm<Input aria-label="Type DELETE to confirm" value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="off" required/></label>
      </div>
      {error && <Alert tone="danger" className="mt-4">{error}</Alert>}
      <div className="mt-6 grid gap-2 sm:flex sm:justify-end"><Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>Cancel</Button><Button type="submit" disabled={!canSubmit} loading={submitting}><Trash2 size={17}/> Delete draft</Button></div>
    </form>
  </div>;
}
