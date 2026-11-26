import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Download, Flag, MapPin, Paperclip, Trash2, X } from "lucide-react";
import { snagsApi } from "../../api/snagsApi";
import { Button, ConfirmModal } from "../../components/ui";
import { cn } from "../../utils/cn";
import { initials } from "../../utils/format";
import { dueLabel, dueState } from "./snagHelpers";

// People are the same for every snag on the page: fetch once.
let peoplePromise = null;
export function loadPeople() {
  if (!peoplePromise) peoplePromise = snagsApi.people().catch(error => { peoplePromise = null; throw error; });
  return peoplePromise;
}
export function resetPeopleCache() { peoplePromise = null; }

function triggerDownload({ blob, filename }) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function Avatar({ person, size = "size-6" }) {
  return <span className={cn("grid shrink-0 place-items-center rounded-full bg-blue-50 text-[10px] font-medium text-blue-800", size)} aria-hidden="true">{initials(person.name)}</span>;
}

// Search everyone in SiteOps by name; shows each person's role.
export function PersonPicker({ value, onChange, disabled }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [people, setPeople] = useState([]);
  const [error, setError] = useState("");
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    loadPeople().then(setPeople).catch(() => setError("Couldn't load people."));
    const onDown = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  const needle = query.trim().toLowerCase();
  const matches = people.filter(person => !needle || person.name.toLowerCase().includes(needle) || person.role_label.toLowerCase().includes(needle)).slice(0, 8);

  function pick(person) { setOpen(false); setQuery(""); onChange(person); }

  return <div ref={ref} className="relative">
    <button type="button" disabled={disabled} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(value => !value)}
      className="flex h-9 w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 text-left text-sm text-slate-950 outline-none hover:border-slate-300 focus-visible:border-blue-600 disabled:cursor-default disabled:hover:border-slate-200">
      {value ? <><Avatar person={value}/><span className="min-w-0 flex-1 truncate">{value.name}</span><span className="truncate text-xs text-slate-500">{value.role_label}</span></>
        : <span className="flex-1 text-slate-400">Tag someone</span>}
      {!disabled && <ChevronDown size={14} className="shrink-0 text-slate-400" aria-hidden="true"/>}
    </button>
    {open && <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-30 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      <input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Search people" aria-label="Search people" autoComplete="off"
        className="mb-1 h-9 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 text-sm outline-none focus:border-blue-600 focus:bg-white"/>
      <ul role="listbox" aria-label="People" className="so-scroll max-h-60 overflow-y-auto">
        {value && <li><button type="button" role="option" aria-selected="false" onClick={() => pick(null)} className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm text-slate-600 hover:bg-slate-50"><X size={14}/> Remove tag</button></li>}
        {matches.map(person => <li key={person.id}><button type="button" role="option" aria-selected={value?.id === person.id} onClick={() => pick(person)}
          className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm hover:bg-slate-50">
          <Avatar person={person}/><span className="min-w-0 flex-1 truncate text-slate-950">{person.name}</span><span className="text-xs text-slate-500">{person.role_label}</span>
        </button></li>)}
        {!matches.length && <li className="px-2.5 py-2 text-sm text-slate-500">{error || (people.length ? "No one matches." : "Loading…")}</li>}
      </ul>
    </div>}
  </div>;
}

function TextField({ label, value, onSave, disabled, multiline = false, placeholder, type = "text" }) {
  const [draft, setDraft] = useState(value || "");
  useEffect(() => { setDraft(value || ""); }, [value]);
  const common = {
    value: draft, disabled, placeholder, "aria-label": label,
    onChange: event => setDraft(event.target.value),
    onBlur: () => { if ((draft || "") !== (value || "")) onSave(draft); },
    className: "w-full rounded-lg border border-slate-200 bg-white px-2.5 text-sm text-slate-950 outline-none placeholder:text-slate-400 focus:border-blue-600 disabled:border-transparent disabled:bg-transparent disabled:px-0",
  };
  // Read-only and empty: say so, rather than showing an empty input or a
  // browser date placeholder.
  if (disabled && !value) return <div className="grid gap-1"><span className="text-xs text-slate-500">{label}</span><span className="text-sm text-slate-400">Not set</span></div>;
  return <label className="grid gap-1">
    <span className="text-xs text-slate-500">{label}</span>
    {multiline
      ? <textarea {...common} rows={3} className={cn(common.className, "min-h-20 resize-y py-2 leading-6")}/>
      : <input {...common} type={type} onKeyDown={event => { if (event.key === "Enter") event.currentTarget.blur(); }} className={cn(common.className, "h-9")}/>}
  </label>;
}

