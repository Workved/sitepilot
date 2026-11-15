import { Pencil, Truck, UserMinus, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { Button, Field, Pill, Select, Textarea } from "../../../components/ui";
import { ContactLinks, PEOPLE_MANAGER_ROLES } from "../../projects/components/VendorProjectPeople";
import { VendorAcknowledgementForm } from "./VendorAcknowledgementForm";

// A vendor's people as options for a task's point person: those assigned
// to this project first (with their trades), matching the task's phase
// first of all; the primary contact is marked.
export function pointPersonOptions(contacts = [], taskPhase = "") {
  const phase = (taskPhase || "").trim().toLowerCase();
  const rank = contact => {
    const names = (contact.attachments || []).map(a => (a.category_name || "").toLowerCase());
    if (phase && names.includes(phase)) return 0;
    if ((contact.attachments || []).length) return 1;
    return 2;
  };
  return [...contacts].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)).map(contact => {
    const trades = (contact.attachments || []).map(a => a.category_name || "All work");
    const parts = [contact.name, contact.designation, contact.is_primary ? "primary" : null].filter(Boolean);
    return { id: contact.id, label: `${parts.join(" · ")}${trades.length ? ` - on this project (${trades.join(", ")})` : ""}` };
  });
}

// Shows a task's point person (with call/WhatsApp) and lets an Admin, or a
// PM/Supervisor, change it. Messages go to this person and the primary contact.
function PointPerson({ projectId, task, assignment, contacts, canChange, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [contactId, setContactId] = useState(assignment.contact_id || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true);
    setError("");
    try {
      await vendorAssignmentApi.setTaskPointPerson(projectId, task.id, assignment.id, contactId || null);
      setEditing(false);
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "The point person could not be changed.");
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return <div className="mt-2 grid gap-2 rounded-lg border border-blue-200 bg-blue-50/60 p-2">
      <Select aria-label="Point person" value={contactId} onChange={event => setContactId(event.target.value)}>
        <option value="">Primary contact only</option>
        {pointPersonOptions(contacts, task.phase).map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
      </Select>
      {error && <p className="text-xs font-bold text-rose-700">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" loading={saving} onClick={save}>Save</Button>
        <Button size="sm" variant="secondary" disabled={saving} onClick={() => { setEditing(false); setContactId(assignment.contact_id || ""); setError(""); }}>Cancel</Button>
      </div>
    </div>;
  }

  return <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
    <span className="flex items-center gap-1 font-bold text-slate-500"><UserRound size={12}/> Point person:</span>
    {assignment.contact_id
      ? <><strong className="text-slate-900">{assignment.contact_name}</strong><ContactLinks name={assignment.contact_name} phone={assignment.contact_phone} whatsapp={assignment.contact_whatsapp}/></>
      : <span className="text-slate-500">primary contact</span>}
    {canChange && !assignment.ends_at && <button type="button" onClick={() => setEditing(true)} className="inline-flex items-center gap-1 font-bold text-blue-700 hover:underline"><Pencil size={11}/> Change</button>}
  </div>;
}

const STATUS_TONE = { pending_ack: "orange", acknowledged: "green", declined: "red" };

// Unassign a vendor from this one task (soft removal - ends_at on the
// TaskVendorAssignment). The vendor stays mapped to the project.
function UnassignVendorControl({ projectId, task, assignment, onChanged }) {
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function unassign() {
    setSubmitting(true);
    setError("");
    try {
      await vendorAssignmentApi.unassignTask(projectId, task.id, assignment.id, { reason: reason.trim() });
      setConfirming(false);
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This vendor could not be unassigned from the task.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!confirming) {
    return <button type="button" className="inline-flex items-center gap-1 text-xs font-bold text-rose-700 hover:underline" onClick={() => setConfirming(true)}><UserMinus size={12}/> Unassign</button>;
  }

  return <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50/60 p-2">
    <Textarea className="min-h-14" value={reason} onChange={event => setReason(event.target.value)} placeholder="Reason for unassigning (required)"/>
    {error && <p className="mt-1 text-xs font-bold text-rose-700">{error}</p>}
    <div className="mt-2 flex gap-2">
      <Button size="sm" variant="danger" loading={submitting} disabled={reason.trim().length < 4} onClick={unassign}>Confirm</Button>
      <Button size="sm" variant="secondary" disabled={submitting} onClick={() => { setConfirming(false); setReason(""); setError(""); }}>Cancel</Button>
    </div>
  </div>;
}

// U2/U3: delegate a mapped vendor to this task (R3), then track its
// acknowledgement/activity history alongside it. Delegation never touches
// Task.lifecycle_status or Phase 1's accountable-Supervisor derivation - a
// vendor assignment is purely additive information for this task.
export function TaskVendorDelegationForm({ projectId, task, user, onChanged }) {
  const [mappedVendors, setMappedVendors] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [vendorId, setVendorId] = useState("");
  const [contactId, setContactId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const canManage = ["admin", "super_admin", "project_manager"].includes(user?.role);
  const canChangePointPerson = PEOPLE_MANAGER_ROLES.includes(user?.role);
  const contactsByVendor = new Map(mappedVendors.map(v => [v.vendor_id, v.contacts || []]));

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [vendors, taskAssignments] = await Promise.all([
        vendorAssignmentApi.listProjectVendors(projectId),
        vendorAssignmentApi.listTaskVendorAssignments(projectId, task.id),
      ]);
      setMappedVendors(vendors);
      setAssignments(taskAssignments);
    } catch (caught) {
      setError(caught?.message || "This task's vendor delegation could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId, task.id]);

  async function refresh() {
    await load();
    await onChanged();
  }

  // A vendor with a live (pending_ack/acknowledged, not yet ended) assignment
  // on this task isn't offered again - re-delegation only makes sense after
  // a decline or an unassignment.
  const liveVendorIds = new Set(assignments.filter(a => a.status !== "declined" && !a.ends_at).map(a => a.vendor_id));
  const candidates = mappedVendors.filter(v => !liveVendorIds.has(v.vendor_id));

  async function delegate(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await vendorAssignmentApi.delegateTask(projectId, task.id, { vendor_id: vendorId, contact_id: contactId || null });
      setVendorId("");
      setContactId("");
      await refresh();
    } catch (caught) {
      setError(caught?.message || "This vendor could not be delegated to the task.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">Loading vendor delegation...</div>;

  return <section className="rounded-xl border border-slate-200 bg-white p-4">
    <h4 className="flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-500"><Truck size={14}/> Vendor delegation</h4>

    {error && <p className="mt-2 text-xs font-bold text-rose-700">{error}</p>}

    {assignments.length === 0 ? <p className="mt-2 text-sm text-slate-500">No vendor delegated to this task.</p> : <div className="mt-3 grid gap-3">{assignments.map(assignment => <article key={assignment.id} className={`rounded-lg border border-slate-100 bg-slate-50 p-3 ${assignment.ends_at ? "opacity-70" : ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2"><strong className="text-sm text-slate-900">{assignment.vendor_name}</strong><Pill tone={assignment.ends_at ? "gray" : (STATUS_TONE[assignment.status] || "gray")}>{assignment.ends_at ? "unassigned" : assignment.status.replaceAll("_", " ")}</Pill></div>
        {canManage && !assignment.ends_at && <UnassignVendorControl projectId={projectId} task={task} assignment={assignment} onChanged={refresh}/>}
      </div>
      <PointPerson projectId={projectId} task={task} assignment={assignment} contacts={contactsByVendor.get(assignment.vendor_id)} canChange={canChangePointPerson} onChanged={refresh}/>
      {assignment.ends_at && <p className="mt-1 text-xs text-slate-400">Unassigned {new Date(assignment.ends_at).toLocaleDateString("en-GB")}</p>}
      <VendorAcknowledgementForm projectId={projectId} task={task} assignment={assignment} canManage={canManage} onChanged={refresh}/>
    </article>)}</div>}

    {canManage && <form className="mt-3 grid gap-2 border-t border-slate-100 pt-3 sm:grid-cols-[1fr_auto]" onSubmit={delegate}>
      <Field label="Delegate a mapped vendor">
        <Select value={vendorId} onChange={event => { setVendorId(event.target.value); setContactId(""); }} required>
          <option value="">{candidates.length ? "Select vendor" : "No mapped vendors available"}</option>
          {candidates.map(candidate => <option key={candidate.vendor_id} value={candidate.vendor_id}>{candidate.vendor_name}</option>)}
        </Select>
      </Field>
      {vendorId && (contactsByVendor.get(vendorId) || []).length > 0 && <Field label="Point person (optional)" className="sm:col-start-1">
        <Select value={contactId} onChange={event => setContactId(event.target.value)}>
          <option value="">Primary contact only</option>
          {pointPersonOptions(contactsByVendor.get(vendorId), task.phase).map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </Select>
      </Field>}
      <div className="flex items-end sm:col-start-2 sm:row-start-1"><Button type="submit" size="sm" loading={submitting} disabled={!vendorId}>Delegate</Button></div>
    </form>}
  </section>;
}
