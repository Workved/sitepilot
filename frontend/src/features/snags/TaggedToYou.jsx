import { useState } from "react";
import { Check, ClipboardList, Flag } from "lucide-react";
import { snagsApi } from "../../api/snagsApi";
import { Modal } from "../../components/ui";
import { cn } from "../../utils/cn";
import { SnagItem } from "./SnagItem";
import { dueLabel, dueState } from "./snagHelpers";

// Open snags tagged to the signed-in person, across every project. Tick to
// close; click to see the whole snag (works even when the project itself is
// not one they can open).
export function TaggedToYou({ snags, onChange, onOpenProject, limit = 4 }) {
  const [opened, setOpened] = useState(null);
  const [busy, setBusy] = useState("");
  const open = snags.filter(item => item.status === "open");
  // Keep an opened snag's dialog up after it is closed, even if it was the
  // last open one; the card itself goes once the dialog is dismissed.
  if (!open.length && !opened) return null;

  async function close(snag) {
    setBusy(snag.id);
    try { onChange(await snagsApi.setStatus(snag.id, "done")); } catch { /* the row stays; the full view shows errors */ } finally { setBusy(""); }
  }

  const dialog = opened && <Modal title={opened.title} subtitle={`${opened.project_name}${opened.created_by ? ` · added by ${opened.created_by.name}` : ""}`} onClose={() => setOpened(null)} className="sm:max-w-2xl">
    <ul><SnagItem snag={snags.find(item => item.id === opened.id) || opened} defaultOpen showProject
      onOpenProject={(code, pane) => { setOpened(null); onOpenProject?.(code, pane); }}
      onChange={updated => onChange(updated)} onRemove={removed => { setOpened(null); onChange({ ...removed, status: "done" }); }}/></ul>
  </Modal>;
  if (!open.length) return dialog;

  return <section aria-label="Tagged to you" className="grid gap-2 rounded-2xl border border-line bg-white p-4">
    <h3 className="flex items-center gap-1.5 text-sm font-medium text-slate-950"><ClipboardList size={14} className="text-blue-700" aria-hidden="true"/> Tagged to you <span className="font-normal text-slate-400">{open.length}</span></h3>
    <ul className="grid gap-0.5">
      {open.slice(0, limit).map(snag => {
        const due = dueState(snag);
        return <li key={snag.id} className="flex items-start gap-2.5 rounded-xl px-1.5 py-1.5 hover:bg-slate-50">
          <button type="button" onClick={() => close(snag)} disabled={busy === snag.id || !snag.can_close} aria-label={`Mark ${snag.title} done`}
            className="mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border-2 border-slate-300 text-transparent transition hover:border-ok hover:text-ok disabled:opacity-50">
            <Check size={10} strokeWidth={3} aria-hidden="true"/>
          </button>
          <button type="button" onClick={() => setOpened(snag)} className="min-w-0 flex-1 text-left text-[13px]">
            <span className="flex items-center gap-1.5 text-slate-950">{snag.urgent && <Flag size={12} className="shrink-0 text-rose-700" aria-label="Urgent"/>}<span className="truncate">{snag.title}</span></span>
            <span className="block truncate text-slate-500">{snag.project_name}{snag.area ? ` · ${snag.area}` : ""}{snag.due_date ? <span className={cn(due === "overdue" && "text-rose-700", due === "today" && "text-orange-700")}> · {dueLabel(snag)}</span> : null}</span>
          </button>
        </li>;
      })}
    </ul>
    {open.length > limit && <p className="text-xs text-slate-500">{open.length - limit} more. Open a project's Snags tab and choose "Tagged to me".</p>}

    {dialog}
  </section>;
}
