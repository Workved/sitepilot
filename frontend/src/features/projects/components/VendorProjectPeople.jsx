import { MessageCircle, Phone, Plus, UserRound, X } from "lucide-react";
import { useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { Button, Field, Select } from "../../../components/ui";

// Who may assign a vendor's people to a project (backend also requires a PM
// or Supervisor to be on the project).
export const PEOPLE_MANAGER_ROLES = ["super_admin", "admin", "project_manager", "supervisor"];

export const cleanPhone = (value = "") => value.replace(/[^\d+]/g, "");

export function ContactLinks({ name, phone, whatsapp }) {
  if (!phone && !whatsapp) return null;
  return <span className="inline-flex items-center gap-1">
    {phone && <a href={`tel:${cleanPhone(phone)}`} aria-label={`Call ${name}`} className="grid size-8 place-items-center rounded-lg border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"><Phone size={13}/></a>}
    <a href={`https://wa.me/${cleanPhone(whatsapp || phone).replace("+", "")}`} target="_blank" rel="noreferrer" aria-label={`WhatsApp ${name}`} className="grid size-8 place-items-center rounded-lg border border-emerald-100 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"><MessageCircle size={13}/></a>
  </span>;
}

function AssignPersonForm({ project, contacts, tradeCategories, onDone, onCancel }) {
  const [contactId, setContactId] = useState(contacts[0]?.id || "");
  const [categoryIds, setCategoryIds] = useState(new Set());
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function toggle(id) {
    setCategoryIds(current => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await vendorAssignmentApi.attachContact(project.id, { contact_id: contactId, category_ids: Array.from(categoryIds), note: note.trim() || null });
      await onDone();
    } catch (caught) {
      setError(caught?.message || "This person could not be assigned to the project.");
    } finally {
      setSaving(false);
    }
  }

  return <form onSubmit={save} className="mt-3 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
    <Field label="Person">
      <Select value={contactId} onChange={event => setContactId(event.target.value)} required>
        {contacts.map(contact => <option key={contact.id} value={contact.id}>{contact.name}{contact.designation ? ` · ${contact.designation}` : ""}{contact.is_primary ? " (primary)" : ""}</option>)}
      </Select>
    </Field>
    {tradeCategories.length > 0 && <fieldset>
      <legend className="text-xs text-slate-600">Works on (leave empty for all of this vendor's work)</legend>
      <div className="mt-2 flex flex-wrap gap-2">{tradeCategories.map(category => {
        const checked = categoryIds.has(category.id);
        return <label key={category.id} className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${checked ? "border-slate-950 bg-white text-slate-950" : "border-slate-200 bg-white text-slate-600"}`}>
          <input type="checkbox" className="size-3.5" checked={checked} onChange={() => toggle(category.id)}/>{category.name}
        </label>;
      })}</div>
    </fieldset>}
    <Field label="Note (optional)">
      <input className="min-h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" value={note} onChange={event => setNote(event.target.value)} maxLength={500} placeholder="e.g. Site in-charge, 2nd floor"/>
    </Field>
    {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
    <div className="flex gap-2">
      <Button type="submit" size="sm" loading={saving} disabled={!contactId}>Assign</Button>
      <Button type="button" size="sm" variant="secondary" disabled={saving} onClick={onCancel}>Cancel</Button>
    </div>
  </form>;
}

// The vendor's people on this project: who is assigned (optionally per
// trade), with one-tap call/WhatsApp, and a form to assign more.
export function VendorProjectPeople({ project, mapping, vendor, categories, canManage, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [removingId, setRemovingId] = useState(null);
  const [error, setError] = useState("");
  const contacts = mapping.contacts || [];
  const assigned = contacts.filter(contact => contact.attachments?.length);
  const primary = contacts.find(contact => contact.is_primary);
  const tradeIds = new Set(vendor?.capability_category_ids || []);
  const tradeCategories = categories.filter(category => tradeIds.has(category.id));

  async function remove(attachmentId) {
    setRemovingId(attachmentId);
    setError("");
    try {
      await vendorAssignmentApi.endContactAttachment(project.id, attachmentId);
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This assignment could not be removed.");
    } finally {
      setRemovingId(null);
    }
  }

  return <div className="border-t border-slate-100 pt-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs text-slate-500">People on this project</span>
      {canManage && contacts.length > 0 && !adding && <button type="button" onClick={() => setAdding(true)} className="inline-flex items-center gap-1 text-xs text-blue-700 hover:text-blue-900"><Plus size={12}/> Assign person</button>}
    </div>
    {assigned.length === 0
      ? <p className="mt-1.5 text-[13px] text-slate-500">{contacts.length === 0 ? "This vendor has no contacts yet. Add them in Vendor Hub." : `No one assigned yet. Task messages go to the primary contact${primary ? ` (${primary.name})` : ""}.`}</p>
      : <ul className="mt-2 grid gap-2">{assigned.map(contact => <li key={contact.id} className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-line bg-slate-50 px-3 py-2.5">
          <div className="min-w-0">
            <span className="flex items-center gap-1.5 text-sm text-slate-950"><UserRound size={14} className="text-slate-400"/>{contact.name}{contact.designation && <span className="text-slate-500">{contact.designation}</span>}</span>
            <div className="mt-1 flex flex-wrap gap-1.5">{contact.attachments.map(attachment => <span key={attachment.id} className="inline-flex items-center gap-1 rounded-md bg-white px-2 py-0.5 text-xs text-slate-700 ring-1 ring-slate-200">
              {attachment.category_name || "All work"}
              {canManage && <button type="button" aria-label={`Remove ${contact.name} from ${attachment.category_name || "all work"}`} disabled={removingId === attachment.id} onClick={() => remove(attachment.id)} className="text-slate-400 hover:text-rose-700 disabled:opacity-50"><X size={12}/></button>}
            </span>)}</div>
            {contact.attachments.find(attachment => attachment.note)?.note && <p className="mt-1 text-xs text-slate-500">{contact.attachments.find(attachment => attachment.note).note}</p>}
          </div>
          <ContactLinks name={contact.name} phone={contact.phone} whatsapp={contact.whatsapp}/>
        </li>)}</ul>}
    {error && <p role="alert" className="mt-1 text-xs text-rose-700">{error}</p>}
    {adding && <AssignPersonForm project={project} contacts={contacts} tradeCategories={tradeCategories} onCancel={() => setAdding(false)} onDone={async () => { setAdding(false); await onChanged(); }}/>}
  </div>;
}