// One snag: a Google Tasks style row (tick, title, a line of facts) that
// expands in place into its details. Every edit saves on its own.
export function SnagItem({ snag, onChange, onRemove, showProject = false, onOpenProject, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [closing, setClosing] = useState(false);
  const [note, setNote] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const fileInput = useRef(null);
  const done = snag.status === "done";
  const due = dueState(snag);

  async function run(key, operation) {
    setBusy(key);
    setError("");
    try {
      const updated = await operation();
      if (updated?.id) onChange(updated);
      return true;
    } catch (caught) {
      setError(caught?.message || "That didn't save. Try again.");
      return false;
    } finally {
      setBusy("");
    }
  }

  const save = changes => run("save", () => snagsApi.update(snag.id, changes));
  const toggle = closingNote => run("status", () => snagsApi.setStatus(snag.id, done ? "open" : "done", closingNote));

  async function remove() {
    const ok = await run("delete", async () => { await snagsApi.remove(snag.id); return null; });
    if (ok) { setConfirmDelete(false); onRemove?.(snag); }
  }

  async function attach(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) await run("file", () => snagsApi.addFile(snag.id, file));
  }

  async function download(file) {
    try { triggerDownload(await snagsApi.downloadFile(snag.id, file.id)); } catch (caught) { setError(caught?.message || "That file couldn't be downloaded."); }
  }

  const facts = [
    snag.urgent && !done && <span key="u" className="inline-flex items-center gap-1 text-rose-700"><Flag size={12} aria-hidden="true"/>Urgent</span>,
    showProject && <span key="p" className="truncate">{snag.project_name}</span>,
    snag.area && <span key="a" className="inline-flex items-center gap-1"><MapPin size={12} aria-hidden="true"/>{snag.area}</span>,
    snag.due_date && !done && <span key="d" className={cn(due === "overdue" ? "text-rose-700" : due === "today" ? "text-orange-700" : "")}>{dueLabel(snag)}</span>,
    snag.files.length > 0 && <span key="f" className="inline-flex items-center gap-1"><Paperclip size={12} aria-hidden="true"/>{snag.files.length}</span>,
    done && snag.closed_by && <span key="c">Done by {snag.closed_by.name}</span>,
  ].filter(Boolean);

  return <li className={cn("group rounded-2xl transition-colors", open ? "bg-white ring-1 ring-line" : "hover:bg-slate-50")}>
    <div className="flex items-start gap-3 px-3 py-2.5">
      <button type="button" onClick={() => toggle()} disabled={!snag.can_close || busy === "status"}
        aria-label={done ? `Reopen ${snag.title}` : `Mark ${snag.title} done`} title={snag.can_close ? undefined : "You can't close this snag"}
        className={cn("mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border-2 transition", done ? "border-ok bg-ok text-white" : "border-slate-300 text-transparent hover:border-ok hover:text-ok", !snag.can_close && "cursor-not-allowed opacity-50")}>
        <Check size={12} strokeWidth={3} aria-hidden="true"/>
      </button>
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} className="min-w-0 flex-1 text-left">
        <span className={cn("block text-sm", done ? "text-slate-400 line-through" : "text-slate-950")}>{snag.title}</span>
        {facts.length > 0 && <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-500">{facts}</span>}
      </button>
      {snag.assignee
        ? <span className="flex shrink-0 items-center gap-1.5 text-xs text-slate-600" title={`Tagged to ${snag.assignee.name}`}><Avatar person={snag.assignee}/><span className="hidden max-w-[9rem] truncate sm:inline">{snag.assignee.name}</span></span>
        : <span className="hidden shrink-0 text-xs text-slate-400 sm:inline">No one tagged</span>}
    </div>

    {open && <div className="grid gap-4 border-t border-line px-3 pb-4 pt-3 sm:pl-11">
      {showProject && <p className="text-xs text-slate-500">
        {snag.can_open_project && onOpenProject
          ? <button type="button" onClick={() => onOpenProject(snag.project_code, "snags")} className="text-blue-700 hover:underline">{snag.project_name}</button>
          : snag.project_name}
      </p>}
      {snag.can_edit && <TextField label="Title" value={snag.title} onSave={title => title.trim() && save({ title })}/>}
      <TextField label="Notes" value={snag.notes} multiline disabled={!snag.can_edit} placeholder={snag.can_edit ? "What exactly needs doing" : "No notes"} onSave={notes => save({ notes })}/>
      <div className="grid gap-3 sm:grid-cols-3">
        <TextField label="Area" value={snag.area} disabled={!snag.can_edit} placeholder={snag.can_edit ? "e.g. Cabin 3" : "-"} onSave={area => save({ area })}/>
        <TextField label="Due date" type="date" value={snag.due_date} disabled={!snag.can_edit} onSave={value => save({ due_date: value || null })}/>
        <div className="grid gap-1">
          <span className="text-xs text-slate-500">Urgent</span>
          <button type="button" role="switch" aria-checked={snag.urgent} aria-label="Urgent" disabled={!snag.can_edit} onClick={() => save({ urgent: !snag.urgent })}
            className={cn("flex h-9 w-fit items-center gap-2 rounded-lg px-2.5 text-sm transition", snag.urgent ? "bg-rose-50 text-rose-800" : "bg-slate-100 text-slate-600", !snag.can_edit && "cursor-default")}>
            <Flag size={14} aria-hidden="true"/>{snag.urgent ? "Urgent" : "Not urgent"}
          </button>
        </div>
      </div>
      <div className="grid gap-1 sm:max-w-sm">
        <span className="text-xs text-slate-500">Tagged to</span>
        <PersonPicker value={snag.assignee} disabled={!snag.can_edit} onChange={person => save({ assignee_user_id: person?.id || null })}/>
      </div>

      <div className="grid gap-2">
        <span className="text-xs text-slate-500">Attachments</span>
        {snag.files.length > 0 && <ul className="flex flex-wrap gap-2">
          {snag.files.map(file => <li key={file.id} className="flex items-center gap-1 rounded-lg bg-canvas py-1 pl-2.5 pr-1 text-xs text-slate-700">
            <button type="button" onClick={() => download(file)} className="flex items-center gap-1.5 hover:text-slate-950" aria-label={`Download ${file.filename}`}><Download size={12}/>{file.filename}</button>
            {snag.can_edit && <button type="button" aria-label={`Remove ${file.filename}`} onClick={() => run("file", () => snagsApi.removeFile(snag.id, file.id))} className="grid size-5 place-items-center rounded text-slate-400 hover:text-rose-700"><X size={12}/></button>}
          </li>)}
        </ul>}
        {snag.can_attach && <div>
          <input ref={fileInput} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,.docx,.xlsx" className="hidden" onChange={attach} aria-label="Attach a file"/>
          <Button size="sm" variant="secondary" loading={busy === "file"} onClick={() => fileInput.current?.click()}><Paperclip size={14}/> Attach a photo or file</Button>
          <span className="ml-2 text-xs text-slate-400">PDF, JPG, PNG, WebP, DOCX or XLSX, up to 10 MB</span>
        </div>}
        {!snag.files.length && !snag.can_attach && <span className="text-sm text-slate-400">None</span>}
      </div>

      {done && <p className="rounded-xl bg-emerald-50 px-3 py-2 text-[13px] leading-5 text-emerald-900">
        Done by {snag.closed_by?.name || "someone"} on {new Date(snag.closed_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}{snag.closing_note ? `: ${snag.closing_note}` : "."}
      </p>}

      {!done && snag.can_close && (closing
        ? <div className="flex flex-wrap items-end gap-2">
            <label className="grid min-w-[220px] flex-1 gap-1"><span className="text-xs text-slate-500">Closing note (optional)</span>
              <input autoFocus value={note} onChange={event => setNote(event.target.value)} placeholder="What was done" className="h-9 rounded-lg border border-slate-200 px-2.5 text-sm outline-none focus:border-blue-600"/></label>
            <Button size="sm" loading={busy === "status"} onClick={async () => { if (await toggle(note.trim())) { setClosing(false); setNote(""); } }}><Check size={14}/> Mark done</Button>
            <Button size="sm" variant="ghost" onClick={() => setClosing(false)}>Cancel</Button>
          </div>
        : <Button size="sm" variant="secondary" className="w-fit" onClick={() => setClosing(true)}><Check size={14}/> Mark done with a note</Button>)}

      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
        <span>Added by {snag.created_by?.name || "someone"} · {new Date(snag.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}{busy === "save" ? " · Saving…" : ""}</span>
        {snag.can_delete && <button type="button" onClick={() => setConfirmDelete(true)} className="inline-flex items-center gap-1 text-rose-700 hover:underline"><Trash2 size={12}/> Delete</button>}
      </div>
    </div>}

    {confirmDelete && <ConfirmModal title="Delete this snag?" message={`"${snag.title}" and its attachments will be removed. If it's fixed, mark it done instead so there's a record.`}
      confirmLabel="Delete snag" confirmDisabled={busy === "delete"} onClose={() => setConfirmDelete(false)} onConfirm={remove}/>}
  </li>;
}
