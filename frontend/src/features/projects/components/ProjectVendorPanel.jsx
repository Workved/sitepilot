import { Building2, Pencil, RotateCcw, Truck, UserMinus } from "lucide-react";
import { useEffect, useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { AcknowledgementPill, Button, EmptyState, Field, Pill, Select, Textarea } from "../../../components/ui";
import { PEOPLE_MANAGER_ROLES, VendorProjectPeople } from "./VendorProjectPeople";

const engagementLabel = { main: "Main vendor", sub_vendor: "Sub-vendor" };

// Delegation matches a vendor's TRADE PHASE against a task's phase (see
// TaskVendorAssignmentService._vendor_matches_task_category) - editing here
// is the only way to set that after the one-time legacy import, since the
// legacy Vendor Hub's own "Edit vendor" only touches its own, disconnected
// legacy category list (a different, unrelated classification - see the
// notice on that screen).
function VendorTradePhaseEditor({ vendor, categories, canManage, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set(vendor.capability_category_ids));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { setSelectedIds(new Set(vendor.capability_category_ids)); }, [vendor.capability_category_ids]);

  function toggle(categoryId) {
    setSelectedIds(current => {
      const next = new Set(current);
      if (next.has(categoryId)) next.delete(categoryId); else next.add(categoryId);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      await vendorAssignmentApi.setVendorCapabilities(vendor.id, Array.from(selectedIds));
      setEditing(false);
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This vendor's trade phase could not be updated.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return <div className="mt-2">
      <span className="block text-[10px] font-black uppercase tracking-wide text-slate-400">Trade phase</span>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        {vendor.capability_categories.length
          ? vendor.capability_categories.map(name => <Pill key={name} tone="blue">{name}</Pill>)
          : <span className="text-xs font-bold text-amber-700">No trade phase set - cannot be delegated to any task</span>}
        {canManage && <button type="button" className="ml-1 inline-flex items-center gap-1 text-xs font-bold text-blue-700 hover:underline" onClick={() => setEditing(true)}><Pencil size={12}/> Edit</button>}
      </div>
    </div>;
  }

  return <div className="mt-2 rounded-xl border border-blue-200 bg-blue-50/60 p-3">
    <span className="block text-[10px] font-black uppercase tracking-wide text-blue-800">Select the trade phases this vendor covers</span>
    <div className="mt-2 flex flex-wrap gap-2">
      {categories.map(category => {
        const checked = selectedIds.has(category.id);
        return <label key={category.id} className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-bold ${checked ? "border-blue-400 bg-blue-100 text-blue-800" : "border-slate-200 bg-white text-slate-600"}`}>
          <input type="checkbox" className="size-3.5" checked={checked} onChange={() => toggle(category.id)}/>
          {category.name}
        </label>;
      })}
    </div>
    {error && <p className="mt-2 text-xs font-bold text-rose-700">{error}</p>}
    <div className="mt-3 flex gap-2">
      <Button size="sm" loading={saving} onClick={save}>Save trade phases</Button>
      <Button size="sm" variant="secondary" disabled={saving} onClick={() => { setSelectedIds(new Set(vendor.capability_category_ids)); setEditing(false); }}>Cancel</Button>
    </div>
  </div>;
}

// Remove a vendor from the project (soft removal - ProjectVendor.ends_at).
// Mirrors VendorTradePhaseEditor's reveal-a-small-form-on-click shape.
function RemoveVendorControl({ project, vendor, onChanged }) {
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function remove() {
    setSubmitting(true);
    setError("");
    try {
      await vendorAssignmentApi.removeProjectVendor(project.id, vendor.id, { reason: reason.trim() });
      setConfirming(false);
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This vendor could not be removed from the project.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!confirming) {
    return <button type="button" className="inline-flex items-center gap-1 text-xs font-bold text-rose-700 hover:underline" onClick={() => setConfirming(true)}><UserMinus size={12}/> Remove</button>;
  }

  return <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50/60 p-3">
    <span className="block text-[10px] font-black uppercase tracking-wide text-rose-800">Remove {vendor.name} from this project?</span>
    <p className="mt-1 text-xs text-rose-700">Their active task assignments on this project will also be ended. History (acknowledgements, evidence) is kept.</p>
    <Textarea className="mt-2 min-h-16" value={reason} onChange={event => setReason(event.target.value)} placeholder="Reason for removal (required)"/>
    {error && <p className="mt-1 text-xs font-bold text-rose-700">{error}</p>}
    <div className="mt-2 flex gap-2">
      <Button size="sm" variant="danger" loading={submitting} disabled={reason.trim().length < 4} onClick={remove}>Confirm removal</Button>
      <Button size="sm" variant="secondary" disabled={submitting} onClick={() => { setConfirming(false); setReason(""); setError(""); }}>Cancel</Button>
    </div>
  </div>;
}

// U2: map an active vendor to the project (R2). A sub-vendor additionally
// requires its parent vendor's mapping to already exist on this same
// project - the backend enforces this (422), this panel surfaces which
// candidates satisfy it up front so the PM isn't guessing.
export function ProjectVendorPanel({ project, user }) {
  const [allVendors, setAllVendors] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [vendorId, setVendorId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const canManage = ["admin", "super_admin", "project_manager"].includes(user.role);
  const canManagePeople = PEOPLE_MANAGER_ROLES.includes(user.role);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [vendors, projectMappings, capabilityCategories] = await Promise.all([
        vendorAssignmentApi.listVendors(),
        vendorAssignmentApi.listProjectVendors(project.id, { includeEnded: true }),
        vendorAssignmentApi.listCapabilityCategories(),
      ]);
      setAllVendors(vendors);
      setMappings(projectMappings);
      setCategories(capabilityCategories);
    } catch (caught) {
      setError(caught?.message || "Unable to load project vendors.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [project.id]);

  const vendorById = new Map(allVendors.map(v => [v.id, v]));
  const activeMappings = mappings.filter(m => !m.ends_at);
  const removedMappings = mappings.filter(m => m.ends_at);
  const mappedVendorIds = new Set(activeMappings.map(m => m.vendor_id));
  const candidates = allVendors.filter(v => !mappedVendorIds.has(v.id)).map(v => ({
    ...v,
    parentMapped: v.engagement_type !== "sub_vendor" || mappedVendorIds.has(v.parent_vendor_id),
  }));

  async function map(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await vendorAssignmentApi.mapVendor(project.id, { vendor_id: vendorId });
      setVendorId("");
      await load();
    } catch (caught) {
      setError(caught?.message || "This vendor could not be mapped to the project.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm font-bold text-slate-500">Loading project vendors...</div>;

  return <div className="grid gap-4">
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><Truck size={18}/></span><div><h3 className="font-black text-slate-950">Project vendors</h3><p className="mt-1 text-xs leading-5 text-slate-500">Vendors mapped here can be delegated a task from the execution board.</p></div></div>
    </section>

    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error} <Button variant="secondary" className="ml-2" onClick={load}><RotateCcw size={15}/> Retry</Button></div>}

    {activeMappings.length === 0 ? <EmptyState icon={<Truck size={20}/>} title="No vendors mapped yet" description="Map an active vendor to make it available for task delegation."/> : <div className="grid gap-2">{activeMappings.map(mapping => {
      const vendor = vendorById.get(mapping.vendor_id);
      return <article key={mapping.id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2"><Building2 size={15} className="text-slate-400"/><strong className="text-slate-900">{mapping.vendor_name}</strong><Pill tone="gray">{engagementLabel[mapping.engagement_type] || mapping.engagement_type}</Pill><Pill tone="green">Active</Pill><AcknowledgementPill acknowledgedAt={mapping.acknowledged_at}/></div>
          <div className="flex items-center gap-3"><time className="text-xs text-slate-400">Added {new Date(mapping.created_at).toLocaleDateString("en-GB")}</time>{canManage && vendor && <RemoveVendorControl project={project} vendor={vendor} onChanged={load}/>}</div>
        </div>
        {vendor && <VendorTradePhaseEditor vendor={vendor} categories={categories} canManage={canManage} onChanged={load}/>}
        <VendorProjectPeople project={project} mapping={mapping} vendor={vendor} categories={categories} canManage={canManagePeople} onChanged={load}/>
      </article>;
    })}</div>}

    {removedMappings.length > 0 && <section className="grid gap-2">
      <h4 className="text-xs font-black uppercase tracking-wide text-slate-400">Previously mapped</h4>
      {removedMappings.map(mapping => <article key={mapping.id} className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-sm opacity-80">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2"><Building2 size={15} className="text-slate-400"/><strong className="text-slate-700">{mapping.vendor_name}</strong><Pill tone="gray">{engagementLabel[mapping.engagement_type] || mapping.engagement_type}</Pill><Pill tone="red">Removed</Pill></div>
          <time className="text-xs text-slate-400">Removed {new Date(mapping.ends_at).toLocaleDateString("en-GB")}</time>
        </div>
      </article>)}
    </section>}

    {canManage && <section className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4 sm:p-5">
      <h4 className="text-xs font-black uppercase tracking-wide text-blue-800">Map a vendor</h4>
      <form className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end" onSubmit={map}>
        <Field label="Vendor">
          <Select value={vendorId} onChange={event => setVendorId(event.target.value)} required>
            <option value="">{candidates.length ? "Select vendor" : "No unmapped active vendors"}</option>
            {candidates.map(candidate => <option key={candidate.id} value={candidate.id} disabled={!candidate.parentMapped}>
              {candidate.name} · {engagementLabel[candidate.engagement_type] || candidate.engagement_type}{candidate.capability_categories.length ? ` (${candidate.capability_categories.join(", ")})` : ""}{!candidate.parentMapped ? " - parent not mapped" : ""}
            </option>)}
          </Select>
        </Field>
        <Button type="submit" loading={submitting} disabled={!vendorId}>Map vendor</Button>
      </form>
    </section>}
  </div>;
}
