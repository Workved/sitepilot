import { Check, EyeOff, Pencil, Plus, Trash2, Undo2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { LoadingSpinner, Modal } from "../../../components/ui";

// Only Super Admin and Admin manage vendor categories (mirrors the backend's
// CATEGORY_ADMIN_ROLES). A category is also a template phase, so the list is
// shared with the template task form.
export const canManageCategories = user => ["super_admin", "admin"].includes(user?.role);

function CategoryRow({ category, busy, onRename, onRemove, onShow }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const used = category.vendor_count || 0;

  if (editing) {
    return <li className="flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50/40 p-2">
      <input aria-label={`New name for ${category.name}`} autoFocus value={name} maxLength={80} onChange={event => setName(event.target.value)}
        onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); onRename(category, name).then(ok => ok && setEditing(false)); } if (event.key === "Escape") setEditing(false); }}
        className="min-h-10 flex-1 rounded-lg border border-slate-200 px-3 text-sm font-semibold outline-none focus:border-blue-600"/>
      <button type="button" aria-label="Save name" disabled={busy || !name.trim()} onClick={() => onRename(category, name).then(ok => ok && setEditing(false))} className="grid size-10 place-items-center rounded-lg bg-blue-700 text-white disabled:opacity-50"><Check size={16}/></button>
      <button type="button" aria-label="Cancel rename" onClick={() => { setName(category.name); setEditing(false); }} className="grid size-10 place-items-center rounded-lg border border-slate-200 text-slate-600"><X size={16}/></button>
    </li>;
  }

  return <li className={`flex items-center gap-3 rounded-xl border p-3 ${category.active ? "border-slate-200 bg-white" : "border-dashed border-slate-200 bg-slate-50"}`}>
    <div className="min-w-0 flex-1">
      <p className={`truncate text-sm font-black ${category.active ? "text-slate-900" : "text-slate-500"}`}>{category.name}</p>
      <p className="text-xs font-semibold text-slate-500">{used ? `${used} vendor${used === 1 ? "" : "s"}` : "No vendors yet"}{category.active ? "" : " · hidden"}</p>
    </div>
    {category.active
      ? <>
          <button type="button" aria-label={`Rename ${category.name}`} disabled={busy} onClick={() => setEditing(true)} className="grid size-9 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900"><Pencil size={15}/></button>
          <button type="button" aria-label={`Remove ${category.name}`} disabled={busy} onClick={() => onRemove(category)} className="grid size-9 place-items-center rounded-lg text-slate-500 hover:bg-rose-50 hover:text-rose-700">{used ? <EyeOff size={15}/> : <Trash2 size={15}/>}</button>
        </>
      : <button type="button" aria-label={`Show ${category.name} again`} disabled={busy} onClick={() => onShow(category)} className="flex min-h-9 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-black text-slate-700 hover:bg-white"><Undo2 size={14}/> Show again</button>}
  </li>;
}

/**
 * Admin screen to add, rename and remove vendor categories. Removing a
 * category that vendors or tasks use hides it instead (the server decides
 * and says which happened).
 */
export function VendorCategoryManager({ onClose, onChanged }) {
  const [categories, setCategories] = useState(null);
  const [newName, setNewName] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    try {
      setCategories(await vendorAssignmentApi.listCapabilityCategories({ includeHidden: true }));
    } catch (caught) {
      setError(caught?.message || "Categories could not be loaded.");
      setCategories([]);
    }
  }
  useEffect(() => { load(); }, []);

  async function run(work, success) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await work();
      setNotice(typeof success === "function" ? success(result) : success);
      await load();
      onChanged?.();
      return true;
    } catch (caught) {
      setError(caught?.message || "That didn't work.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add(event) {
    event.preventDefault();
    const name = newName.trim();
    if (!name || busy) return;
    if (await run(() => vendorAssignmentApi.addCapabilityCategory(name), result => `"${result.name}" ${result.active ? "is ready to use" : "added"}.`)) setNewName("");
  }

  const rename = (category, name) => run(() => vendorAssignmentApi.updateCapabilityCategory(category.id, { name: name.trim() }), result => `Renamed to "${result.name}".`);
  const show = category => run(() => vendorAssignmentApi.updateCapabilityCategory(category.id, { active: true }), `"${category.name}" is shown again.`);
  const remove = category => {
    const used = category.vendor_count || 0;
    const question = used
      ? `${used} vendor${used === 1 ? " has" : "s have"} "${category.name}". It will be hidden from pickers; those vendors keep it. Continue?`
      : `Remove "${category.name}"? If tasks use it as their phase it will be hidden instead of deleted.`;
    if (!window.confirm(question)) return;
    run(() => vendorAssignmentApi.removeCapabilityCategory(category.id), result => result.message);
  };

  const visible = (categories || []).filter(category => showHidden || category.active);
  const hiddenCount = (categories || []).filter(category => !category.active).length;

  return <Modal className="max-w-2xl" title="Vendor categories" subtitle="Each category is also a phase in the template task form. A vendor can be given a task only when one of its categories matches the task's phase." onClose={onClose}>
    <div className="grid gap-4">
      <form onSubmit={add} className="flex gap-2">
        <input aria-label="New category name" value={newName} maxLength={80} onChange={event => setNewName(event.target.value)} placeholder="e.g. Glass Works"
          className="min-h-11 flex-1 rounded-xl border border-slate-200 px-4 text-sm font-semibold outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-50"/>
        <button type="submit" disabled={busy || !newName.trim()} className="flex min-h-11 items-center gap-2 rounded-xl bg-slate-950 px-4 text-sm font-black text-white hover:bg-slate-800 disabled:opacity-50"><Plus size={16}/> Add</button>
      </form>
      {notice && <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-bold text-emerald-800">{notice}</p>}
      {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</p>}
      {categories === null
        ? <LoadingSpinner label="Loading categories..."/>
        : <ul className="grid max-h-[50vh] gap-2 overflow-y-auto pr-1">{visible.map(category => <CategoryRow key={category.id} category={category} busy={busy} onRename={rename} onRemove={remove} onShow={show}/>)}</ul>}
      {hiddenCount > 0 && <label className="flex items-center gap-2 text-sm font-bold text-slate-600"><input type="checkbox" checked={showHidden} onChange={event => setShowHidden(event.target.checked)}/> Show {hiddenCount} hidden categor{hiddenCount === 1 ? "y" : "ies"}</label>}
      <p className="text-xs font-semibold text-slate-500">A category used as a task's phase can't be renamed (those tasks would stop matching their vendors) - add a new one and hide the old one instead.</p>
    </div>
  </Modal>;
}
