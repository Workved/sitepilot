import { Upload } from "lucide-react";
import { useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { ReferenceFilePicker, uploadChosenFiles } from "../../../components/ReferenceFilePicker";

// Add reference files to a live task after it was created (for example a
// revised drawing). Admin and the project's own PM / Supervisor only - the
// same people who can add tasks; the backend re-checks.
export function TaskReferenceManager({ projectId, taskId, onChanged }) {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function upload() {
    if (!files.length || busy) return;
    setBusy(true); setError("");
    const failed = await uploadChosenFiles(files, item => projectsApi.addTaskReference(projectId, taskId, item));
    setBusy(false);
    setFiles([]);
    if (failed.length) setError(`Not uploaded: ${failed.join(", ")}`);
    await onChanged?.();
  }

  return <div className="grid gap-2 rounded-xl border border-slate-100 bg-slate-50/60 p-3">
    <span className="text-[11px] font-black uppercase tracking-wide text-slate-400">Add reference material</span>
    <ReferenceFilePicker id={`task-${taskId}-reference-files`} files={files} onChange={setFiles} disabled={busy}/>
    {files.length > 0 && <button type="button" onClick={upload} disabled={busy} className="flex min-h-10 w-fit items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-black text-white hover:bg-blue-700 disabled:opacity-60"><Upload size={15}/>{busy ? "Uploading..." : `Upload ${files.length} file${files.length === 1 ? "" : "s"}`}</button>}
    {error && <p role="alert" className="text-xs font-bold text-rose-700">{error}</p>}
  </div>;
}
