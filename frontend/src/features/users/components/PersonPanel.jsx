import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, Check, KeyRound, MessageCircle, MoreHorizontal, RotateCcw, Trash2, UserX, X } from "lucide-react";
import { usersApi } from "../../../api/usersApi";
import { Button, Field, Input, Pill, Select } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { roles } from "../../../utils/constants";
import { initials, relativeAge } from "../../../utils/format";
import { attentionFor } from "../teamHelpers";
import { AccountStatus, LifecycleModal, roleDefinition, SuperAdminNote } from "./UserModals";

const TABS = [["details", "Details"], ["access", "Access"], ["history", "History"]];

const ATTENTION_HELP = {
  not_signed_in: "Hasn't signed in yet. They can use Google with this email, or a password you set on the Access tab.",
  no_phone: "No mobile number, so they get no WhatsApp alerts. Add one below.",
  no_profile: "No employee code or designation, so they can't be put on a project. Fill them in below.",
};

function dateLabel(iso) {
  return iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";
}

export function lastActiveLabel(person) {
  if (!person.last_login_at) return "Never signed in";
  return `Active ${relativeAge(person.last_login_at)}`;
}

function ActionsMenu({ items }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  if (!items.length) return null;
  return <div ref={ref} className="relative">
    <button type="button" aria-label="More account actions" aria-expanded={open} onClick={() => setOpen(value => !value)}
      className="grid size-10 place-items-center rounded-xl text-slate-500 hover:bg-slate-100 hover:text-slate-950"><MoreHorizontal size={18}/></button>
    {open && <div role="menu" className="absolute right-0 top-[calc(100%+6px)] z-20 grid w-56 gap-0.5 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      {items.map(item => <button key={item.label} type="button" role="menuitem" onClick={() => { setOpen(false); item.onClick(); }}
        className={cn("flex items-center gap-2 rounded-xl px-3 py-2 text-left text-sm", item.danger ? "text-rose-700 hover:bg-rose-50" : "text-slate-800 hover:bg-slate-50")}>
        <item.icon size={15} aria-hidden="true"/>{item.label}
      </button>)}
    </div>}
  </div>;
}

function RoleSummary({ definition }) {
  return <div className="rounded-2xl bg-canvas p-4">
    <p className="text-sm text-slate-950">{definition.label}</p>
    <p className="mt-0.5 text-[13px] leading-5 text-slate-500">{definition.summary}</p>
    {definition.capabilities?.length > 0 && <ul className="mt-2.5 grid gap-1.5">
      {definition.capabilities.map(item => <li key={item} className="flex items-start gap-2 text-[13px] text-slate-700"><Check size={14} className="mt-0.5 shrink-0 text-ok" aria-hidden="true"/>{item}</li>)}
    </ul>}
  </div>;
}

function Facts({ items }) {
  return <dl className="divide-y divide-line rounded-2xl border border-line">
    {items.map(([label, value]) => <div key={label} className="flex items-center justify-between gap-4 px-4 py-2.5">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="min-w-0 truncate text-right text-sm text-slate-950">{value || <span className="text-slate-400">Not set</span>}</dd>
    </div>)}
  </dl>;
}

