import { AlertTriangle, Clock3, X } from "lucide-react";
import { useEffect, useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { Button, Field, Input, Pill, Select, Textarea } from "../../../components/ui";

const DELAY_RESPONSIBILITY_OPTIONS = [
  ["vendor", "Vendor"], ["client", "Client"], ["approval", "Approval"],
  ["design", "Design"], ["site_readiness", "Site readiness"], ["internal", "Internal"], ["other", "Other"],
];

function BlockerRow({ projectId, task, blocker, onChanged, canResolve }) {
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState("");

  async function resolve() {
    setResolving(true);
    setError("");
    try {
      await taskExecutionApi.resolveBlocker(projectId, task.id, blocker.id);
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This blocker could not be resolved.");
    } finally {
      setResolving(false);
    }
  }

  return <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="flex items-center gap-2"><strong className="capitalize text-slate-800">{blocker.type}</strong><Pill tone={blocker.resolved_at ? "green" : "orange"}>{blocker.resolved_at ? "Resolved" : "Open"}</Pill></span>
      {!blocker.resolved_at && canResolve && <Button size="sm" variant="secondary" loading={resolving} onClick={resolve}>Resolve</Button>}
    </div>
    <p className="mt-0.5 text-slate-600">{blocker.description}</p>
    {error && <p className="mt-1 text-xs font-bold text-rose-700">{error}</p>}
  </div>;
}

function BlockerForm({ projectId, task, onDone, onChanged }) {
  const [type, setType] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await taskExecutionApi.logBlocker(projectId, task.id, { type: type.trim(), description: description.trim() });
      await onChanged();
      onDone();
    } catch (caught) {
      setError(caught?.message || "This blocker could not be logged.");
    } finally {
      setSubmitting(false);
    }
  }

  return <form className="mt-2 grid gap-2 rounded-lg border border-orange-200 bg-orange-50/60 p-3 sm:grid-cols-[160px_1fr_auto]" onSubmit={submit}>
    <Field label="Type"><Input value={type} onChange={event => setType(event.target.value)} placeholder="e.g. material" required/></Field>
    <Field label="Description"><Input value={description} onChange={event => setDescription(event.target.value)} placeholder="Describe the blocker" required/></Field>
    <div className="flex items-end gap-2">
      <Button type="submit" size="sm" loading={submitting} disabled={!type.trim() || !description.trim()}>Log blocker</Button>
      <Button type="button" size="sm" variant="ghost" disabled={submitting} onClick={onDone}>Cancel</Button>
    </div>
    {error && <p className="text-xs font-bold text-rose-700 sm:col-span-3">{error}</p>}
  </form>;
}

function DelayForm({ projectId, task, onDone, onChanged }) {
  const [responsibilityType, setResponsibilityType] = useState("vendor");
  const [vendorId, setVendorId] = useState("");
  const [vendors, setVendors] = useState([]);
  const [vendorsLoading, setVendorsLoading] = useState(true);
  const [reason, setReason] = useState("");
  const [impactDays, setImpactDays] = useState("1");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Vendors mapped to THIS project only - mirrors TaskVendorDelegationForm's
  // own picker, so "who caused this delay" only ever offers a vendor that
  // could plausibly be responsible for work on this project.
  useEffect(() => {
    let active = true;
    setVendorsLoading(true);
    vendorAssignmentApi.listProjectVendors(projectId)
      .then(list => { if (active) setVendors(list); })
      .catch(() => { if (active) setVendors([]); })
      .finally(() => { if (active) setVendorsLoading(false); });
    return () => { active = false; };
  }, [projectId]);

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await taskExecutionApi.logDelay(projectId, task.id, {
        responsibility_type: responsibilityType,
        responsible_vendor_id: responsibilityType === "vendor" ? vendorId : null,
        reason: reason.trim(),
        impact_days: Number(impactDays),
      });
      await onChanged();
      onDone();
    } catch (caught) {
      setError(caught?.message || "This delay could not be logged.");
    } finally {
      setSubmitting(false);
    }
  }

  return <form className="mt-2 grid gap-2 rounded-lg border border-slate-200 bg-slate-50/60 p-3 sm:grid-cols-2" onSubmit={submit}>
    <Field label="Responsibility"><Select value={responsibilityType} onChange={event => setResponsibilityType(event.target.value)}>{DELAY_RESPONSIBILITY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select></Field>
    <Field label="Impact (days)"><Input type="number" min="1" value={impactDays} onChange={event => setImpactDays(event.target.value)} required/></Field>
    {responsibilityType === "vendor" && <Field
      label="Vendor" className="sm:col-span-2"
      hint={!vendorsLoading && vendors.length === 0 ? "No vendors are mapped to this project yet - map one from the Vendor Hub first." : null}
    >
      <Select value={vendorId} onChange={event => setVendorId(event.target.value)} disabled={vendorsLoading || vendors.length === 0} required>
        <option value="">{vendorsLoading ? "Loading vendors..." : vendors.length ? "Select vendor" : "No vendors mapped to this project"}</option>
        {vendors.map(vendor => <option key={vendor.vendor_id} value={vendor.vendor_id}>{vendor.vendor_name}</option>)}
      </Select>
    </Field>}
    <Field label="Reason" className="sm:col-span-2"><Textarea value={reason} onChange={event => setReason(event.target.value)} placeholder="What is causing the delay?" required/></Field>
    <div className="flex gap-2 sm:col-span-2">
      <Button type="submit" size="sm" loading={submitting} disabled={!reason.trim() || (responsibilityType === "vendor" && !vendorId)}>Log delay</Button>
      <Button type="button" size="sm" variant="ghost" disabled={submitting} onClick={onDone}>Cancel</Button>
    </div>
    {error && <p className="text-xs font-bold text-rose-700 sm:col-span-2">{error}</p>}
  </form>;
}

