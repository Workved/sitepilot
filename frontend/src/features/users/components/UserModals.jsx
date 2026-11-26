import { useState } from "react";
import { Check, RotateCcw, Trash2, UserPlus, UserX } from "lucide-react";
import { usersApi } from "../../../api/usersApi";
import { Button, Field, FormActions, Input, Modal, Pill, Select, Textarea } from "../../../components/ui";
import { roles } from "../../../utils/constants";

export function roleDefinition(catalog, role) {
  return catalog.find(item => item.role === role) || { label: roles[role] || role, summary: "Role-based SiteOps access.", capabilities: [] };
}

export function AccountStatus({ person }) {
  if (!person.active) return <Pill tone="gray">Offboarded</Pill>;
  if (person.activation_status === "setup_pending") return <Pill tone="orange">Setup pending</Pill>;
  return <Pill tone="green">Active</Pill>;
}

// Shown wherever someone is about to be given Super Admin, the one role
// nobody above can take back from them.
export function SuperAdminNote() {
  return <p role="note" className="rounded-xl bg-orange-50 px-3 py-2 text-[13px] leading-5 text-orange-900">
    Super Admins have full control of SiteOps, including other Super Admins' accounts. Only give this role to people who run the platform.
  </p>;
}

// Role first, because it decides everything else: what they can do is shown
// right next to the picker, then their details, then how they sign in.
export function CreateUserModal({ create, catalog, manageableRoles, onClose }) {
  const [selectedRole, setSelectedRole] = useState(manageableRoles[0] || "");
  const definition = roleDefinition(catalog, selectedRole);
  return <Modal title="Add team member" subtitle="Set up their role and details. They can sign in straight away." onClose={onClose} className="sm:max-w-2xl"
    footer={<FormActions><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="add-member-form"><UserPlus size={17}/> Add team member</Button></FormActions>}>
    <form id="add-member-form" className="grid gap-6" onSubmit={create}>
      <section className="grid gap-3">
        <Field label="Role"><Select name="role" value={selectedRole} onChange={event => setSelectedRole(event.target.value)} required>{manageableRoles.map(role => <option key={role} value={role}>{roles[role]}</option>)}</Select></Field>
        <div className="rounded-2xl bg-canvas p-4" aria-label="What this role can do">
          <p className="text-[13px] leading-5 text-slate-600">{definition.summary}</p>
          {definition.capabilities?.length > 0 && <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
            {definition.capabilities.map(item => <li key={item} className="flex items-start gap-2 text-[13px] text-slate-700"><Check size={14} className="mt-0.5 shrink-0 text-ok" aria-hidden="true"/>{item}</li>)}
          </ul>}
        </div>
        {selectedRole === "super_admin" && <SuperAdminNote/>}
      </section>

      <section className="grid gap-3">
        <h3 className="text-[15px] font-medium text-slate-950">Details</h3>
        <div className="grid items-start gap-4 sm:grid-cols-2">
          <Field label="Full name"><Input name="name" autoComplete="name" placeholder="e.g. Ananya Shah" required/></Field>
          <Field label="Email login" hint="The Google account they'll sign in with."><Input name="email" type="email" autoComplete="email" placeholder="name@company.com" required/></Field>
          <Field label="Mobile number" hint="Needed for WhatsApp alerts."><Input name="phone" inputMode="tel" placeholder="+919876543210"/></Field>
          <Field label="Employee code"><Input name="employee_code" placeholder="EMP-00124" required/></Field>
          <Field label="Designation"><Input name="designation" placeholder="Project Manager" required/></Field>
          <Field label="Department"><Input name="department" placeholder="Projects / Operations"/></Field>
        </div>
      </section>

      <section className="grid gap-3">
        <h3 className="text-[15px] font-medium text-slate-950">Sign-in</h3>
        <p className="text-[13px] leading-5 text-slate-600">They can sign in with Google using the email above. Set a password too if they don't use Google; share it with them privately.</p>
        <Field label="Password (optional)" hint="At least 8 characters."><Input name="password" type="password" autoComplete="new-password" minLength={8}/></Field>
      </section>
    </form>
  </Modal>;
}

export function LifecycleModal({ mode, person, onClose, onConfirm, loading }) {
  const deleting = mode === "delete";
  const restoring = mode === "restore";
  const title = deleting ? "Permanently delete this unused account?" : restoring ? `Restore access for ${person.name}?` : `Offboard ${person.name}?`;
  const explanation = deleting
    ? "Only for test or duplicate accounts with no history. This also removes their sign-in identity and can't be undone."
    : restoring
      ? "They will be able to sign in again immediately."
      : "Their login is blocked straight away. Their project, task, approval and audit history stays. Any project they lead as PM or Supervisor must be reassigned first.";

  return <Modal title={title} onClose={onClose} className="sm:max-w-lg">
    <form onSubmit={onConfirm} className="grid gap-5">
      <p className="text-sm leading-6 text-slate-600">{explanation}</p>
      <Field label="Reason" hint="Required, and kept in their account history."><Textarea name="reason" minLength={4} required
        placeholder={deleting ? "Duplicate test account" : restoring ? "Returned to active duty" : "Left the company on DD/MM/YYYY"}/></Field>
      {deleting && <Field label="Type their email to confirm" hint={person.email}><Input name="confirmation" type="email" autoComplete="off" required/></Field>}
      <FormActions>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" variant={restoring ? "primary" : "danger"} loading={loading}>
          {deleting ? <><Trash2 size={16}/> Delete permanently</> : restoring ? <><RotateCcw size={16}/> Restore access</> : <><UserX size={16}/> Offboard</>}
        </Button>
      </FormActions>
    </form>
  </Modal>;
}

export function EditMyProfileModal({ user, onClose, action }) {
  async function save(event) {
    event.preventDefault();
    const result = await action(() => usersApi.updateMe(Object.fromEntries(new FormData(event.currentTarget))), "Profile updated");
    if (result?.ok !== false) onClose();
  }
  return <Modal title="Edit contact details" subtitle="Your name and number, as the team and WhatsApp alerts see them." onClose={onClose} className="sm:max-w-lg"
    footer={<FormActions><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="edit-me-form">Save</Button></FormActions>}>
    <form id="edit-me-form" className="grid gap-4" onSubmit={save}>
      <Field label="Full name"><Input name="name" defaultValue={user.name} required/></Field>
      <Field label="Mobile number" hint="Needed for WhatsApp alerts."><Input name="phone" inputMode="tel" defaultValue={user.phone || ""} placeholder="+919876543210"/></Field>
    </form>
  </Modal>;
}
