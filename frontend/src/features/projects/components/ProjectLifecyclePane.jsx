import { useEffect, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Alert, Button, Field, Input, Select } from "../../../components/ui";
import { isOrgAdmin } from "../../../utils/constants";
import { PaneHeader } from "../../../components/layout/PaneKit";

const actionLabel = value => value.toLowerCase().replaceAll("_", " ").replace(/(^|\s)\S/g, match => match.toUpperCase());

// Mirrors change_status' guards in backend/app/routes/projects_v2.py:
// activate and archive are Admin/Super Admin, on-hold/complete are
// Admin/Super Admin or the project's own PM.
const ORG_ADMIN_TRANSITIONS = { draft: ["active", "archived"], active: ["on_hold", "completed", "archived"], on_hold: ["active", "completed", "archived"], completed: ["archived"], archived: [] };
const TRANSITIONS = {
  super_admin: ORG_ADMIN_TRANSITIONS,
  admin: ORG_ADMIN_TRANSITIONS,
  project_manager: { active: ["on_hold", "completed"], on_hold: ["completed"] },
};

// The lifecycle as a line of stages, so the reader sees where the project
// is and what comes next before choosing a transition. On hold sits beside
// Active rather than after it: it is a pause, not a step forward.
const STAGES = [["draft", "Draft"], ["active", "Active"], ["completed", "Completed"], ["archived", "Archived"]];