// Your own account, opened from the Team page. Name and mobile for
// everyone; a Super Admin also sets their own employee details, since no
// one sits above them to do it. Role, email and access stay with whoever
// manages the account.
function SelfDetailsForm({ person, action }) {
  const [saving, setSaving] = useState(false);
  const profile = person.employee_profile || {};
  const ownsProfile = person.role === "super_admin";

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    await action(() => usersApi.updateMe(Object.fromEntries(new FormData(event.currentTarget))), "Profile updated");
    setSaving(false);
  }

  return <form id="my-details" onSubmit={save} className="grid gap-4">
    <div className="grid items-start gap-4 sm:grid-cols-2">
      <Field label="Full name"><Input name="name" defaultValue={person.name} required/></Field>
      <Field label="Mobile number" hint="Needed for WhatsApp alerts."><Input name="phone" inputMode="tel" defaultValue={person.phone || ""} placeholder="+919876543210"/></Field>
      {ownsProfile && <>
        <Field label="Employee code"><Input name="employee_code" defaultValue={profile.employee_code || ""} required/></Field>
        <Field label="Designation"><Input name="designation" defaultValue={profile.designation || ""} required/></Field>
        <Field label="Department" className="sm:col-span-2"><Input name="department" defaultValue={profile.department || ""}/></Field>
      </>}
    </div>
    <Facts items={ownsProfile
      ? [["Email login", person.email], ["Role", roles[person.role] || person.role]]
      : [["Email login", person.email], ["Role", roles[person.role] || person.role], ["Employee code", profile.employee_code], ["Designation", profile.designation], ["Department", profile.department]]}/>
    <p className="text-sm leading-6 text-slate-500">{ownsProfile
      ? "Your email, role and access can only be changed by another Super Admin."
      : "Your role, email and employee details are set by a higher authority."}</p>
    <div className="flex justify-end"><Button type="submit" loading={saving}>Save changes</Button></div>
  </form>;
}

function DetailsTab({ person, canManage, isSelf, catalog, manageableRoles, action }) {
  const [role, setRole] = useState(person.role);
  const [saving, setSaving] = useState(false);
  const profile = person.employee_profile || {};
  const roleChanged = role !== person.role;

  if (isSelf) return <SelfDetailsForm person={person} action={action}/>;

  if (!canManage) {
    return <div className="grid gap-4">
      <Facts items={[
        ["Email login", person.email], ["Mobile number", person.phone], ["Employee code", profile.employee_code],
        ["Designation", profile.designation], ["Department", profile.department],
      ]}/>
      <p className="text-sm leading-6 text-slate-500">You can see this person for context, but their role is outside what you can manage.</p>
    </div>;
  }

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    await action(() => usersApi.update(person.id, Object.fromEntries(new FormData(event.currentTarget))), "Changes saved");
    setSaving(false);
  }

  return <form id="person-details" onSubmit={save} className="grid gap-4">
    <div className="grid items-start gap-4 sm:grid-cols-2">
      <Field label="Full name"><Input name="name" defaultValue={person.name} required/></Field>
      <Field label="Email login"><Input name="email" type="email" defaultValue={person.email} required/></Field>
      <Field label="Mobile number" hint="Needed for WhatsApp alerts."><Input name="phone" inputMode="tel" defaultValue={person.phone || ""} placeholder="+919876543210"/></Field>
      <Field label="Role"><Select name="role" value={role} onChange={event => setRole(event.target.value)}>{manageableRoles.map(item => <option key={item} value={item}>{roles[item]}</option>)}</Select></Field>
      <Field label="Employee code"><Input name="employee_code" defaultValue={profile.employee_code || ""} required/></Field>
      <Field label="Designation"><Input name="designation" defaultValue={profile.designation || ""} required/></Field>
      <Field label="Department" className="sm:col-span-2"><Input name="department" defaultValue={profile.department || ""}/></Field>
      {roleChanged && <Field className="sm:col-span-2" label="Reason for the role change" hint="Written to their account history."><Input name="reason" minLength={4} required placeholder="Why their responsibility is changing"/></Field>}
    </div>
    {roleChanged && <RoleSummary definition={roleDefinition(catalog, role)}/>}
    {roleChanged && role === "super_admin" && <SuperAdminNote/>}
    <div className="flex justify-end"><Button type="submit" loading={saving}>Save changes</Button></div>
  </form>;
}

