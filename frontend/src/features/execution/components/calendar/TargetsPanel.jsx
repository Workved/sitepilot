import { useMemo, useState } from "react";
import { Check, Search } from "lucide-react";
import { targetsApi } from "../../../../api/targetsApi";
import { Button, Field, Input, Modal, Textarea } from "../../../../components/ui";
import { localDay } from "./svarSetup";
import { TARGET_STYLE, targetLabel } from "./scheduleModel";

const ORDER = { missed: 0, due_soon: 1, open: 2, met: 3, cancelled: 4 };

export function targetSummary(targets, today) {
  const active = targets.filter(target => target.status === "active");
  const weekEnd = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 7);
  const open = active.filter(target => !["met", "cancelled"].includes(target.outcome?.state));
  return {
    active: active.length,
    missed: open.filter(target => target.outcome?.state === "missed").length,
    thisWeek: open.filter(target => { const day = localDay(target.target_date); return day >= today && day <= weekEnd; }).length,
  };
}

// The toolbar list: every active target, most urgent first.
export function TargetsList({ targets, onOpenTask, onAddProjectTarget, onlyTargets, onToggleOnly, canAdd }) {
  const active = targets.filter(target => target.status === "active")
    .sort((a, b) => (ORDER[a.outcome?.state] ?? 9) - (ORDER[b.outcome?.state] ?? 9) || a.target_date.localeCompare(b.target_date));
  return <div className="grid gap-2 p-1">
    <label className="flex items-center gap-2 text-[13px] text-slate-700">
      <input type="checkbox" checked={onlyTargets} onChange={onToggleOnly} className="size-4 accent-slate-950"/> Only show tasks with a target
    </label>
    {active.length
      ? <ul className="so-scroll grid max-h-72 gap-0.5 overflow-y-auto border-t border-line pt-2">
          {active.map(target => {
            const style = TARGET_STYLE[target.outcome?.state || "open"];
            return <li key={target.id}>
              <button type="button" onClick={() => target.task_id && onOpenTask(target.task_id)} disabled={!target.task_id}
                className="flex w-full items-start gap-2 rounded-xl px-2 py-1.5 text-left text-[13px] hover:bg-slate-50 disabled:cursor-default disabled:hover:bg-transparent">
                <span className="mt-1 size-2.5 shrink-0 rotate-45 rounded-[2px]" style={{ background: style.color }} aria-hidden="true"/>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-slate-950">{target.kind === "project" ? target.title : target.task_label}</span>
                  <span className={`block truncate ${style.text}`}>{targetLabel(target)}{target.kind === "project" && target.linked_tasks.length ? ` · ${target.outcome?.done ?? 0}/${target.outcome?.total ?? target.linked_tasks.length} tasks` : ""}</span>
                </span>
              </button>
            </li>;
          })}
        </ul>
      : <p className="border-t border-line pt-2 text-[13px] text-slate-500">No targets yet. Set one on a task from its detail, or add a project target.</p>}
    {canAdd && <Button size="sm" variant="secondary" onClick={onAddProjectTarget}>Add project target</Button>}
  </div>;
}

// A titled commitment for the whole project, optionally tied to tasks.
export function ProjectTargetModal({ projectId, tasks, onClose, onSaved }) {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [linked, setLinked] = useState(() => new Set());
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const open = useMemo(() => tasks.filter(task => !["completed", "cancelled"].includes(task.lifecycle_status)), [tasks]);
  const needle = query.trim().toLowerCase();
  const shown = open.filter(task => !needle || `${task.original_code} ${task.title} ${task.phase || ""}`.toLowerCase().includes(needle)).slice(0, 50);

  function toggle(id) { setLinked(current => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; }); }

  async function save(event) {
    event.preventDefault();
    if (!title.trim() || !date) return setError("Give the target a title and a date.");
    setSaving(true);
    setError("");
    try {
      await targetsApi.create(projectId, { kind: "project", title: title.trim(), target_date: date, note: note.trim() || null, task_ids: [...linked] });
      onSaved();
    } catch (caught) {
      setError(caught?.message || "The target couldn't be saved.");
      setSaving(false);
    }
  }

  return <Modal title="Add project target" subtitle="A date the whole team is working to, e.g. a client walkthrough." onClose={onClose} className="sm:max-w-xl"
    footer={<div className="flex justify-end"><Button type="submit" form="project-target-form" loading={saving}>Add target</Button></div>}>
    <form id="project-target-form" onSubmit={save} className="grid gap-4">
      <div className="grid items-start gap-4 sm:grid-cols-[minmax(0,1fr)_11rem]">
        <Field label="Title"><Input value={title} onChange={event => setTitle(event.target.value)} placeholder="Client walkthrough" maxLength={200} required/></Field>
        <Field label="Date"><Input type="date" value={date} onChange={event => setDate(event.target.value)} required/></Field>
      </div>
      <Field label="Note (optional)"><Textarea value={note} onChange={event => setNote(event.target.value)} placeholder="What has to be ready"/></Field>
      <div className="grid gap-2">
        <span className="text-sm font-medium text-slate-700">Tasks that must be done by then <span className="text-xs font-normal text-slate-400">optional</span></span>
        <p className="text-xs text-slate-500">With tasks linked, the target is met when they're all done by the date. Without, mark it achieved by hand.</p>
        <label className="relative"><span className="sr-only">Search tasks</span><Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search open tasks" className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-8 pr-3 text-sm outline-none focus:border-blue-600 focus:bg-white"/></label>
        <ul className="so-scroll grid max-h-48 gap-0.5 overflow-y-auto rounded-xl border border-line p-1">
          {shown.map(task => <li key={task.id}><label className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] hover:bg-slate-50">
            <input type="checkbox" checked={linked.has(task.id)} onChange={() => toggle(task.id)} className="size-4 accent-slate-950"/>
            <span className="tabular-nums text-slate-400">{task.original_code}</span><span className="truncate text-slate-900">{task.title}</span>
          </label></li>)}
          {!shown.length && <li className="px-2 py-2 text-[13px] text-slate-500">No open tasks match.</li>}
        </ul>
        {linked.size > 0 && <p className="flex items-center gap-1 text-xs text-slate-600"><Check size={13}/>{linked.size} linked</p>}
      </div>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
    </form>
  </Modal>;
}
