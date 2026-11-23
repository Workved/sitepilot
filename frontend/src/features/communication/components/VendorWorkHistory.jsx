import { useState } from "react";
import { Briefcase, CalendarRange, FolderKanban, History, MapPin, Pencil, Plus, Trash2, UserRound } from "lucide-react";
import { ConfirmModal, Modal, Pill } from "../../../components/ui";

// Who may add past projects (mirrors the backend's HISTORY_ROLES), and who
// may change or remove anyone's entry. Everyone else can only change their own.
const HISTORY_ROLES = new Set(["super_admin", "admin", "project_manager", "supervisor"]);
const HISTORY_ADMIN_ROLES = new Set(["super_admin", "admin"]);

export const canAddWorkHistory = user => HISTORY_ROLES.has(user?.role);
export const canEditWorkHistory = (user, entry) => HISTORY_ADMIN_ROLES.has(user?.role) || (Boolean(entry.created_by) && entry.created_by === user?.id);

const inputClass = "min-h-12 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-50";
const labelClass = "grid gap-2 text-sm font-black text-slate-700";

function monthLabel(value) {
  if (!value) return "";
  const [year, month] = value.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

function dateLabel(iso) {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { month: "short", year: "numeric" }) : "";
}

export function periodLabel(start, end) {
  if (start && end) return start === end ? monthLabel(start) : `${monthLabel(start)} - ${monthLabel(end)}`;
  if (start) return `From ${monthLabel(start)}`;
  if (end) return `Until ${monthLabel(end)}`;
  return "";
}

export function valueLabel(value) {
  if (value === null || value === undefined) return "";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
}

function PastProjectForm({ entry, categories, saving, onClose, onSubmit }) {
  const [error, setError] = useState("");
  const formId = "vendor-past-project-form";

  function submit(event) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    if (data.start_month && data.end_month && data.end_month < data.start_month) {
      setError("End month cannot be before the start month.");
      return;
    }
    setError("");
    onSubmit(data);
  }

  return <Modal
    className="max-w-3xl"
    title={entry ? "Edit past project" : "Add past project"}
    subtitle="Work this vendor did before or outside SiteOps."
    onClose={onClose}
    footer={<div className="flex justify-end"><button type="submit" form={formId} disabled={saving} className="min-h-12 rounded-xl bg-slate-950 px-6 font-black text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60">{saving ? "Saving..." : entry ? "Save changes" : "Add past project"}</button></div>}
  >
    <form id={formId} onSubmit={submit} className="grid grid-cols-2 gap-4 max-[720px]:grid-cols-1">
      <label className={`${labelClass} col-span-full max-[720px]:col-span-1`}>Project name<input className={inputClass} name="project_name" defaultValue={entry?.project_name || ""} placeholder="e.g. Skyline Towers interior fit-out" required/></label>
      <label className={labelClass}>Client<input className={inputClass} name="client_name" defaultValue={entry?.client_name || ""}/></label>
      <label className={labelClass}>Location<input className={inputClass} name="location" defaultValue={entry?.location || ""} placeholder="City or site"/></label>
      <label className={labelClass}>Work category<select className={inputClass} name="category_id" defaultValue={entry?.category_id || ""}><option value="">Not specified</option>{categories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
      <label className={labelClass}>Approx. value (₹)<input className={inputClass} name="approx_value" type="number" min="0" step="1" inputMode="numeric" defaultValue={entry?.approx_value ?? ""} placeholder="Optional"/></label>
      <label className={labelClass}>Start month<input className={inputClass} name="start_month" type="month" defaultValue={entry?.start_month || ""}/></label>
      <label className={labelClass}>End month<input className={inputClass} name="end_month" type="month" defaultValue={entry?.end_month || ""}/></label>
      <label className={`${labelClass} col-span-full max-[720px]:col-span-1`}>Work done<textarea className={`${inputClass} min-h-24 resize-y`} name="work_description" defaultValue={entry?.work_description || ""} placeholder="Scope the vendor handled on this project"/></label>
      <label className={`${labelClass} col-span-full max-[720px]:col-span-1`}>Notes<textarea className={`${inputClass} min-h-20 resize-y`} name="notes" defaultValue={entry?.notes || ""} placeholder="Quality, timeliness, anything worth remembering"/></label>
      {error && <p role="alert" className="col-span-full text-sm font-bold text-rose-700">{error}</p>}
    </form>
  </Modal>;
}

