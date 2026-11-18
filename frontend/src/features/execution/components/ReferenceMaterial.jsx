import { FileText, Paperclip } from "lucide-react";
import { useState } from "react";

function sizeLabel(bytes) {
  if (!bytes) return "";
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * Read-only guidance from the template the project was created from: what
 * proof the work needs, and the Admin's reference files. Deliberately separate
 * from the evidence people submit. Renders nothing when there is neither.
 */
export function ReferenceMaterial({ instructions, files = [], onDownload, onRemove, className = "" }) {
  const [error, setError] = useState("");
  if (!instructions && !files.length) return null;

  async function download(file) {
    setError("");
    try {
      const { blob, filename } = await onDownload(file);
      triggerDownload(blob, filename || file.filename);
    } catch (caught) {
      setError(caught?.message || "This reference file could not be downloaded.");
    }
  }

  return <div className={`grid gap-3 ${className}`}>
    {instructions && <div>
      <h4 className="text-[11px] font-black uppercase tracking-wide text-slate-400">What proof is needed</h4>
      <p className="mt-1 whitespace-pre-line text-sm leading-6 text-slate-700">{instructions}</p>
    </div>}
    {files.length > 0 && <div>
      <h4 className="flex items-center gap-1.5 text-[11px] font-black uppercase tracking-wide text-slate-400"><Paperclip size={12}/> Reference material</h4>
      <ul className="mt-2 grid gap-2">
        {files.map(file => <li key={file.id} className="flex items-start gap-2">
          <button type="button" onClick={() => download(file)} aria-label={`Download ${file.filename}`}
            className="flex min-w-0 flex-1 items-start gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-left hover:border-blue-300 hover:bg-blue-50">
            <FileText size={16} className="mt-0.5 shrink-0 text-blue-700"/>
            <span className="min-w-0">
              <span className="block truncate text-sm font-bold text-blue-700">{file.filename}</span>
              {file.description && <span className="block text-xs font-semibold text-slate-600">{file.description}</span>}
              <span className="block text-[11px] font-semibold text-slate-400">{sizeLabel(file.size_bytes)}{file.source === "project" ? " · added on this project" : ""}</span>
            </span>
          </button>
          {/* Only files added on the project can be removed; template files stay as published. */}
          {onRemove && file.source === "project" && <button type="button" aria-label={`Remove ${file.filename}`} onClick={() => onRemove(file)}
            className="min-h-10 shrink-0 rounded-xl border border-slate-200 px-3 text-xs font-black text-rose-700 hover:bg-rose-50">Remove</button>}
        </li>)}
      </ul>
    </div>}
    {error && <p role="alert" className="text-xs font-bold text-rose-700">{error}</p>}
  </div>;
}
