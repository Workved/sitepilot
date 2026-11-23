import { useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, Field, Input, Modal, Select } from "../../../components/ui";
import { PendingRoleChangesPanel } from "./PendingRoleChangesPanel";
import { ProjectTeamReplaceModal } from "./ProjectTeamReplaceModal";

const roleLabel = { project_manager: "Project Manager", site_supervisor: "Site Supervisor", internal_employee: "Internal Employee" };

// Mirrors set_membership's own `allowed` computation (backend/app/routes/
// projects_v2.py) exactly: Admin can assign any role; a PM can assign
// Supervisor/Internal Employee; a Supervisor can assign Internal Employee
// only. Project-specific (is this actor the PM/Supervisor *of this
// project*), not the actor's global role - same distinction the backend
// itself draws.
const TEAM_ROLE_OPTIONS = [
  { value: "project_manager", label: "Project Manager", referenceKey: "project_managers" },
  { value: "site_supervisor", label: "Site Supervisor", referenceKey: "supervisors" },
  { value: "internal_employee", label: "Internal Employee", referenceKey: "internal_employees" },
];

function AddTeamMemberForm({ project, user, references, onChanged }) {
  const isAdmin = user.role === "admin" || user.role === "super_admin";
  const isPmOnProject = project.memberships?.some(item => item.project_role === "project_manager" && item.user_id === user.id);
  const isSupervisorOnProject = project.memberships?.some(item => item.project_role === "site_supervisor" && item.user_id === user.id);
  const assignableRoles = TEAM_ROLE_OPTIONS.filter(option => {
    if (option.value === "project_manager") return isAdmin;
    if (option.value === "site_supervisor") return isAdmin || isPmOnProject;
    return isAdmin || isPmOnProject || isSupervisorOnProject;
  });

  const [role, setRole] = useState(assignableRoles[0]?.value || "");
  const [employeeId, setEmployeeId] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  if (!assignableRoles.length || project.status === "completed" || project.status === "archived") return null;

  const candidates = references[TEAM_ROLE_OPTIONS.find(option => option.value === role)?.referenceKey] || [];

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const result = await projectsApi.setMembership(project.id, { employee_id: employeeId, project_role: role, reason });
      setNotice(result.status ? "Replacement request submitted - pending approval." : "Added to the project team.");
      setEmployeeId("");
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "Could not add this team member.");
    } finally {
      setSaving(false);
    }
  }

  return <section className="rounded-2xl border border-slate-200 bg-white p-4">
    <h3 className="text-sm font-black text-slate-950">Add team member</h3>
    <form onSubmit={submit} className="mt-3 grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
      <Field label="Role">
        <Select value={role} onChange={event => { setRole(event.target.value); setEmployeeId(""); }}>
          {assignableRoles.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </Select>
      </Field>
      <Field label="Person">
        <Select value={employeeId} onChange={event => setEmployeeId(event.target.value)} required>
          <option value="">{candidates.length ? "Select person" : "No eligible active users"}</option>
          {candidates.map(candidate => <option key={candidate.employee_id} value={candidate.employee_id}>{candidate.name} - {candidate.designation}</option>)}
        </Select>
      </Field>
      <Field label="Reason">
        <Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} required placeholder="Why is this person joining the team?"/>
      </Field>
      <Button type="submit" loading={saving} disabled={!employeeId}>Add</Button>
    </form>
    {notice && <p className="mt-3 text-sm font-bold text-emerald-700">{notice}</p>}
    {error && <p className="mt-3 text-sm font-bold text-rose-700">{error}</p>}
  </section>;
}

// Internal Employee can always be removed directly (subject to the actor
// permission check the caller already applied). project_manager and
// site_supervisor are the "accountable role" singularities (BR-004/BR-007):
// end_membership itself only allows a direct end for them while the project
// is draft or on_hold - once active, BR-007's replace/approve flow
// (ProjectTeamReplaceModal, including its "Vacate now" option) is the only
// path, so vacating a live project's accountable role is always audited via
// a role-change record rather than silent. The caller only renders this for
// a role/status combination end_membership will actually accept.
function RemoveMembershipModal({ project, membership, onClose, onChanged }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await projectsApi.endMembership(project.id, membership.id, reason);
      await onChanged();
      onClose();
    } catch (caught) {
      setError(caught?.message || "Could not remove this team member.");
    } finally {
      setSaving(false);
    }
  }

  return <Modal title={`Remove ${membership.name}`} onClose={onClose}>
    <form onSubmit={submit} className="grid gap-4">
      <p className="text-sm text-slate-500">This ends {membership.name}'s {roleLabel[membership.project_role]} assignment on this project. They can be re-added later if needed.</p>
      <Field label="Reason">
        <Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} required placeholder="Why is this person leaving the project team?"/>
      </Field>
      {error && <p className="text-sm font-bold text-rose-700">{error}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="danger" loading={saving} disabled={reason.trim().length < 4}>Remove</Button>
      </div>
    </form>
  </Modal>;
}