function PasswordForm({ person, action }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    const result = await action(() => usersApi.setPassword(person.id, password), "Password set - share it with them privately");
    setBusy(false);
    if (result?.ok !== false) setPassword("");
  }
  return <form onSubmit={submit} className="grid gap-3">
    <p className="text-sm leading-6 text-slate-600">Lets {person.name} sign in with {person.email} and a password, as well as Google. A new password replaces the old one; SiteOps never stores it.</p>
    <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
      <Field label="New password" htmlFor="set-password" hint="At least 8 characters." className="flex-1"><Input id="set-password" type="password" autoComplete="new-password" minLength={8} value={password} onChange={event => setPassword(event.target.value)} required/></Field>
      <Button type="submit" loading={busy} disabled={password.length < 8} className="sm:mb-6"><KeyRound size={16}/> Set password</Button>
    </div>
  </form>;
}

function AccessTab({ person, canManage, catalog, action }) {
  return <div className="grid gap-5">
    <section className="grid gap-2">
      <h4 className="text-[15px] font-medium text-slate-950">What they can do</h4>
      <RoleSummary definition={roleDefinition(catalog, person.role)}/>
    </section>
    <section className="grid gap-2">
      <h4 className="text-[15px] font-medium text-slate-950">Notifications</h4>
      <p className="flex items-start gap-2 text-sm leading-6 text-slate-600">
        <MessageCircle size={16} className={cn("mt-1 shrink-0", person.phone ? "text-ok" : "text-orange-600")} aria-hidden="true"/>
        {person.phone
          ? <span>Gets task, gate and approval alerts on WhatsApp at {person.phone}, and can reply with commands.</span>
          : <span className="text-orange-800">No mobile number, so no WhatsApp alerts. Add one on the Details tab.</span>}
      </p>
    </section>
    {canManage && person.active && <section className="grid gap-2" id="person-password">
      <h4 className="text-[15px] font-medium text-slate-950">Sign-in</h4>
      <PasswordForm person={person} action={action}/>
    </section>}
  </div>;
}