// U5: blocker and delay capture (BR-010). Independent of and combinable
// with lifecycle_status - logging either never changes task status. Both
// forms are collapsed by default behind compact "Report..." actions
// (progressive disclosure); only the selected form opens, and cancelling
// it never touches the task's status.
//
// `autoOpen` ("blocker" | "delay" | undefined): a quick-action button
// elsewhere on the page can drive this open remotely (e.g. TaskDetailDrawer's
// "Report Delay - Blocker" action) instead of the user finding and clicking
// the toggle themselves. Re-applied whenever it changes, not just on mount,
// so a second quick-action click while this panel is already open still
// switches to the requested form.
// `canResolve`: whether this viewer may resolve a blocker - the backend allows
// only the project's Supervisor, PM or an Admin (task_blocker._require_resolver);
// anyone else would only be refused, so the button is not offered.
export function TaskBlockerDelayPanel({ projectId, task, onChanged, autoOpen, canResolve = false }) {
  const [openForm, setOpenForm] = useState(autoOpen || null); // "blocker" | "delay" | null
  useEffect(() => { if (autoOpen) setOpenForm(autoOpen); }, [autoOpen]);
  const openBlockers = task.blockers.filter(b => !b.resolved_at).length;

  return <section className="rounded-[20px] border border-line bg-white p-5">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="text-[15px] font-medium text-slate-950">Blockers &amp; delays</h4>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={openForm === "blocker" ? "primary" : "secondary"} onClick={() => setOpenForm(openForm === "blocker" ? null : "blocker")}>
          {openForm === "blocker" ? <X size={13}/> : <AlertTriangle size={13}/>} Report blocker
        </Button>
        <Button size="sm" variant={openForm === "delay" ? "primary" : "secondary"} onClick={() => setOpenForm(openForm === "delay" ? null : "delay")}>
          {openForm === "delay" ? <X size={13}/> : <Clock3 size={13}/>} Report delay
        </Button>
      </div>
    </div>

    <div className="mt-2 flex flex-wrap items-center gap-3 text-xs font-bold text-slate-500">
      <span>{openBlockers > 0 ? <span className="text-orange-700">{openBlockers} open blocker{openBlockers === 1 ? "" : "s"}</span> : "No open blockers"}</span>
      <span aria-hidden="true">&middot;</span>
      <span>{task.delays.length > 0 ? `${task.delays.length} delay${task.delays.length === 1 ? "" : "s"} logged` : "No delays logged"}</span>
    </div>

    {task.blockers.length > 0 && <div className="mt-2 grid gap-1.5">{task.blockers.map(blocker => <BlockerRow key={blocker.id} projectId={projectId} task={task} blocker={blocker} onChanged={onChanged} canResolve={canResolve}/>)}</div>}
    {openForm === "blocker" && <BlockerForm projectId={projectId} task={task} onChanged={onChanged} onDone={() => setOpenForm(null)}/>}

    {task.delays.length > 0 && <div className="mt-2 grid gap-1.5">{task.delays.map(delay => <div key={delay.id} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><strong className="capitalize text-slate-800">{delay.responsibility_type.replaceAll("_", " ")}</strong><span className="text-xs font-bold text-slate-500">{delay.impact_days} day{delay.impact_days === 1 ? "" : "s"}</span></div><p className="mt-0.5 text-slate-600">{delay.reason}</p></div>)}</div>}
    {openForm === "delay" && <DelayForm projectId={projectId} task={task} onChanged={onChanged} onDone={() => setOpenForm(null)}/>}
  </section>;
}
