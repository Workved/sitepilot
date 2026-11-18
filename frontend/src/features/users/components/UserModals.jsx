import { useEffect, useState } from "react";
import { Activity, AlertTriangle, ArrowLeftRight, Check, Clock3, Copy, KeyRound, MessageCircle, RotateCcw, Save, ShieldCheck, Trash2, Unlink, UserPlus, UserX } from "lucide-react";
import { channelToggleApi } from "../../../api/channelToggleApi";
import { telegramConnectApi } from "../../../api/telegramConnectApi";
import { usersApi } from "../../../api/usersApi";
import { MyTelegramPanel } from "./MyTelegramPanel";
import { Button, Field, FormActions, Input, Modal, Pill, Select, Textarea } from "../../../components/ui";
import { roles } from "../../../utils/constants";
import { initials } from "../../../utils/format";

function roleDefinition(catalog, role) {
  return catalog.find(item => item.role === role) || { label: roles[role] || role, summary: "Role-based SiteOps access.", capabilities: [] };
}

function AccountStatus({ person }) {
  if (!person.active) return <Pill tone="gray">Offboarded</Pill>;
  if (person.activation_status === "setup_pending") return <Pill tone="orange">Setup pending</Pill>;
  return <Pill tone="green">Active</Pill>;
}
function IdentityBand({ person }) {
  return <div className="relative overflow-hidden rounded-[24px] bg-[#071a33] p-5 text-white shadow-[0_22px_60px_rgba(7,26,51,.18)] sm:p-6"><div className="absolute -right-12 -top-16 size-40 rounded-full border-[28px] border-blue-500/10"/><div className="relative flex items-center gap-4"><span className="grid size-14 shrink-0 place-items-center rounded-[20px] bg-blue-600 text-base font-black shadow-[0_12px_28px_rgba(37,99,235,.35)]">{initials(person.name)}</span><span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><strong className="truncate text-xl font-black tracking-[-.025em]">{person.name}</strong><AccountStatus person={person}/></span><small className="mt-1 block truncate text-sm text-blue-100/75">{person.email}</small></span></div></div>;
}

function CapabilityPreview({ definition }) {
  return <section className="rounded-[22px] border border-blue-100 bg-blue-50/70 p-4 sm:p-5"><div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-blue-600 text-white"><ShieldCheck size={19}/></span><div><p className="text-xs font-black uppercase tracking-[.16em] text-blue-700">Access preview</p><h3 className="mt-1 font-black text-slate-950">{definition.label}</h3><p className="mt-1 text-sm leading-6 text-slate-600">{definition.summary}</p></div></div><div className="mt-4 grid gap-2 sm:grid-cols-2">{definition.capabilities.map(item => <span key={item} className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs font-bold text-slate-700 shadow-sm"><Check className="text-emerald-600" size={15}/>{item}</span>)}</div></section>;
}

