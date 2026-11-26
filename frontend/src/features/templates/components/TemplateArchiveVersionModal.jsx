import { createPortal } from "react-dom";
import { Archive, AlertTriangle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { templatesApi } from "../../../api/templatesApi";
import { Alert, Button, Input, LoadingSpinner, Select } from "../../../components/ui";

export function TemplateArchiveVersionModal({ version, onClose, onSuccess }) {
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(Boolean(version.is_current_published));
  const [replacementId, setReplacementId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!version.is_current_published) return undefined;
    const controller = new AbortController();
    templatesApi.list({ search: version.template_code, status: "published", page: 1, page_size: 100 }, { signal: controller.signal })
      .then(result => {
        const candidates = result.items.filter(item => item.template_id === version.template_id && item.version_id !== version.version_id && item.status === "published");
        setVersions(candidates);
        if (candidates.length === 1) setReplacementId(candidates[0].version_id);
      })
      .catch(requestError => { if (requestError.name !== "AbortError") setError(requestError.message || "Published versions could not be loaded."); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [version]);

  const canSubmit = useMemo(() => reason.trim() && (!version.is_current_published || replacementId), [reason, replacementId, version.is_current_published]);

  async function submit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true); setError("");
    try {
      const response = await templatesApi.archiveVersion(version.version_id, {
        revision_token: version.revision_token,
        reason: reason.trim(),
        replacement_current_version_id: version.is_current_published ? replacementId : null,
      });
      onSuccess(response);
    } catch (requestError) {
      setError(requestError.message || "The version could not be archived. Reload and retry.");
    } finally {
      setSubmitting(false);
    }
  }

  return createPortal(<div role="dialog" aria-modal="true" aria-labelledby="archive-version-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/60 p-4">
    <form onSubmit={submit} className="w-full max-w-xl rounded-[24px] bg-white p-5 shadow-2xl sm:p-6">
      <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-orange-100 text-orange-800"><Archive size={19}/></span><div><h2 id="archive-version-title" className="text-xl font-medium text-slate-950">Archive published version</h2><p className="mt-1 text-sm text-slate-600">Version {version.version_no} will leave active selection but remain available for audit and historical references.</p></div></div>
      <Alert tone="warning" className="mt-5"><AlertTriangle size={18}/><div><strong>Publication history will not be deleted.</strong><span className="mt-1 block font-medium">The archived version cannot be converted back to draft.</span></div></Alert>
      {loading ? <div className="grid min-h-24 place-items-center"><LoadingSpinner label="Loading replacement versions..."/></div> : <div className="mt-5 grid gap-4">
        {version.is_current_published && <label className="grid gap-2 text-sm font-bold text-slate-700">Restore current published version<Select aria-label="Replacement current published version" value={replacementId} onChange={event => setReplacementId(event.target.value)} required><option value="">Select another published version</option>{versions.map(item => <option key={item.version_id} value={item.version_id}>Version {item.version_no} — {item.change_note || "Published"}</option>)}</Select>{!versions.length && <span className="text-xs font-medium text-rose-700">No other published version is available. Publish a replacement before archiving this current version.</span>}</label>}
        <label className="grid gap-2 text-sm font-bold text-slate-700">Archive reason<Input aria-label="Archive reason" value={reason} onChange={event => setReason(event.target.value)} placeholder="Example: Remove published test version" required/></label>
      </div>}
      {error && <Alert tone="danger" className="mt-4">{error}</Alert>}
      <div className="mt-6 grid gap-2 sm:flex sm:justify-end"><Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>Cancel</Button><Button type="submit" disabled={!canSubmit || loading} loading={submitting}><Archive size={17}/> Archive version</Button></div>
    </form>
  </div>, document.body);
}
