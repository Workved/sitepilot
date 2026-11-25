import { useState } from "react";
import { CalendarRange, History, MapPin, MessageSquarePlus, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { Button, ConfirmModal, Modal, Pill } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { needsComment, REHIRE_LABEL, REHIRE_OPTIONS, REHIRE_TONE, SCORE_FIELDS, Stars } from "../vendorFeedback";

// Who may add past projects (mirrors the backend's HISTORY_ROLES), and who
// may change or remove anyone's entry. Everyone else can only change their own.
const HISTORY_ROLES = new Set(["super_admin", "admin", "project_manager", "supervisor"]);
const HISTORY_ADMIN_ROLES = new Set(["super_admin", "admin"]);

export const canAddWorkHistory = user => HISTORY_ROLES.has(user?.role);
export const canEditWorkHistory = (user, entry) => HISTORY_ADMIN_ROLES.has(user?.role) || (Boolean(entry.created_by) && entry.created_by === user?.id);

const inputClass = "min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10";
const labelClass = "grid gap-2 text-sm font-medium text-slate-700";

function monthLabel(value) {
  if (!value) return "";
  const [year, month] = value.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

function dateLabel(iso) {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { month: "short", year: "numeric" }) : "";
}

function dayLabel(iso) {
  return iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";
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
    footer={<div className="flex justify-end"><Button type="submit" form={formId} disabled={saving}>{saving ? "Saving..." : entry ? "Save changes" : "Add past project"}</Button></div>}
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
      {error && <p role="alert" className="col-span-full text-sm text-rose-700">{error}</p>}
    </form>
  </Modal>;
}

function IconAction({ label, onClick, danger, children }) {
  return <button type="button" aria-label={label} onClick={onClick}
    className={cn("grid size-8 place-items-center rounded-lg text-slate-500 transition", danger ? "hover:bg-rose-50 hover:text-rose-700" : "hover:bg-slate-100 hover:text-slate-950")}>{children}</button>;
}

function PastProjectCard({ entry, canEdit, onEdit, onDelete }) {
  const period = periodLabel(entry.start_month, entry.end_month);
  const value = valueLabel(entry.approx_value);
  return <article aria-label={entry.project_name} className="rounded-2xl border border-line p-4">
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><h5 className="text-sm text-slate-950">{entry.project_name}</h5>{entry.category_name && <Pill tone="gray">{entry.category_name}</Pill>}</div>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-500">
          {entry.client_name && <span>{entry.client_name}</span>}
          {entry.location && <span className="inline-flex items-center gap-1"><MapPin size={12}/>{entry.location}</span>}
          {period && <span className="inline-flex items-center gap-1"><CalendarRange size={12}/>{period}</span>}
          {value && <span>{value}</span>}
        </p>
        {entry.work_description && <p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700">{entry.work_description}</p>}
        {entry.notes && <p className="mt-2 whitespace-pre-line rounded-xl bg-canvas p-3 text-sm leading-6 text-slate-600">{entry.notes}</p>}
        {entry.created_by_name && <p className="mt-2 text-xs text-slate-400">Added by {entry.created_by_name}</p>}
      </div>
      {canEdit && <div className="flex shrink-0 gap-0.5">
        <IconAction label={`Edit ${entry.project_name}`} onClick={onEdit}><Pencil size={15}/></IconAction>
        <IconAction label={`Delete ${entry.project_name}`} onClick={onDelete} danger><Trash2 size={15}/></IconAction>
      </div>}
    </div>
  </article>;
}

// ---- feedback ---------------------------------------------------------------

// Five tappable stars as a radio group. `optional` adds a way back to "not rated".
function StarInput({ label, value, onChange, optional = false, size = 26 }) {
  return <div role="radiogroup" aria-label={label} className="flex items-center gap-1">
    {[1, 2, 3, 4, 5].map(n => <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} of 5`}
      onClick={() => onChange(optional && value === n ? null : n)}
      className="rounded-md p-0.5 transition hover:scale-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600">
      <Star size={size} aria-hidden="true" className={n <= (value || 0) ? "fill-amber-400 text-amber-400" : "fill-slate-100 text-slate-300"}/>
    </button>)}
    {optional && value && <button type="button" onClick={() => onChange(null)} className="ml-1 text-xs text-slate-500 hover:text-slate-950">Clear</button>}
  </div>;
}

const RATING_WORDS = { 1: "Poor", 2: "Below expectations", 3: "Acceptable", 4: "Good", 5: "Excellent" };

function FeedbackForm({ vendorName, projectName, entry, saving, onClose, onSubmit }) {
  const [form, setForm] = useState(() => ({
    rating: entry?.rating || null, quality: entry?.quality ?? null, timeliness: entry?.timeliness ?? null, conduct: entry?.conduct ?? null,
    would_rehire: entry?.would_rehire || "", comment: entry?.comment || "",
  }));
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));
  const commentRequired = form.rating && needsComment(form);

  async function submit(event) {
    event.preventDefault();
    if (!form.rating) return setError("Pick an overall rating.");
    if (!form.would_rehire) return setError("Say whether you would hire them again.");
    if (commentRequired && !form.comment.trim()) return setError("Add a comment explaining a low rating or a 'would not hire again'.");
    setError("");
    const result = await onSubmit({ ...form, comment: form.comment.trim() || null });
    if (result && !result.ok) setError(result.error || "This feedback could not be saved.");
  }

  return <Modal title={entry ? "Edit your feedback" : "Leave feedback"} subtitle={`How ${vendorName} worked on ${projectName}`} onClose={onClose} className="sm:max-w-xl"
    footer={<div className="flex justify-end"><Button type="submit" form="vendor-feedback-form" loading={saving}>{entry ? "Save feedback" : "Submit feedback"}</Button></div>}>
    <form id="vendor-feedback-form" onSubmit={submit} className="grid gap-5">
      <div className="grid gap-2">
        <span className="text-sm font-medium text-slate-700">Overall rating</span>
        <div className="flex flex-wrap items-center gap-3">
          <StarInput label="Overall rating" value={form.rating} onChange={value => set("rating", value)}/>
          {form.rating && <span className="text-sm text-slate-600">{RATING_WORDS[form.rating]}</span>}
        </div>
      </div>

      <div className="grid gap-2.5 rounded-2xl bg-canvas p-4">
        <span className="text-sm text-slate-700">In detail <span className="text-xs text-slate-400">optional</span></span>
        {SCORE_FIELDS.map(([key, label]) => <div key={key} className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm text-slate-600">{label}</span>
          <StarInput label={label} value={form[key]} onChange={value => set(key, value)} optional size={18}/>
        </div>)}
      </div>

      <div className="grid gap-2">
        <span className="text-sm font-medium text-slate-700" id="rehire-label">Would you hire them again?</span>
        <div role="radiogroup" aria-labelledby="rehire-label" className="flex w-fit gap-0.5 rounded-[10px] bg-slate-100 p-[3px]">
          {REHIRE_OPTIONS.map(([value, label]) => <button key={value} type="button" role="radio" aria-checked={form.would_rehire === value} onClick={() => set("would_rehire", value)}
            className={cn("h-8 rounded-lg px-3 text-[13px] transition", form.would_rehire === value ? "bg-white text-slate-950 shadow-[0_1px_3px_rgba(21,23,26,.12)]" : "text-slate-500 hover:text-slate-950")}>{label}</button>)}
        </div>
      </div>

      <label className={labelClass}>
        <span>Comment {commentRequired ? <span className="text-xs text-rose-700">required for this rating</span> : <span className="text-xs text-slate-400">optional</span>}</span>
        <textarea className={`${inputClass} min-h-24 resize-y`} value={form.comment} onChange={event => set("comment", event.target.value)}
          placeholder="What went well, what didn't, anything the next team should know"/>
      </label>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
    </form>
  </Modal>;
}

function FeedbackItem({ item, canEdit, canDelete, onEdit, onDelete }) {
  const scores = SCORE_FIELDS.filter(([key]) => item[key] != null);
  return <li className="grid gap-1.5 rounded-xl bg-canvas p-3">
    <div className="flex flex-wrap items-center gap-2">
      <Stars value={item.rating}/>
      <span className="text-sm tabular-nums text-slate-950">{item.rating}/5</span>
      <Pill tone={REHIRE_TONE[item.would_rehire]} className="normal-case">{REHIRE_LABEL[item.would_rehire]}</Pill>
      {(canEdit || canDelete) && <span className="ml-auto flex gap-0.5">
        {canEdit && <IconAction label={`Edit feedback by ${item.author_name}`} onClick={onEdit}><Pencil size={14}/></IconAction>}
        {canDelete && <IconAction label={`Delete feedback by ${item.author_name}`} onClick={onDelete} danger><Trash2 size={14}/></IconAction>}
      </span>}
    </div>
    {scores.length > 0 && <p className="flex flex-wrap gap-x-3 text-xs text-slate-600">{scores.map(([key, label]) => <span key={key}>{label} <span className="tabular-nums text-slate-950">{item[key]}</span></span>)}</p>}
    {item.comment && <p className="whitespace-pre-line text-sm leading-6 text-slate-800">{item.comment}</p>}
    <p className="text-xs text-slate-500">{item.author_name}, {item.author_role_label} · {dayLabel(item.updated_at || item.created_at)}</p>
  </li>;
}

function SiteOpsProject({ entry, reviews, user, onReview, onEditReview, onDeleteReview }) {
  const mine = reviews.find(item => item.author_user_id === user?.id);
  const isAdmin = HISTORY_ADMIN_ROLES.has(user?.role);
  // `removed` is missing from an older API that only listed removals; say
  // "Ended" there rather than claiming the project was completed.
  const outcome = entry.removed ? "Removed" : entry.removed === undefined ? "Ended" : entry.project_status === "archived" ? "Archived" : "Completed";
  return <article aria-label={entry.project_name} className="rounded-2xl border border-line p-4">
    <div className="flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h5 className="text-sm text-slate-950">{entry.project_name}</h5>
          <Pill tone={entry.removed ? "orange" : "gray"}>{outcome}</Pill>
        </div>
        <p className="mt-0.5 text-xs text-slate-500">
          {[entry.project_code, entry.started_at && `${dateLabel(entry.started_at)}${entry.ended_at ? ` - ${dateLabel(entry.ended_at)}` : ""}`].filter(Boolean).join(" · ")}
        </p>
      </div>
      {entry.can_review && !mine && <Button size="sm" variant="secondary" onClick={onReview}><MessageSquarePlus size={15}/> Leave feedback</Button>}
    </div>
    {reviews.length > 0
      ? <ul className="mt-3 grid gap-2" aria-label={`Feedback on ${entry.project_name}`}>
          {reviews.map(item => <FeedbackItem key={item.id} item={item}
            canEdit={item.author_user_id === user?.id} canDelete={item.author_user_id === user?.id || isAdmin}
            onEdit={() => onEditReview(item)} onDelete={() => onDeleteReview(item)}/>)}
        </ul>
      : <p className="mt-2 text-xs text-slate-400">{entry.can_review ? "No feedback yet. Be the first to review." : "No feedback yet."}</p>}
  </article>;
}

export function VendorWorkHistory({ user, vendorName = "This vendor", pastProjects = [], projectHistory = [], feedback = [], categories = [], saving = false, savePastProject, deletePastProject, saveFeedback, deleteFeedback }) {
  const [editing, setEditing] = useState(null); // null | "new" | entry
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [deleteError, setDeleteError] = useState("");
  const [reviewing, setReviewing] = useState(null); // { entry, item? }
  const [removingReview, setRemovingReview] = useState(null);
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

  async function submitReview(payload) {
    const result = await saveFeedback(reviewing.entry.project_id, reviewing.item?.id || null, payload);
    if (result?.ok) setReviewing(null);
    return result;
  }

  async function confirmReviewRemoval() {
    const result = await deleteFeedback(removingReview.id);
    if (result?.ok) setRemovingReview(null);
  }

  const reviewsFor = projectId => feedback.filter(item => item.project_id === projectId);
  const counts = [
    projectHistory.length && `${projectHistory.length} in SiteOps`,
    pastProjects.length && `${pastProjects.length} before SiteOps`,
  ].filter(Boolean).join(", ");

  return <section className="grid gap-4" aria-label="Work history">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 className="text-[15px] font-medium text-slate-950">Work history</h3>
        <p className="mt-0.5 text-[13px] text-slate-500">{counts || "Projects this vendor has worked on, and how they did."}</p>
      </div>
      {canAdd && <Button size="sm" variant="secondary" onClick={() => setEditing("new")}><Plus size={15}/> Add past project</Button>}
    </header>

    {projectHistory.length > 0 && <div className="grid gap-2">
      <h4 className="text-xs text-slate-500">In SiteOps</h4>
      {projectHistory.map(entry => <SiteOpsProject key={entry.id} entry={entry} reviews={reviewsFor(entry.project_id)} user={user}
        onReview={() => setReviewing({ entry })} onEditReview={item => setReviewing({ entry, item })} onDeleteReview={setRemovingReview}/>)}
    </div>}

    {pastProjects.length > 0 && <div className="grid gap-2">
      <h4 className="text-xs text-slate-500">Before SiteOps</h4>
      {pastProjects.map(entry => <PastProjectCard key={entry.id} entry={entry} canEdit={canEditWorkHistory(user, entry)} onEdit={() => setEditing(entry)} onDelete={() => { setDeleteError(""); setConfirmDelete(entry); }}/>)}
    </div>}

    {!projectHistory.length && !pastProjects.length && <div className="grid place-items-center rounded-2xl border border-dashed border-slate-300 p-8 text-center">
      <History className="text-slate-300" aria-hidden="true"/>
      <h4 className="mt-3 text-sm text-slate-950">No work history yet</h4>
      <p className="mx-auto mt-1 max-w-sm text-sm leading-6 text-slate-500">Finished SiteOps projects appear here automatically. {canAdd ? "You can also add work they did before SiteOps." : ""}</p>
    </div>}

    {editing && <PastProjectForm entry={editing === "new" ? null : editing} categories={categories} saving={saving} onClose={() => setEditing(null)} onSubmit={submit}/>}
    {confirmDelete && <ConfirmModal
      title={`Remove ${confirmDelete.project_name}?`}
      message={deleteError || "This removes the project from the vendor's work history. It cannot be undone."}
      confirmLabel={saving ? "Removing..." : "Remove"}
      confirmDisabled={saving}
      onClose={() => { setConfirmDelete(null); setDeleteError(""); }}
      onConfirm={confirmRemoval}/>}
    {reviewing && <FeedbackForm vendorName={vendorName} projectName={reviewing.entry.project_name} entry={reviewing.item} saving={saving}
      onClose={() => setReviewing(null)} onSubmit={submitReview}/>}
    {removingReview && <ConfirmModal
      title="Delete this feedback?"
      message={`${removingReview.author_name}'s feedback on ${removingReview.project_name || "this project"} will be removed for everyone.`}
      confirmLabel="Delete feedback" confirmDisabled={saving}
      onClose={() => setRemovingReview(null)} onConfirm={confirmReviewRemoval}/>}
  </section>;
}
