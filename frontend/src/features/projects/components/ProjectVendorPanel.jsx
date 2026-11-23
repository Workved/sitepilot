import { Building2, ChevronDown, Pencil, Plus, RotateCcw, Truck, UserMinus } from "lucide-react";
import { PaneHeader, PaneLoading } from "./PaneKit";
import { useEffect, useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { Button, EmptyState, Field, Pill, Select, Textarea } from "../../../components/ui";
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
    return <div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-slate-500">Trade phases</span>
        {canManage && <button type="button" className="inline-flex items-center gap-1 text-xs text-blue-700 hover:text-blue-900" onClick={() => setEditing(true)}><Pencil size={12}/> Edit</button>}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {vendor.capability_categories.length
          ? vendor.capability_categories.map(name => <span key={name} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{name}</span>)
          : <span className="rounded-md bg-orange-50 px-2 py-1 text-xs text-orange-800">No trade phase set - cannot be delegated to any task</span>}
      </div>
    </div>;
  }

  return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
    <span className="block text-xs text-slate-600">Select the trade phases this vendor covers</span>
    <div className="mt-2 flex flex-wrap gap-2">
      {categories.map(category => {
        const checked = selectedIds.has(category.id);
        return <label key={category.id} className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${checked ? "border-slate-950 bg-white text-slate-950" : "border-slate-200 bg-white text-slate-600"}`}>
          <input type="checkbox" className="size-3.5" checked={checked} onChange={() => toggle(category.id)}/>
          {category.name}
        </label>;
      })}
    </div>
    {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
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
    return <button type="button" className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-rose-50 hover:text-rose-700" onClick={() => setConfirming(true)}><UserMinus size={13}/> Remove</button>;
  }

  return <div className="mt-3 rounded-xl border border-rose-100 bg-rose-50 p-3">
    <span className="block text-sm text-rose-900">Remove {vendor.name} from this project?</span>
    <p className="mt-1 text-xs text-rose-700">Their active task assignments on this project will also be ended. History (acknowledgements, evidence) is kept.</p>
    <Textarea className="mt-2 min-h-16" value={reason} onChange={event => setReason(event.target.value)} placeholder="Reason for removal (required)"/>
    {error && <p className="mt-1 text-xs text-rose-700">{error}</p>}
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

  if (loading) return <PaneLoading label="Loading project vendors..."/>;

  const missingTrade = activeMappings.filter(mapping => !vendorById.get(mapping.vendor_id)?.capability_categories?.length).length;

  return <div className="grid gap-5">
    <PaneHeader
      title="Vendors"
      description="Vendors mapped here can be delegated a task from the execution board."
      meta={<>
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{activeMappings.length} active</span>
        {missingTrade > 0 && <span className="rounded-md bg-orange-50 px-2 py-0.5 text-xs text-orange-800">{missingTrade} without a trade phase</span>}
      </>}
    />

    {canManage && <form className="flex flex-col gap-2 rounded-2xl border border-line bg-white p-3 sm:flex-row sm:items-end" onSubmit={map}>
      <Field label="Vendor" className="min-w-0 flex-1 text-[13px]">
        <Select value={vendorId} onChange={event => setVendorId(event.target.value)} required>
          <option value="">{candidates.length ? "Select vendor" : "No unmapped active vendors"}</option>
          {candidates.map(candidate => <option key={candidate.id} value={candidate.id} disabled={!candidate.parentMapped}>
            {candidate.name}, {engagementLabel[candidate.engagement_type] || candidate.engagement_type}{candidate.capability_categories.length ? ` (${candidate.capability_categories.join(", ")})` : ""}{!candidate.parentMapped ? " - parent not mapped" : ""}
          </option>)}
        </Select>
      </Field>
      <Button type="submit" loading={submitting} disabled={!vendorId}><Plus size={16}/> Map vendor</Button>
    </form>}

    {error && <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error} <Button variant="secondary" size="sm" onClick={load}><RotateCcw size={15}/> Retry</Button></div>}

    {activeMappings.length === 0
      ? <EmptyState icon={<Truck size={20}/>} title="No vendors mapped yet" description={canManage ? "Pick a vendor above to make it available for task delegation." : "A project manager maps vendors to this project."}/>
      : <div className="grid gap-3 2xl:grid-cols-2">{activeMappings.map(mapping => {
        const vendor = vendorById.get(mapping.vendor_id);
        return <article key={mapping.id} className="rounded-[20px] border border-line bg-white">
          <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
            <div className="flex min-w-0 items-center gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-700"><Building2 size={18}/></span>
              <div className="min-w-0">
                <strong className="block truncate text-[15px] font-medium text-slate-950">{mapping.vendor_name}</strong>
                <span className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>{engagementLabel[mapping.engagement_type] || mapping.engagement_type}</span>
                  <time>Added {new Date(mapping.created_at).toLocaleDateString("en-GB")}</time>
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1"><Pill tone="green">Active</Pill>{canManage && vendor && <RemoveVendorControl project={project} vendor={vendor} onChanged={load}/>}</div>
          </div>
          <div className="grid gap-4 px-5 pb-4 pt-4">
            {vendor && <VendorTradePhaseEditor vendor={vendor} categories={categories} canManage={canManage} onChanged={load}/>}
            <VendorProjectPeople project={project} mapping={mapping} vendor={vendor} categories={categories} canManage={canManagePeople} onChanged={load}/>
          </div>
        </article>;
      })}</div>}

    {removedMappings.length > 0 && <details className="group rounded-2xl border border-line bg-white">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm text-slate-700">
        <span>Previously mapped <span className="text-slate-400">{removedMappings.length}</span></span>
        <ChevronDown size={16} className="text-slate-500 transition group-open:rotate-180" aria-hidden="true"/>
      </summary>
      <ul className="grid border-t border-line">
        {removedMappings.map(mapping => <li key={mapping.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5 text-sm last:border-0">
          <span className="flex items-center gap-2"><span className="text-slate-700">{mapping.vendor_name}</span><span className="text-xs text-slate-500">{engagementLabel[mapping.engagement_type] || mapping.engagement_type}</span><Pill tone="red">Removed</Pill></span>
          <time className="text-xs text-slate-500">Removed {new Date(mapping.ends_at).toLocaleDateString("en-GB")}</time>
        </li>)}
      </ul>
    </details>}
  </div>;
}