export function ProjectTeamPane({ project, references, user, onChanged }) {
  const [replaceRole, setReplaceRole] = useState(null);
  const [removingMembership, setRemovingMembership] = useState(null);
  const isAdmin = user.role === "admin" || user.role === "super_admin";
  const isPmOnProject = project.memberships?.some(item => item.project_role === "project_manager" && item.user_id === user.id);
  const isSupervisorOnProject = project.memberships?.some(item => item.project_role === "site_supervisor" && item.user_id === user.id);
  const canRemoveInternalEmployee = (isAdmin || isPmOnProject || isSupervisorOnProject) && !["completed", "archived"].includes(project.status);
  const pm = project.memberships?.find(item => item.project_role === "project_manager");
  const supervisor = project.memberships?.find(item => item.project_role === "site_supervisor");
  // Mirrors _require_hierarchy_actor (backend/app/services/project_role_change.py)
  // exactly: PM replacement is Admin-only; Supervisor replacement is Admin
  // or the project's own PM. U6: this two-step request/approval flow
  // (BR-007) specifically governs replacement on ACTIVE projects - gating
  // "Change" to draft-only left this unit's flow with no UI entry point
  // once a project goes active.
  const canReplace = {
    project_manager: ["draft", "active"].includes(project.status) && isAdmin,
    site_supervisor: ["draft", "active"].includes(project.status) && (isAdmin || isPmOnProject),
  };
  // Direct removal (no named replacement) works on draft AND on_hold
  // projects - end_membership only rejects it when project.status ===
  // "active" (see backend/app/routes/projects_v2.py). On an active project,
  // vacating still requires the audited role-change flow below (via
  // "Change" -> "Vacate now"), even with no replacement named. Same
  // hierarchy as canReplace otherwise.
  const canRemoveAccountableRole = {
    project_manager: ["draft", "on_hold"].includes(project.status) && isAdmin,
    site_supervisor: ["draft", "on_hold"].includes(project.status) && (isAdmin || isPmOnProject),
  };

  return <div className="grid gap-3">
    <section className="grid gap-2 sm:grid-cols-3">
      {[
        ["Creator", project.creator?.name || project.created_by_name || "—", null],
        ["Project Manager", pm?.name || "Not assigned", "project_manager"],
        ["Supervisor", supervisor?.name || "Not assigned", "site_supervisor"],
      ].map(([label, value, changeRole]) => <article key={label} className="rounded-2xl border border-slate-200 bg-white p-4">
        <p className="font-mono text-[10px] uppercase tracking-[.1em] text-slate-400">{label}</p>
        <h4 className="mt-1.5 truncate text-sm font-black text-slate-950">{value}</h4>
        {changeRole && canReplace[changeRole] && <Button variant="secondary" className="mt-3" onClick={() => setReplaceRole(changeRole)}>Change</Button>}
      </article>)}
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-black text-slate-950">Memberships</h3>
      <div className="mt-2 grid">
        {(project.memberships || []).map(item => <div key={item.id} className="flex items-center justify-between gap-3 border-b border-slate-100 py-2.5 last:border-0">
          <div className="min-w-0">
            <strong className="block truncate text-sm font-semibold text-slate-900">{item.name}</strong>
            <span className="block truncate text-[11px] text-slate-400">{item.designation || item.employee_code}</span>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className="text-xs font-bold text-slate-500">{roleLabel[item.project_role]}</span>
            {item.project_role === "internal_employee" && canRemoveInternalEmployee && <Button size="sm" variant="ghost" className="!text-rose-700 hover:!bg-rose-50" onClick={() => setRemovingMembership(item)}>Remove</Button>}
            {canRemoveAccountableRole[item.project_role] && <Button size="sm" variant="ghost" className="!text-rose-700 hover:!bg-rose-50" onClick={() => setRemovingMembership(item)}>Remove</Button>}
          </div>
        </div>)}
        {!(project.memberships || []).length && <p className="py-3 text-xs text-slate-400">Nobody is assigned to this project yet.</p>}
      </div>
    </section>

    <AddTeamMemberForm project={project} user={user} references={references} onChanged={onChanged}/>

    <PendingRoleChangesPanel projectId={project.id} user={user} onChanged={onChanged}/>

    {replaceRole && <ProjectTeamReplaceModal project={project} role={replaceRole} references={references} hasCurrentHolder={Boolean(replaceRole === "project_manager" ? pm : supervisor)} onClose={() => setReplaceRole(null)} onChanged={onChanged}/>}
    {removingMembership && <RemoveMembershipModal project={project} membership={removingMembership} onClose={() => setRemovingMembership(null)} onChanged={onChanged}/>}
  </div>;
}