function ChannelPanel({ profile, phone }) {
  const [channel, setChannel] = useState(profile?.active_channel || "whatsapp");
  const [connected, setConnected] = useState(!!profile?.telegram_connected);
  const [chatHint, setChatHint] = useState(profile?.telegram_chat_hint || "");
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [codeBusy, setCodeBusy] = useState(false);
  const [codeError, setCodeError] = useState("");
  const [connectCode, setConnectCode] = useState(null);
  const [unlinkBusy, setUnlinkBusy] = useState(false);
  const [unlinkError, setUnlinkError] = useState("");

  if (!profile?.id) return null;

  const other = channel === "telegram" ? "whatsapp" : "telegram";
  const otherLabel = other === "telegram" ? "Telegram" : "WhatsApp";
  const canSwitchToOther = other !== "telegram" || connected;
  // No auto-fallback: a person left on "telegram" with no connected chat
  // is deliberately shown as not-ready rather than silently treated as
  // reachable on WhatsApp instead (see serializers.py's messaging_ready).
  const messagingReady = channel === "telegram" ? connected : !!phone;

  async function switchTo(target) {
    setBusy(true);
    setError("");
    try {
      const response = await channelToggleApi.toggle(profile.id, target);
      const result = response.results?.[0];
      if (!result?.success) setError(result?.error || "Could not switch channel.");
      else setChannel(target);
    } catch (err) {
      setError(err.message || "Could not switch channel.");
    } finally {
      setBusy(false);
    }
  }

  async function unlinkTelegram() {
    // eslint-disable-next-line no-alert -- deliberately simple: this is an
    // Admin-only, low-frequency identity action, not worth a full modal.
    if (!window.confirm(`Unlink Telegram from this person? Messages to them stop going to that chat right away. They'll need a new link to reconnect, and the chat becomes free for someone else to link.`)) return;
    setUnlinkBusy(true);
    setUnlinkError("");
    try {
      await telegramConnectApi.unlink(profile.id);
      setConnected(false);
      setChatHint("");
      setConnectCode(null);
    } catch (err) {
      setUnlinkError(err.message || "Could not unlink Telegram.");
    } finally {
      setUnlinkBusy(false);
    }
  }

  async function generateCode() {
    setCodeBusy(true);
    setCodeError("");
    setCopied(false);
    try {
      const response = await telegramConnectApi.generateCode(profile.id);
      setConnectCode(response);
    } catch (err) {
      setCodeError(err.message || "Could not generate a connect link.");
    } finally {
      setCodeBusy(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(connectCode.link || connectCode.start_command);
      setCopied(true);
    } catch {
      setCodeError("Could not copy - select the link and copy it manually.");
    }
  }

  return <section className="rounded-[22px] border border-slate-200 bg-slate-50 p-4 sm:p-5">
    <div className="flex items-start gap-3">
      <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-blue-600 text-white"><MessageCircle size={19}/></span>
      <div className="min-w-0 flex-1">
        <h3 className="font-black text-slate-950">Messaging channel</h3>
        <p className="mt-1 text-sm leading-6 text-slate-600">Where this person currently receives task, gate and approval notifications - and can reply with commands.</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Pill tone={channel === "telegram" ? "blue" : "green"}>{channel === "telegram" ? "Telegram" : "WhatsApp"}</Pill>
          {connected ? <Pill tone="blue">Telegram connected{chatHint ? ` · chat ${chatHint}` : ""}</Pill> : <Pill tone="gray">Telegram not connected</Pill>}
          {!messagingReady && <Pill tone="orange">Messaging Not Ready</Pill>}
        </div>
        {!canSwitchToOther && <p className="mt-2 text-xs font-semibold text-amber-700">They must connect Telegram (below) before they can be switched over.</p>}
        {error && <p className="mt-2 text-xs font-semibold text-rose-600">{error}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" variant="secondary" loading={busy} disabled={!canSwitchToOther} onClick={() => switchTo(other)}>
            <ArrowLeftRight size={16}/>Switch to {otherLabel}
          </Button>
          {connected && <Button type="button" variant="ghost" loading={unlinkBusy} onClick={unlinkTelegram}>
            <Unlink size={16}/>Unlink Telegram
          </Button>}
        </div>
        {unlinkError && <p className="mt-2 text-xs font-semibold text-rose-600">{unlinkError}</p>}

        {!connected && <div className="mt-4 rounded-2xl border border-dashed border-blue-200 bg-blue-50/60 p-3">
          <p className="flex items-center gap-2 text-xs font-black uppercase tracking-[.14em] text-blue-700"><KeyRound size={14}/>Connect Telegram</p>
          {!connectCode ? <>
            <p className="mt-1 text-xs leading-5 text-slate-600">Generates a one-time link. They open it on their phone, tap Start in a private chat with the bot, and they're connected.</p>
            {codeError && <p className="mt-2 text-xs font-semibold text-rose-600">{codeError}</p>}
            <Button type="button" variant="secondary" className="mt-2" loading={codeBusy} onClick={generateCode}>
              <KeyRound size={16}/>Generate link
            </Button>
          </> : <>
            {connectCode.link ? <>
              <p className="mt-1 text-sm leading-6 text-slate-700">Send them this link. It opens the bot; they tap <strong>Start</strong>:</p>
              <code className="mt-2 block break-all rounded-xl bg-white px-3 py-2 text-sm font-bold text-slate-900 shadow-sm">{connectCode.link}</code>
            </> : <>
              <p className="mt-1 text-sm leading-6 text-slate-700">The bot link isn't available right now. Tell them to open the bot in Telegram and send this message:</p>
              <code className="mt-2 block break-all rounded-xl bg-white px-3 py-2 text-sm font-bold text-slate-900 shadow-sm">{connectCode.start_command}</code>
            </>}
            <p className="mt-2 text-xs font-semibold text-slate-500">Works once. Expires {new Date(connectCode.expires_at).toLocaleTimeString("en-GB")}. Refresh this record afterward to confirm it connected.</p>
            {codeError && <p className="mt-2 text-xs font-semibold text-rose-600">{codeError}</p>}
            <div className="mt-2 flex flex-wrap gap-2">
              <Button type="button" onClick={copyLink}><Copy size={16}/>{copied ? "Copied" : "Copy link"}</Button>
              <Button type="button" variant="secondary" loading={codeBusy} onClick={generateCode}>
                <KeyRound size={16}/>Generate a new link
              </Button>
            </div>
          </>}
        </div>}
      </div>
    </div>
  </section>;
}

// Sets or resets the email/password this person signs in with. A separate
// form from the access record's, so a password is never sent with (or lost
// on) an ordinary profile save.
function PasswordPanel({ person, action }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    const result = await action(() => usersApi.setPassword(person.id, password), "Password set - share it with them privately");
    setBusy(false);
    if (result?.ok !== false) setPassword("");
  }
  return <form onSubmit={submit} className="rounded-[22px] border border-slate-200 p-4 sm:p-5">
    <div className="flex items-start gap-3"><KeyRound className="mt-0.5 shrink-0 text-blue-600" size={19}/><div><h3 className="font-black text-slate-950">Email and password sign-in</h3><p className="mt-1 text-sm leading-6 text-slate-600">Set a password so {person.name} can sign in with {person.email}. Setting a new one replaces the old one. SiteOps never stores it.</p></div></div>
    <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
      <Field label="New password" htmlFor="set-password" hint="At least 8 characters." className="flex-1"><Input id="set-password" type="password" autoComplete="new-password" minLength={8} value={password} onChange={event => setPassword(event.target.value)} required/></Field>
      <Button type="submit" loading={busy} disabled={password.length < 8} className="sm:mb-6"><KeyRound size={17}/>Set password</Button>
    </div>
  </form>;
}

export function CreateUserModal({ create, catalog, manageableRoles, onClose }) {
  const [selectedRole, setSelectedRole] = useState(manageableRoles[0] || "");
  const definition = roleDefinition(catalog, selectedRole);
  return <Modal title="Add team member" subtitle="Pre-register their role and details now - they sign in with Google, or with the email and password you set here." onClose={onClose} className="sm:max-w-3xl"><form className="grid gap-5" onSubmit={create}><CapabilityPreview definition={definition}/><section className="grid gap-4 rounded-[22px] border border-slate-200 bg-white p-4 sm:grid-cols-2 sm:p-5"><Field label="Full name"><Input name="name" autoComplete="name" placeholder="e.g. Ananya Shah" required/></Field><Field label="Email login" hint="Must match the Google account they'll sign in with."><Input name="email" type="email" autoComplete="email" placeholder="name@company.com" required/></Field><Field label="Mobile number" hint="Use international format for future WhatsApp identity."><Input name="phone" inputMode="tel" placeholder="+919876543210"/></Field><Field label="System role"><Select name="role" value={selectedRole} onChange={event => setSelectedRole(event.target.value)} required>{manageableRoles.map(role => <option key={role} value={role}>{roles[role]}</option>)}</Select></Field><Field label="Employee code"><Input name="employee_code" placeholder="EMP-00124" required/></Field><Field label="Designation"><Input name="designation" placeholder="Project Manager" required/></Field><Field label="Department"><Input name="department" placeholder="Projects / Operations"/></Field><Field label="Password (optional)" hint="Lets them sign in with this email and password as well as Google. At least 8 characters - share it with them privately."><Input name="password" type="password" autoComplete="new-password" minLength={8}/></Field></section><FormActions><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit"><UserPlus size={18}/>Add to roster</Button></FormActions></form></Modal>;
}

function LifecycleModal({ mode, person, onClose, onConfirm, loading }) {
  const deleting = mode === "delete";
  const restoring = mode === "restore";
  const title = deleting ? "Permanently delete unused account?" : restoring ? "Restore employee access?" : "Offboard employee?";
  const subtitle = deleting
    ? "Only test or duplicate accounts with no business history can be permanently deleted."
    : restoring
      ? "Restore SiteOps and Supabase login after confirming the employee should regain access."
      : "Block login while preserving all project, task, approval, and audit history.";

  return <Modal title={title} subtitle={subtitle} onClose={onClose}>
    <form onSubmit={onConfirm} className="grid gap-5">
      <section className={"flex items-start gap-3 rounded-[20px] border p-4 text-sm leading-6 " + (deleting ? "border-rose-200 bg-rose-50 text-rose-900" : restoring ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-950")}>
        <span className={"grid size-10 shrink-0 place-items-center rounded-2xl " + (deleting ? "bg-rose-600 text-white" : restoring ? "bg-emerald-600 text-white" : "bg-amber-500 text-white")}>{deleting ? <Trash2 size={19}/> : restoring ? <RotateCcw size={19}/> : <UserX size={19}/>}</span>
        <div><strong className="block text-base">{person.name}</strong><span className="mt-1 block">{deleting ? "This action also removes the Supabase identity and cannot be undone." : restoring ? "The employee will be able to sign in again immediately." : "Active PM or Supervisor responsibilities must be reassigned before offboarding."}</span></div>
      </section>
      <Field label={deleting ? "Deletion reason" : restoring ? "Restoration reason" : "Offboarding reason"} hint="This reason is required for accountability."><Textarea name="reason" minLength={4} placeholder={deleting ? "Duplicate QA identity created during testing." : restoring ? "Employee returned to active duty." : "Employee left the company on DD/MM/YYYY."} required/></Field>
      {deleting && <Field label="Confirm exact email" hint={"Enter " + person.email + " to confirm permanent deletion."}><Input name="confirmation" type="email" autoComplete="off" required/></Field>}
      <FormActions><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" variant={deleting || !restoring ? "danger" : "primary"} loading={loading}>{deleting ? <><Trash2 size={17}/>Delete permanently</> : restoring ? <><RotateCcw size={17}/>Restore access</> : <><UserX size={17}/>Offboard employee</>}</Button></FormActions>
    </form>
  </Modal>;
}

export function UserModal({ selectedUser, actor, catalog, manageableRoles, onClose, action }) {
  const [selectedRole, setSelectedRole] = useState(selectedUser.role);
  const [lifecycleMode, setLifecycleMode] = useState("");
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [events, setEvents] = useState([]);
  const canManage = manageableRoles.includes(selectedUser.role);
  const canDelete = actor.role === "super_admin" && !selectedUser.active && canManage;
  const definition = roleDefinition(catalog, selectedRole);
  const profile = selectedUser.employee_profile;
  // Admins/Super Admins open their own record here (they have no My Profile
  // page), and can't manage their own role - but they can link their own Telegram.
  const isSelf = selectedUser.id === actor.id;

  useEffect(() => { usersApi.events(selectedUser.id).then(setEvents).catch(() => setEvents([])); }, [selectedUser.id]);

  async function save(event) {
    event.preventDefault();
    const result = await action(() => usersApi.update(selectedUser.id, Object.fromEntries(new FormData(event.currentTarget))), "User access updated");
    if (result?.ok !== false) onClose();
  }

  async function applyLifecycle(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setLifecycleBusy(true);
    let operation;
    let notice;
    if (lifecycleMode === "delete") {
      operation = () => usersApi.remove(selectedUser.id, values);
      notice = "Unused account permanently deleted";
    } else if (lifecycleMode === "restore") {
      operation = () => usersApi.restore(selectedUser.id, values.reason);
      notice = "Employee access restored";
    } else {
      operation = () => usersApi.offboard(selectedUser.id, values.reason);
      notice = "Employee offboarded and login blocked";
    }
    const result = await action(operation, notice);
    setLifecycleBusy(false);
    if (result?.ok) { setLifecycleMode(""); onClose(); }
  }

  const roleChanged = selectedRole !== selectedUser.role;
  return <><Modal title="Access record" subtitle="Employee identity, role boundary, lifecycle and immutable account history." onClose={onClose} className="sm:max-w-4xl"><div className="grid gap-5"><IdentityBand person={selectedUser}/>{canManage ? <form className="grid gap-5" onSubmit={save}><section className="grid gap-4 rounded-[22px] border border-slate-200 p-4 sm:grid-cols-2 sm:p-5"><Field label="Full name"><Input name="name" defaultValue={selectedUser.name} required/></Field><Field label="Email login"><Input name="email" type="email" defaultValue={selectedUser.email} required/></Field><Field label="Mobile number"><Input name="phone" inputMode="tel" defaultValue={selectedUser.phone || ""} placeholder="+919876543210"/></Field><Field label="System role"><Select name="role" value={selectedRole} onChange={event => setSelectedRole(event.target.value)}>{manageableRoles.map(role => <option key={role} value={role}>{roles[role]}</option>)}</Select></Field><Field label="Employee code"><Input name="employee_code" defaultValue={profile?.employee_code || ""} required/></Field><Field label="Designation"><Input name="designation" defaultValue={profile?.designation || ""} required/></Field><Field label="Department"><Input name="department" defaultValue={profile?.department || ""}/></Field>{roleChanged && <Field className="sm:col-span-2" label="Reason for role change" hint="Role changes are written to account history."><Input name="reason" placeholder="Explain why access responsibility is changing" minLength={4} required/></Field>}</section><CapabilityPreview definition={definition}/><ChannelPanel profile={profile} phone={selectedUser.phone}/><section className="rounded-[22px] border border-slate-200 bg-slate-50 p-4"><div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 shrink-0 text-amber-600" size={19}/><div><h3 className="font-black text-slate-950">Employment lifecycle</h3><p className="mt-1 text-sm leading-6 text-slate-600">Offboarding blocks Supabase and portal access but retains accountable business history. Permanent deletion is limited to inactive, unused test or duplicate accounts.</p></div></div></section><FormActions>{selectedUser.active ? <Button type="button" variant="danger" onClick={() => setLifecycleMode("offboard")}><UserX size={17}/>Offboard</Button> : <><Button type="button" variant="secondary" onClick={() => setLifecycleMode("restore")}><RotateCcw size={17}/>Restore</Button>{canDelete && <Button type="button" variant="danger" onClick={() => setLifecycleMode("delete")}><Trash2 size={17}/>Delete unused account</Button>}</>}<Button type="submit"><Save size={17}/>Save changes</Button></FormActions></form> : <div className="grid gap-4"><CapabilityPreview definition={roleDefinition(catalog, selectedUser.role)}/>{isSelf && <MyTelegramPanel/>}<div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-600">{isSelf ? "This is your own account. Your role and account status are managed by a higher authority; you can connect your own Telegram above." : "This identity is visible for context but falls outside your management authority."}</div></div>}{canManage && selectedUser.active && <PasswordPanel person={selectedUser} action={action}/>}<section className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4 sm:p-5"><div className="flex items-center justify-between gap-3"><div><p className="text-xs font-black uppercase tracking-[.16em] text-slate-500">Account trail</p><h3 className="mt-1 font-black text-slate-950">Recent activity</h3></div><Activity className="text-blue-600" size={20}/></div><div className="mt-4 grid gap-2">{events.length ? events.slice(0, 6).map(item => <article key={item.id} className="grid grid-cols-[auto_1fr] gap-3 rounded-2xl bg-white p-3 shadow-sm"><span className="mt-0.5 grid size-8 place-items-center rounded-xl bg-slate-100 text-slate-500"><Clock3 size={15}/></span><div><strong className="block text-xs text-slate-900">{item.event_type.replaceAll("_", " ")}</strong><p className="mt-1 text-xs leading-5 text-slate-500">{item.reason}</p><time className="mt-1 block text-[11px] font-semibold text-slate-400">{new Date(item.created_at).toLocaleString("en-GB")}</time></div></article>) : <p className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">No account changes recorded yet.</p>}</div></section></div></Modal>{lifecycleMode && <LifecycleModal mode={lifecycleMode} person={selectedUser} onClose={() => setLifecycleMode("")} onConfirm={applyLifecycle} loading={lifecycleBusy}/>}</>;
}
export function EditMyProfileModal({ user, onClose, action }) {
  async function save(event) {
    event.preventDefault();
    const result = await action(() => usersApi.updateMe(Object.fromEntries(new FormData(event.currentTarget))), "Profile updated");
    if (result?.ok !== false) onClose();
  }
  return <Modal title="Edit personal details" subtitle="Keep your contact identity accurate for project coordination." onClose={onClose}><form className="grid gap-5" onSubmit={save}><IdentityBand person={user}/><section className="grid gap-4 rounded-[22px] border border-slate-200 p-4 sm:p-5"><Field label="Full name"><Input name="name" defaultValue={user.name} required/></Field><Field label="Mobile number"><Input name="phone" inputMode="tel" defaultValue={user.phone || ""} placeholder="+919876543210"/></Field></section><FormActions><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit"><Save size={17}/>Save profile</Button></FormActions></form></Modal>;
}