function HistoryTab({ person }) {
  const [state, setState] = useState({ loading: true, events: [] });
  useEffect(() => {
    let alive = true;
    usersApi.events(person.id)
      .then(events => alive && setState({ loading: false, events: Array.isArray(events) ? events : [] }))
      .catch(() => alive && setState({ loading: false, events: [] }));
    return () => { alive = false; };
  }, [person.id]);
  if (state.loading) return <p className="text-sm text-slate-500">Loading history…</p>;
  if (!state.events.length) return <p className="rounded-2xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">No account changes recorded yet.</p>;
  return <ol className="grid gap-2" aria-label="Account history">
    {state.events.map(item => <li key={item.id} className="rounded-2xl border border-line p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm text-slate-950">{String(item.event_type || "").replaceAll("_", " ").toLowerCase().replace(/^./, c => c.toUpperCase())}</span>
        <time className="text-xs text-slate-500">{new Date(item.created_at).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</time>
      </div>
      {item.reason && <p className="mt-1 text-[13px] leading-5 text-slate-600">{item.reason}</p>}
    </li>)}
  </ol>;
}

export function PersonPanel({ person, actor, catalog, manageableRoles, action, onClose }) {
  const [tab, setTab] = useState("details");
  const [lifecycle, setLifecycle] = useState("");
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const isSelf = person.id === actor.id;
  const canManage = manageableRoles.includes(person.role) && !isSelf;
  const canDelete = actor.role === "super_admin" && !person.active && canManage;
  const flags = attentionFor(person);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = event => { if (event.key === "Escape" && !lifecycle) onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previous; document.removeEventListener("keydown", onKey); };
  }, [onClose, lifecycle]);
  useEffect(() => { setTab("details"); }, [person.id]);

  const menu = canManage ? [
    ...(person.active ? [{ label: "Set password", icon: KeyRound, onClick: () => setTab("access") }] : []),
    ...(person.active ? [{ label: "Offboard", icon: UserX, onClick: () => setLifecycle("offboard"), danger: true }] : [{ label: "Restore access", icon: RotateCcw, onClick: () => setLifecycle("restore") }]),
    ...(canDelete ? [{ label: "Delete unused account", icon: Trash2, onClick: () => setLifecycle("delete"), danger: true }] : []),
  ] : [];

  async function applyLifecycle(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setLifecycleBusy(true);
    const operation = lifecycle === "delete" ? () => usersApi.remove(person.id, values)
      : lifecycle === "restore" ? () => usersApi.restore(person.id, values.reason)
      : () => usersApi.offboard(person.id, values.reason);
    const notice = lifecycle === "delete" ? "Unused account permanently deleted" : lifecycle === "restore" ? "Access restored" : "Offboarded - their login is blocked";
    const deleting = lifecycle === "delete";
    const result = await action(operation, notice);
    setLifecycleBusy(false);
    if (result?.ok) { setLifecycle(""); if (deleting) onClose(); }
  }

  return createPortal(<>
    <div className="fixed inset-0 z-40 bg-slate-950/30" onClick={onClose} aria-hidden="true"/>
    <aside role="dialog" aria-label={`Person - ${person.name}`} className="fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-white shadow-[-16px_0_50px_rgba(21,23,26,.14)] sm:w-[600px] sm:max-w-[92vw] sm:rounded-l-[26px]">
      <header className="border-b border-line px-5 pt-5 sm:px-6">
        <div className="flex items-start gap-3">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-blue-50 text-base font-medium text-blue-800">{initials(person.name)}</span>
          <div className="min-w-0 flex-1">
            <h2 className="flex flex-wrap items-center gap-2 text-xl font-light tracking-[-0.01em] text-slate-950">{person.name}{isSelf && <Pill tone="gray">You</Pill>}</h2>
            <p className="truncate text-sm text-slate-500">{person.email}</p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Pill>{roles[person.role] || person.role}</Pill>
              <AccountStatus person={person}/>
              <span className="text-xs text-slate-500">{lastActiveLabel(person)}{person.created_at ? ` · Added ${dateLabel(person.created_at)}` : ""}</span>
            </div>
          </div>
          <ActionsMenu items={menu}/>
          <button type="button" aria-label="Close" onClick={onClose} className="grid size-10 shrink-0 place-items-center rounded-xl text-slate-500 hover:bg-slate-100 hover:text-slate-950"><X size={19}/></button>
        </div>
        {flags.length > 0 && <ul className="mt-3 grid gap-1" aria-label="Needs attention">
          {flags.map(key => <li key={key} className="flex items-start gap-2 rounded-xl bg-orange-50 px-3 py-2 text-[13px] leading-5 text-orange-900">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true"/>{ATTENTION_HELP[key]}
          </li>)}
        </ul>}
        <nav aria-label="Person sections" className="-mb-px mt-3 flex gap-1">
          {TABS.map(([key, label]) => <button key={key} type="button" onClick={() => setTab(key)} aria-current={tab === key ? "page" : undefined}
            className={cn("inline-flex min-h-11 items-center px-2.5 text-sm transition-colors", tab === key ? "text-slate-950 shadow-[inset_0_-2px_0_var(--color-slate-950)]" : "text-slate-500 hover:text-slate-950")}>{label}</button>)}
        </nav>
      </header>
      <div className="so-scroll min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
        {tab === "details" && <DetailsTab key={person.id} person={person} canManage={canManage} isSelf={isSelf} catalog={catalog} manageableRoles={manageableRoles} action={action}/>}
        {tab === "access" && <AccessTab person={person} canManage={canManage} catalog={catalog} action={action}/>}
        {tab === "history" && <HistoryTab person={person}/>}
      </div>
    </aside>
    {lifecycle && <LifecycleModal mode={lifecycle} person={person} onClose={() => setLifecycle("")} onConfirm={applyLifecycle} loading={lifecycleBusy}/>}
  </>, document.body);
}