function LifecycleTrack({ status }) {
  const currentIndex = status === "on_hold" ? 1 : STAGES.findIndex(([key]) => key === status);
  return <ol className="flex flex-wrap items-center gap-y-3" aria-label="Lifecycle stages">
    {STAGES.map(([key, label], index) => {
      const done = index < currentIndex;
      const current = index === currentIndex;
      const name = current && status === "on_hold" ? "Active, on hold" : label;
      return <li key={key} className="flex items-center" aria-current={current ? "step" : undefined}>
        <span className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px] ${current ? (status === "on_hold" ? "bg-orange-50 text-orange-900 ring-1 ring-orange-200" : "bg-slate-950 text-white") : done ? "text-slate-700" : "text-slate-400"}`}>
          <span className={`size-2 rounded-full ${current ? (status === "on_hold" ? "bg-behind" : "bg-white") : done ? "bg-emerald-500" : "bg-slate-300"}`} aria-hidden="true"/>
          {name}
        </span>
        {index < STAGES.length - 1 && <span className={`mx-1 h-px w-6 sm:w-10 ${done ? "bg-emerald-400" : "bg-slate-200"}`} aria-hidden="true"/>}
      </li>;
    })}
  </ol>;
}

export function ProjectLifecyclePane({ project, user, onChanged, onDeleted }) {
  const transitions = TRANSITIONS[user.role]?.[project.status] || [];
  const canDelete = isOrgAdmin(user) && project.status === "draft" && !project.template_version_id && project.memberships.length === 0;
  const isArchived = project.status === "archived";
  const canRestore = isArchived && isOrgAdmin(user);
  const [target, setTarget] = useState(transitions[0] || "");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // project.status changes (e.g. after a successful transition, since this
  // pane stays mounted and only `project` is reloaded) recompute `transitions`
  // above - reset `target` so it can't keep pointing at a value that's no
  // longer a valid transition for the new status.
  useEffect(() => {
    setTarget((TRANSITIONS[user.role]?.[project.status] || [])[0] || "");
  }, [project.status, user.role]);

  async function restore(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await projectsApi.restore(project.id, reason);
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      // Draft -> active is the one transition with its own dedicated,
      // notification-emitting endpoint (see projectsApi.activate's comment).
      // Every other transition keeps going through the generic /status route,
      // unchanged.
      if (target === "active" && project.status === "draft") {
        await projectsApi.activate(project.id, reason);
      } else {
        await projectsApi.setStatus(project.id, target, reason);
      }
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeDraft() {
    setBusy(true);
    setError("");
    try {
      await projectsApi.remove(project.id, { confirmation, reason });
      await onDeleted();
    } catch (caught) {
      setError(caught.message);
      setBusy(false);
    }
  }

  // Explain the actual blocker. Saying "Admin only" to an Admin looking at
  // an archived project is both wrong and a dead end - archived is terminal
  // in change_status, which is a state problem, not a permission one.
  if (!transitions.length && !canDelete && !canRestore) {
    const message = isArchived
      ? "This project is archived. Only an Admin can restore it."
      : project.status === "completed"
        ? "This project is complete. Only an Admin can archive it from here."
        : "Your role cannot change this project's lifecycle state. Activating, archiving and deleting a project are Admin-only actions.";
    return <div className="grid gap-5">
      <PaneHeader title="Lifecycle" description="Every transition requires a reason and is retained in activity."/>
      <section className="rounded-[20px] border border-line bg-white p-5"><LifecycleTrack status={project.status}/></section>
      <p className="rounded-2xl border border-line bg-slate-50 px-4 py-3 text-sm text-slate-600">{message}</p>
    </div>;
  }

  const activationBlocked = target === "active" && project.status === "draft" && !project.setup.activation_ready;

  return <div className="grid gap-5">
    <PaneHeader title="Lifecycle" description="Every transition requires a reason and is retained in activity."/>
    <section className="rounded-[20px] border border-line bg-white p-5"><LifecycleTrack status={project.status}/></section>

    {error && <Alert tone="danger">{error}</Alert>}

    {canRestore && <section className="rounded-[20px] border border-line bg-white p-5">
      <h4 className="text-[15px] font-medium text-slate-950">Restore project</h4>
      <p className="mt-1 text-[13px] leading-5 text-slate-600">
        Restoring returns it to the state it held before archiving. A project that was active comes back <strong className="font-medium">on hold</strong>, so work is never silently resumed.
      </p>
      <form onSubmit={restore} className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <Field label="Reason for restoring">
          <Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} required placeholder="Why is this project being restored?"/>
        </Field>
        <Button type="submit" loading={busy} disabled={reason.trim().length < 4}>Restore project</Button>
      </form>
    </section>}

    {transitions.length > 0 && <section className="rounded-[20px] border border-line bg-white p-5">
      <h4 className="text-[15px] font-medium text-slate-950">Change status</h4>
      <p className="mt-1 text-[13px] text-slate-500">Pick where the project goes next and say why.</p>
      <form onSubmit={changeStatus} className="mt-4 grid gap-3 md:grid-cols-[200px_minmax(0,1fr)_auto] md:items-end">
        <Field label="Move project to">
          <Select value={target} onChange={event => setTarget(event.target.value)}>
            {transitions.map(value => <option key={value} value={value}>{actionLabel(value)}</option>)}
          </Select>
        </Field>
        <Field label="Reason">
          <Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} required placeholder="Operational reason for this change"/>
        </Field>
        <Button type="submit" loading={busy} disabled={activationBlocked}>Confirm</Button>
        {activationBlocked && <p className="rounded-xl bg-orange-50 px-3 py-2 text-[13px] text-orange-900 md:col-span-3">
          Complete all four activation details first, and generate the task snapshot — activation also requires at least one included task.
        </p>}
      </form>
    </section>}

    {canDelete && <section className="rounded-[20px] border border-rose-100 bg-white p-5">
      <h4 className="text-[15px] font-medium text-rose-700">Delete unused draft</h4>
      <p className="mt-1 text-[13px] leading-5 text-slate-500">
        Only a draft with no team and no template can be permanently deleted. Type <strong className="font-medium text-slate-800">{project.code}</strong> and provide the reason.
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-[200px_minmax(0,1fr)_auto] md:items-end">
        <Field label="Project code"><Input value={confirmation} onChange={event => setConfirmation(event.target.value)} placeholder={project.code}/></Field>
        <Field label="Deletion reason"><Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} placeholder="Why is this draft being removed?"/></Field>
        <Button variant="danger" disabled={confirmation !== project.code || reason.length < 4} loading={busy} onClick={removeDraft}>Delete draft</Button>
      </div>
    </section>}
  </div>;
}