function PastProjectCard({ entry, canEdit, onEdit, onDelete }) {
  const period = periodLabel(entry.start_month, entry.end_month);
  const value = valueLabel(entry.approx_value);
  return <article className="rounded-2xl border border-slate-200 bg-white p-4">
    <div className="flex items-start gap-4">
      <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-700"><Briefcase size={19}/></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><strong className="text-slate-950">{entry.project_name}</strong>{entry.category_name && <Pill tone="blue">{entry.category_name}</Pill>}</div>
        {(entry.client_name || entry.location) && <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">{entry.client_name && <span>{entry.client_name}</span>}{entry.location && <span className="flex items-center gap-1"><MapPin size={13}/>{entry.location}</span>}</span>}
        {(period || value) && <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-bold text-slate-600">{period && <span className="flex items-center gap-1"><CalendarRange size={13}/>{period}</span>}{value && <span>{value}</span>}</span>}
        {entry.work_description && <p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700">{entry.work_description}</p>}
        {entry.notes && <p className="mt-2 whitespace-pre-line rounded-xl bg-slate-50 p-3 text-sm leading-6 text-slate-600">{entry.notes}</p>}
        {entry.created_by_name && <span className="mt-2 flex items-center gap-1 text-[11px] font-bold text-slate-400"><UserRound size={12}/>Added by {entry.created_by_name}</span>}
      </div>
      {canEdit && <div className="flex shrink-0 gap-1">
        <button type="button" aria-label={`Edit ${entry.project_name}`} onClick={onEdit} className="grid size-9 place-items-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"><Pencil size={15}/></button>
        <button type="button" aria-label={`Delete ${entry.project_name}`} onClick={onDelete} className="grid size-9 place-items-center rounded-lg text-slate-500 transition hover:bg-rose-50 hover:text-rose-700"><Trash2 size={15}/></button>
      </div>}
    </div>
  </article>;
}

export function VendorWorkHistory({ user, pastProjects = [], projectHistory = [], categories = [], saving = false, savePastProject, deletePastProject }) {
  const [editing, setEditing] = useState(null); // null | "new" | entry
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [deleteError, setDeleteError] = useState("");
  const canAdd = canAddWorkHistory(user);

  async function submit(data) {
    const result = await savePastProject(editing === "new" ? null : editing.id, data);
    if (result?.ok) setEditing(null);
  }

  async function confirmRemoval() {
    setDeleteError("");
    const result = await deletePastProject(confirmDelete.id);
    if (result?.ok) setConfirmDelete(null);
    else setDeleteError(result?.error || "This past project could not be removed.");
  }

  return <section className="grid gap-3" aria-label="Work history">
    <header className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-5">
      <div><h3 className="text-lg font-black text-slate-950">Work history</h3><p className="mt-1 text-sm text-slate-500">Projects this vendor has worked on before.</p></div>
      {canAdd && <button type="button" onClick={() => setEditing("new")} className="flex min-h-11 items-center gap-2 rounded-xl bg-blue-700 px-4 text-sm font-black text-white"><Plus size={17}/> Add past project</button>}
    </header>

    {projectHistory.length > 0 && <div className="grid gap-2">
      <p className="text-xs font-medium text-slate-500">In SiteOps</p>
      {projectHistory.map(item => <article key={item.id} className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-600"><FolderKanban size={19}/></span>
        <div className="min-w-0 flex-1"><strong className="block truncate text-slate-950">{item.project_name}</strong><span className="mt-1 block text-xs text-slate-500">{dateLabel(item.started_at)} - {dateLabel(item.ended_at)}</span></div>
        <Pill tone="gray">Ended</Pill>
      </article>)}
    </div>}

    {pastProjects.length > 0 && <div className="grid gap-2">
      <p className="text-xs font-medium text-slate-500">Before SiteOps</p>
      {pastProjects.map(entry => <PastProjectCard key={entry.id} entry={entry} canEdit={canEditWorkHistory(user, entry)} onEdit={() => setEditing(entry)} onDelete={() => { setDeleteError(""); setConfirmDelete(entry); }}/>)}
    </div>}

    {!projectHistory.length && !pastProjects.length && <div className="grid place-items-center rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 p-8 text-center">
      <span className="grid size-12 place-items-center rounded-2xl bg-white text-slate-400 shadow-sm"><History/></span>
      <h4 className="mt-4 font-black text-slate-900">No work history yet</h4>
      <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">{canAdd ? "Add projects this vendor has done before so the team can judge their experience." : "Past projects added by your team will show here."}</p>
    </div>}

    {editing && <PastProjectForm entry={editing === "new" ? null : editing} categories={categories} saving={saving} onClose={() => setEditing(null)} onSubmit={submit}/>}
    {confirmDelete && <ConfirmModal
      title={`Remove ${confirmDelete.project_name}?`}
      message={deleteError || "This removes the project from the vendor's work history. It cannot be undone."}
      confirmLabel={saving ? "Removing..." : "Remove"}
      confirmDisabled={saving}
      onClose={() => { setConfirmDelete(null); setDeleteError(""); }}
      onConfirm={confirmRemoval}/>}
  </section>;
}
