import { Check, Plus, RotateCcw, ShieldCheck, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, EmptyState, Field, Modal, Pill, Textarea } from "../../../components/ui";
import { GateApplicabilityControls } from "./GateApplicabilityDecisionModal";
import { ProjectManualGateModal } from "./ProjectManualGateModal";
import { isOrgAdmin } from "../../../utils/constants";
import { PaneHeader, PaneLoading } from "./PaneKit";

const mappingLabel = { exact: "Exact", broad_text: "Broad text", unmapped: "Unmapped" };

export function ProjectExternalGates({ project, user }) {
  const [data, setData] = useState({ total: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [bulkNotApplicable, setBulkNotApplicable] = useState(false);
  const [bulkReason, setBulkReason] = useState("");
  const requestRef = useRef(false);
  const canGenerate = ["admin", "super_admin"].includes(user.role) && project.status === "draft";
  // Admin decides whether an approval applies; the assigned PM reads it.
  //
  // Draft OR active, mirroring ProjectGateApplicabilityService. Applicability
  // used to be draft-only here and on the backend, while activation never
  // required the gates to have been reviewed - so a project could go live
  // with every gate undecided and then nobody could ever decide them, and
  // since only an APPLICABLE gate becomes a runtime approval, that project
  // could never hold an external approval at all.
  const canDecide = isOrgAdmin(user) && ["draft", "active"].includes(project.status);
  // NOT the same rule: adding a brand-new approval is still draft-only on the
  // backend (`ProjectManualGateService`), so offering it on an active project
  // would render a control that 409s on click.
  const canAddManual = isOrgAdmin(user) && project.status === "draft";

  async function load() {
    setLoading(true); setError("");
    try { setData(await projectsApi.externalGates(project.id)); }
    catch (caught) { setError(caught?.message || "Unable to load project gates."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [project.id]);

  async function generate() {
    if (!canGenerate || !confirmed || busy || requestRef.current) return;
    requestRef.current = true; setBusy(true); setError("");
    try { await projectsApi.generateGates(project.id); setConfirmed(false); await load(); }
    catch (caught) { setError(caught?.message || "Unable to generate project gates."); }
    finally { requestRef.current = false; setBusy(false); }
  }

  function toggleSelected(gateId) {
    setSelected(previous => {
      const next = new Set(previous);
      if (next.has(gateId)) next.delete(gateId); else next.add(gateId);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected(previous => previous.size === data.items.length ? new Set() : new Set(data.items.map(gate => gate.id)));
  }

  // Applying the same decision a gate already carries would just append a
  // redundant history entry, so bulk actions skip gates already at the
  // target state instead of re-deciding them.
  async function applyBulkDecision(decision, reason) {
    const targets = data.items.filter(gate => selected.has(gate.id) && gate.applicability_state !== decision);
    if (targets.length === 0) { setSelected(new Set()); setBulkNotApplicable(false); return; }
    setBulkBusy(true); setBulkError("");
    try {
      const results = await Promise.allSettled(
        targets.map(gate => projectsApi.decideGateApplicability(project.id, gate.id, { decision, reason: reason || null })),
      );
      const failed = results.filter(result => result.status === "rejected");
      if (failed.length > 0) {
        setBulkError(`${failed.length} of ${targets.length} gates could not be updated. ${failed[0].reason?.message || ""}`.trim());
      } else {
        setSelected(new Set());
        setBulkNotApplicable(false);
        setBulkReason("");
      }
      await load();
    } finally {
      setBulkBusy(false);
    }
  }

  const stateCount = state => data.items.filter(gate => (gate.applicability_state || "pending_review") === state).length;
  const pendingReview = stateCount("pending_review");

  return <div className="grid gap-5">
    <PaneHeader
      title="External gates"
      description="Approvals from outside parties (client, landlord, authorities) that work depends on, copied from the published template."
      meta={!loading && data.total > 0 && <>
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{data.total} gates</span>
        {stateCount("applicable") > 0 && <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800">{stateCount("applicable")} applicable</span>}
        {pendingReview > 0 && <span className="rounded-md bg-orange-50 px-2 py-0.5 text-xs text-orange-800">{pendingReview} to review</span>}
        {stateCount("not_applicable") > 0 && <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{stateCount("not_applicable")} not applicable</span>}
      </>}
      actions={canAddManual && !showManual && <Button variant="secondary" onClick={() => setShowManual(true)}><Plus size={15}/> Add manual approval</Button>}
    />
    {error && <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}<Button variant="secondary" size="sm" onClick={load}><RotateCcw size={15}/> Retry</Button></div>}
    {loading ? <PaneLoading label="Loading external gates..."/> : data.total === 0 ? <>
      <EmptyState icon={<ShieldCheck size={20}/>} title="No project gates generated" description="Generate the project-owned gate snapshot after project tasks exist."/>
      {canGenerate && <section className="rounded-[20px] border border-line bg-white p-5"><label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5 size-4 accent-slate-950"/><span>I confirm the selected published template is correct. Gates will remain pending review and the project will remain Draft.</span></label><Button className="mt-4 w-full sm:w-auto" disabled={!confirmed || busy} loading={busy} onClick={generate}>Generate gates</Button></section>}
    </> : <section className="overflow-hidden rounded-[20px] border border-line bg-white">
      {canDecide && <div className="flex flex-wrap items-center gap-3 border-b border-line bg-slate-50 px-4 py-3">
        <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" className="size-4 accent-slate-950" checked={selected.size > 0 && selected.size === data.items.length} onChange={toggleSelectAll}/>Select all</label>
        <span className="text-xs text-slate-500">{selected.size} selected</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" disabled={selected.size === 0 || bulkBusy} loading={bulkBusy && !bulkNotApplicable} onClick={() => applyBulkDecision("applicable")}><Check size={14}/> Mark selected Applicable</Button>
          <Button size="sm" variant="danger" disabled={selected.size === 0 || bulkBusy} onClick={() => setBulkNotApplicable(true)}><X size={14}/> Mark selected Not Applicable</Button>
        </div>
        {bulkError && <div role="alert" className="w-full rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-sm text-rose-800">{bulkError}</div>}
      </div>}
      <ol className="divide-y divide-slate-100">{data.items.map(gate => {
        const state = gate.applicability_state || "pending_review";
        return <li key={gate.id} className={`grid gap-4 px-4 py-4 sm:px-5 lg:grid-cols-[minmax(0,1fr)_auto] ${selected.has(gate.id) ? "bg-blue-50/40" : ""}`}>
          <div className="flex min-w-0 items-start gap-3">
            {canDecide && <input type="checkbox" className="mt-1 size-4 shrink-0 accent-slate-950" checked={selected.has(gate.id)} onChange={() => toggleSelected(gate.id)} aria-label={`Select ${gate.code}`}/>}
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs tabular-nums text-slate-700">{gate.code}</span>
                <h4 className="text-[15px] text-slate-950">{gate.approval_name}</h4>
                <Pill tone={state === "applicable" ? "green" : state === "not_applicable" ? "gray" : "orange"}>{state.replaceAll("_", " ")}</Pill>
                {gate.blocking && <Pill tone="red">Blocking</Pill>}
              </div>
              {gate.description && <p className="mt-1 text-[13px] leading-5 text-slate-600">{gate.description}</p>}
              <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs">
                <div className="flex gap-1.5"><dt className="text-slate-500">Source</dt><dd className="text-slate-800">{gate.source === "project_manual" ? "Manual" : "Template"}</dd></div>
                <div className="flex gap-1.5"><dt className="text-slate-500">PM owner</dt><dd className="text-slate-800">{gate.accountable_pm_name}</dd></div>
                <div className="flex gap-1.5"><dt className="text-slate-500">Mapping</dt><dd className="text-slate-800">{gate.mapping_classification === "exact" ? `${gate.exact_task_count} task links` : gate.broad_mapping_text || "Configuration required"} <span className="text-slate-500">({mappingLabel[gate.mapping_classification]})</span></dd></div>
                <div className="flex gap-1.5"><dt className="text-slate-500">Status</dt><dd className="text-slate-800">{gate.status.replaceAll("_", " ")}</dd></div>
              </dl>
            </div>
          </div>
          <div className="lg:min-w-[16rem]"><GateApplicabilityControls projectId={project.id} gate={gate} canDecide={canDecide} onDecided={load}/></div>
        </li>;
      })}</ol>
      <p className="flex items-center gap-2 border-t border-line bg-slate-50 px-4 py-2.5 text-xs text-slate-500"><Check size={14} className="text-emerald-600"/>{data.total} gates generated. Retry is idempotent and creates no duplicates.</p>
    </section>}
    {showManual && <ProjectManualGateModal projectId={project.id} onClose={() => setShowManual(false)} onCreated={load}/>}
    {bulkNotApplicable && <Modal title="Mark selected gates Not Applicable" subtitle={`${selected.size} gate${selected.size === 1 ? "" : "s"} selected`} onClose={() => { if (!bulkBusy) { setBulkNotApplicable(false); setBulkReason(""); } }} className="sm:max-w-xl">
      <div className="grid gap-5">
        <div className="rounded-2xl border border-rose-100 bg-rose-50 p-4"><p className="text-sm text-rose-950">Each selected gate will be retained but excluded from the project requirement set.</p><p className="mt-1 text-xs leading-5 text-slate-600">The same reason is recorded against every selected gate, append-only in each gate's own history.</p></div>
        <Field label="Reason (required)" htmlFor="bulk-gate-decision-reason">
          <Textarea id="bulk-gate-decision-reason" value={bulkReason} onChange={event => setBulkReason(event.target.value)} maxLength={2000} placeholder="Explain why these gates do not apply"/>
        </Field>
        {bulkError && <div role="alert" className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{bulkError}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button variant="secondary" disabled={bulkBusy} onClick={() => { setBulkNotApplicable(false); setBulkReason(""); }}>Cancel</Button>
          <Button variant="danger" loading={bulkBusy} disabled={!bulkReason.trim()} onClick={() => applyBulkDecision("not_applicable", bulkReason.trim())}>Confirm Not Applicable</Button>
        </div>
      </div>
    </Modal>}
  </div>;
}
