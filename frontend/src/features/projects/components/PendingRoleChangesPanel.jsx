import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, Input, LoadingSpinner, Pill } from "../../../components/ui";

const ROLE_LABEL = { project_manager: "Project Manager", site_supervisor: "Site Supervisor" };

function RejectControl({ projectId, change, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function reject() {
    if (reason.trim().length < 4) return;
    setBusy(true);
    setError("");
    try {
      await projectsApi.rejectRoleChange(projectId, change.id, reason.trim());
      await onDone();
    } catch (caught) {
      setError(caught?.message || "This request could not be rejected.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="mt-2 flex flex-wrap items-center gap-2">
    <Input value={reason} onChange={event => setReason(event.target.value)} placeholder="Reason (required)" className="min-w-[200px] flex-1"/>
    <Button size="sm" variant="danger" loading={busy} disabled={reason.trim().length < 4} onClick={reject}>Reject</Button>
    {error && <span className="text-xs text-rose-700">{error}</span>}
  </div>;
}

// U6: wires roleChanges/approveRoleChange/rejectRoleChange/reassignmentRequired
// - already exported by projectsApi.js, but not previously called from any
// component - so a project_role_changes row created via requestRoleChange
// (ProjectTeamReplaceModal) is visible and actionable in the portal.
export function PendingRoleChangesPanel({ projectId, user, onChanged }) {
  const [pending, setPending] = useState([]);
  const [reassignmentNeeded, setReassignmentNeeded] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [approvingId, setApprovingId] = useState("");

  // BR-007's hierarchy is role_type-specific, not a flat permission: only
  // Admin/Super Admin may act on a project_manager replacement; a PM may
  // additionally act on a site_supervisor replacement. Showing Approve/
  // Reject to a PM for a PM-replacement request would always 403.
  function canActOn(change) {
    if (["admin", "super_admin"].includes(user?.role)) return true;
    if (change.role_type === "site_supervisor") return user?.role === "project_manager";
    return false;
  }
  const canActOnAny = pending.some(canActOn);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [changes, reassignment] = await Promise.all([
        projectsApi.roleChanges(projectId, "pending"),
        projectsApi.reassignmentRequired(projectId),
      ]);
      setPending(changes);
      setReassignmentNeeded(reassignment);
    } catch (caught) {
      setError(caught?.message || "Pending role changes could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId]);

  async function approve(change) {
    setApprovingId(change.id);
    setError("");
    try {
      await projectsApi.approveRoleChange(projectId, change.id);
      await load();
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This request could not be approved.");
    } finally {
      setApprovingId("");
    }
  }

  async function afterReject() {
    await load();
    await onChanged();
  }

  if (loading) return <div className="grid min-h-24 place-items-center"><LoadingSpinner label="Loading role changes..."/></div>;
  if (!canActOnAny && !pending.length && !reassignmentNeeded.length) return null;

  return <section className="grid gap-3">
    {error && <div className="rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}

    {reassignmentNeeded.length > 0 && <div className="rounded-[20px] border border-orange-100 bg-orange-50 p-4">
      <h3 className="flex items-center gap-2 font-medium text-orange-950"><AlertTriangle size={17}/> Reassignment required</h3>
      <div className="mt-2 grid gap-2">{reassignmentNeeded.map(item => <p key={item.membership_id} className="text-sm text-orange-900">The active <strong>{ROLE_LABEL[item.role_type] || item.role_type}</strong> is marked unavailable - request a replacement below.</p>)}</div>
    </div>}

    {pending.length > 0 && <div className="rounded-[20px] border border-line bg-white p-5">
      <h3 className="text-[15px] font-medium text-slate-950">Pending role changes</h3>
      <div className="mt-3 grid gap-3">{pending.map(change => <article key={change.id} className="rounded-xl border border-line bg-slate-50 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div><strong className="font-normal text-slate-950">{ROLE_LABEL[change.role_type] || change.role_type}</strong><span className="ml-2 text-sm text-slate-600">{change.change_type === "vacate" ? "→ Vacate (no replacement named)" : `→ ${change.replacement_name}`}</span></div>
          <Pill tone="orange">Pending approval</Pill>
        </div>
        <p className="mt-2 text-sm text-slate-600">{change.reason_code}</p>
        {canActOn(change) && <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" loading={approvingId === change.id} onClick={() => approve(change)}>Approve</Button>
        </div>}
        {canActOn(change) && <RejectControl projectId={projectId} change={change} onDone={afterReject}/>}
      </article>)}</div>
    </div>}
  </section>;
}
