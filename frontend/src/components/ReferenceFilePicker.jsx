import { FileText, Paperclip, X } from "lucide-react";
import { useState } from "react";

// Mirrors the server's rules (template_reference_files.validate_reference_file),
// which still re-check every upload.
export const ACCEPTED_REFERENCE_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".docx", ".xlsx"];
export const MAX_REFERENCE_BYTES = 10 * 1024 * 1024;

export function referenceFileProblem(file) {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_REFERENCE_EXTENSIONS.some(extension => name.endsWith(extension))) return "Reference files must be PDF, JPG, PNG, WebP, DOCX or XLSX.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_REFERENCE_BYTES) return "Reference files must be 10 MB or smaller.";
  return "";
}

const sizeLabel = bytes => bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

/**
 * Reference material chosen while a task is being created. Nothing is
 * uploaded here: the form uploads `files` ({ file, description }) right after
 * the task is saved, as part of the same Save.
 */
export function ReferenceFilePicker({ files, onChange, disabled = false, id = "reference-files" }) {
  const [error, setError] = useState("");
  const [inputKey, setInputKey] = useState(0);

  function choose(list) {
    const chosen = [...(list || [])];
    const problems = chosen.map(file => [file, referenceFileProblem(file)]);
    const bad = problems.find(([, problem]) => problem);
    setError(bad ? `${bad[0].name}: ${bad[1]}` : "");
    const good = problems.filter(([, problem]) => !problem).map(([file]) => ({ file, description: "" }));
    if (good.length) onChange([...files, ...good]);
    setInputKey(key => key + 1);
  }

  return <div className="grid gap-3">
    <p className="text-xs font-semibold text-slate-500">Optional. Drawings, specs or photos the person doing the work should look at - not proof of work. PDF, JPG, PNG, WebP, DOCX or XLSX, up to 10 MB each.</p>
    {files.length > 0 && <ul className="grid gap-2">
      {files.map((item, index) => <li key={`${item.file.name}-${index}`} className="grid gap-2 rounded-xl border border-slate-200 bg-white p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center">
        <span className="flex min-w-0 items-center gap-2 text-sm font-bold text-slate-800"><FileText size={16} className="shrink-0 text-slate-400"/><span className="truncate">{item.file.name}</span><span className="shrink-0 text-xs font-semibold text-slate-400">{sizeLabel(item.file.size)}</span></span>
        <input aria-label={`Note for ${item.file.name}`} value={item.description} maxLength={500} disabled={disabled} placeholder="Note (optional)"
          onChange={event => onChange(files.map((other, i) => i === index ? { ...other, description: event.target.value } : other))}
          className="min-h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-600"/>
        <button type="button" aria-label={`Remove ${item.file.name}`} disabled={disabled} onClick={() => onChange(files.filter((_, i) => i !== index))} className="grid size-9 place-items-center rounded-lg text-slate-500 hover:bg-rose-50 hover:text-rose-700"><X size={16}/></button>
      </li>)}
    </ul>}
    <label htmlFor={id} className={`flex min-h-11 w-fit cursor-pointer items-center gap-2 rounded-xl border border-dashed border-blue-300 bg-blue-50/50 px-4 text-sm font-black text-blue-700 hover:bg-blue-50 ${disabled ? "pointer-events-none opacity-60" : ""}`}>
      <Paperclip size={16}/> {files.length ? "Add another file" : "Attach reference files"}
      <input key={inputKey} id={id} type="file" multiple accept={ACCEPTED_REFERENCE_EXTENSIONS.join(",")} className="sr-only" disabled={disabled} onChange={event => choose(event.target.files)}/>
    </label>
    {error && <p role="alert" className="text-sm font-bold text-rose-700">{error}</p>}
  </div>;
}

/**
 * Upload chosen files one by one after the task exists. Returns the names of
 * files that failed (with why), so the form can say so instead of losing them.
 */
export async function uploadChosenFiles(files, uploadOne) {
  const failed = [];
  for (const item of files) {
    try {
      await uploadOne(item);
    } catch (error) {
      failed.push(`${item.file.name} (${error?.message || "upload failed"})`);
    }
  }
  return failed;
}
