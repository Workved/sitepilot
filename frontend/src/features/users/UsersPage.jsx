import { useMemo, useState } from "react";
import {
  BadgeCheck,
  BriefcaseBusiness,
  ChevronRight,
  CircleUserRound,
  Mail,
  Pencil,
  Phone,
  Search,
  ShieldCheck,
  UserPlus,
  UsersRound,
} from "lucide-react";
import { Button, Input, Pill, RefreshButton } from "../../components/ui";
import { usersApi } from "../../api/usersApi";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";
import { CreateUserModal, EditMyProfileModal, UserModal } from "./components/UserModals";

const managementRoles = new Set(["super_admin", "admin"]);

function Avatar({ name, large = false }) {
  return <span className={`grid shrink-0 place-items-center bg-blue-100 font-medium text-blue-800 ${large ? "size-16 rounded-[18px] text-lg" : "size-11 rounded-xl text-sm"}`}>{initials(name)}</span>;
}

function AccountStatus({ person }) {
  if (!person.active) return <Pill tone="gray">Offboarded</Pill>;
  if (person.activation_status === "setup_pending") return <Pill tone="orange">Setup pending</Pill>;
  return <Pill tone="green">Active</Pill>;
}

function Metric({ icon, label, value, tone = "blue" }) {
  const tones = {
    blue: "bg-blue-50 text-blue-700",
    green: "bg-emerald-50 text-emerald-700",
    violet: "bg-violet-50 text-violet-700",
  };
  return <article className="rounded-[22px] border border-slate-200 bg-white p-4 sm:p-5"><span className={`grid size-10 place-items-center rounded-2xl ${tones[tone]}`}>{icon}</span><strong className="mt-5 block text-3xl font-normal tracking-[-.04em] text-slate-950">{value}</strong><span className="mt-1 block text-sm font-semibold text-slate-500">{label}</span></article>;
}

function EmptyState() {
  return <div className="grid place-items-center px-5 py-16 text-center"><span className="grid size-14 place-items-center rounded-[20px] bg-slate-100 text-slate-400"><UsersRound size={25}/></span><h3 className="mt-4 font-black text-slate-900">No matching identities</h3><p className="mt-1 max-w-xs text-sm leading-6 text-slate-500">Try a different name, email, or role filter.</p></div>;
}

function AccessDirectory({ data, user, action, onRefresh }) {
  const users = data.users || [];
  const catalog = data.access_catalog || [];
  const manageableRoles = data.manageable_roles || [];
  const [selected, setSelected] = useState(null);
  const [inviting, setInviting] = useState(false);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("active");

  async function invite(event) {
    event.preventDefault();
    const result = await action(() => usersApi.invite(Object.fromEntries(new FormData(event.currentTarget))), "Added to roster - they can now sign in");
    if (result?.ok !== false) { setInviting(false); onRefresh?.(); }
  }

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return users.filter(item => {
      const matchesText = !needle || [item.name, item.email, item.phone, item.employee_profile?.employee_code, item.employee_profile?.designation].some(value => String(value || "").toLowerCase().includes(needle));
      const matchesRole = roleFilter === "all" || item.role === roleFilter;
      const matchesStatus = statusFilter === "all" || (statusFilter === "active" ? item.active : !item.active);
      return matchesText && matchesRole && matchesStatus;
    });
  }, [users, query, roleFilter, statusFilter]);

  const activeCount = users.filter(item => item.active).length;
  const profiledCount = users.filter(item => item.employee_profile).length;

  return <div className="grid gap-5 sm:gap-6">
    <section className="rounded-[22px] border border-line bg-white px-5 py-6 sm:px-7">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="text-xs font-medium text-slate-500">Identity and access</p><h2 className="mt-1 text-[28px] font-normal tracking-[-0.02em] text-slate-950">Users & Access</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">One auditable directory for employee identity, fixed role boundaries, and account status.</p></div>
        <div className="flex flex-wrap items-center gap-2"><Pill tone="blue">Google or password sign-in</Pill><Button onClick={() => setInviting(true)}><UserPlus size={17}/>Add team member</Button>{onRefresh && <RefreshButton onClick={onRefresh}/>}</div>
      </div>
    </section>

    <section className="grid grid-cols-2 gap-3 lg:grid-cols-3">
      <Metric icon={<UsersRound size={19}/>} label="Total identities" value={users.length}/>
      <Metric icon={<BadgeCheck size={19}/>} label="Active access" value={activeCount} tone="green"/>
      <div className="col-span-2 lg:col-span-1"><Metric icon={<BriefcaseBusiness size={19}/>} label="Employee profiles" value={profiledCount} tone="violet"/></div>
    </section>

    <section className="overflow-hidden rounded-[26px] border border-slate-200 bg-white">
      <div className="grid gap-3 border-b border-slate-200 p-4 sm:grid-cols-[minmax(0,1fr)_180px_180px] sm:p-5">
        <label className="relative"><Search className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18}/><Input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search name, email or employee code" className="pl-11"/></label>
        <select value={roleFilter} onChange={event => setRoleFilter(event.target.value)} className="min-h-12 rounded-xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"><option value="all">All roles</option>{catalog.map(item => <option key={item.role} value={item.role}>{item.label}</option>)}</select><select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className="min-h-12 rounded-xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"><option value="active">Active employees</option><option value="inactive">Offboarded employees</option><option value="all">All account statuses</option></select>
      </div>

      {filtered.length === 0 ? <EmptyState/> : <>
        <div className="divide-y divide-slate-100 md:hidden">{filtered.map(item => <button type="button" key={item.id} onClick={() => setSelected(item)} className="flex w-full items-center gap-3 p-4 text-left transition active:bg-blue-50"><Avatar name={item.name}/><span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><strong className="truncate text-sm text-slate-950">{item.name}</strong><AccountStatus person={item}/></span><span className="mt-1 block truncate text-xs text-slate-500">{item.email}</span><span className="mt-1 block text-xs font-bold text-blue-700">{roles[item.role] || item.role}</span></span><ChevronRight className="shrink-0 text-slate-400" size={20}/></button>)}</div>
        <div className="hidden overflow-x-auto md:block"><table className="w-full min-w-[880px] text-left"><thead className="bg-slate-50 text-xs font-medium text-slate-500"><tr><th className="px-5 py-4">Identity</th><th className="px-5 py-4">Role</th><th className="px-5 py-4">Employee profile</th><th className="px-5 py-4">Status</th><th className="px-5 py-4 text-right">View</th></tr></thead><tbody className="divide-y divide-slate-100">{filtered.map(item => <tr key={item.id} onClick={() => setSelected(item)} className="cursor-pointer transition hover:bg-blue-50/50"><td className="px-5 py-4"><span className="flex items-center gap-3"><Avatar name={item.name}/><span className="min-w-0"><strong className="block truncate text-sm text-slate-950">{item.name}</strong><small className="mt-1 block truncate text-xs text-slate-500">{item.email}</small></span></span></td><td className="px-5 py-4"><Pill>{roles[item.role] || item.role}</Pill></td><td className="px-5 py-4"><strong className="block text-sm text-slate-700">{item.employee_profile?.designation || "Profile pending"}</strong><small className="mt-1 block text-xs text-slate-500">{item.employee_profile?.employee_code || "No employee code"}</small></td><td className="px-5 py-4"><span className="flex flex-wrap items-center gap-2"><AccountStatus person={item}/></span></td><td className="px-5 py-4 text-right"><ChevronRight className="ml-auto text-slate-400" size={20}/></td></tr>)}</tbody></table></div>
      </>}
    </section>

    <section className="grid gap-3 lg:grid-cols-3">{catalog.map(item => <article key={item.role} className="rounded-[22px] border border-slate-200 bg-white p-5"><div className="flex items-start justify-between gap-3"><span className="grid size-10 place-items-center rounded-2xl bg-blue-50 text-blue-700"><ShieldCheck size={19}/></span><Pill tone={manageableRoles.includes(item.role) ? "blue" : "gray"}>{manageableRoles.includes(item.role) ? "Manageable" : "Fixed"}</Pill></div><h3 className="mt-4 font-black text-slate-950">{item.label}</h3><p className="mt-1 text-sm leading-6 text-slate-500">{item.summary}</p></article>)}</section>

    {selected && <UserModal selectedUser={selected} actor={user} catalog={catalog} manageableRoles={manageableRoles} onClose={() => setSelected(null)} action={action}/>}
    {inviting && <CreateUserModal create={invite} catalog={catalog} manageableRoles={manageableRoles} onClose={() => setInviting(false)}/>}
  </div>;
}

function PersonalProfile({ data, user, action }) {
  const [editing, setEditing] = useState(false);
  const definition = (data.access_catalog || []).find(item => item.role === user.role) || { label: roles[user.role] || user.role, summary: "Role-based SiteOps access.", capabilities: [] };
  const profile = user.employee_profile || {};
  const detailRows = [
    ["Email login", user.email, <Mail size={17}/>],
    ["Mobile number", user.phone || "Not provided", <Phone size={17}/>],
    ["Employee code", profile.employee_code || "Not assigned", <BadgeCheck size={17}/>],
    ["Designation", profile.designation || definition.label, <BriefcaseBusiness size={17}/>],
  ];

  return <div className="grid gap-5 sm:gap-6">
    <section className="rounded-[22px] border border-line bg-white p-5 sm:p-7">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center"><Avatar name={user.name} large/><div className="min-w-0 flex-1"><p className="text-xs font-medium text-slate-500">My profile</p><h2 className="mt-1 truncate text-[28px] font-normal tracking-[-0.02em] text-slate-950">{user.name}</h2><div className="mt-2 flex flex-wrap items-center gap-2"><Pill>{definition.label}</Pill><AccountStatus person={user}/></div></div><div className="flex flex-wrap gap-2"><Button onClick={() => setEditing(true)}><Pencil size={17}/>Edit profile</Button></div></div>
    </section>

    <section className="grid gap-4 lg:grid-cols-[1.1fr_.9fr]">
      <article className="rounded-[26px] border border-slate-200 bg-white p-5 sm:p-6"><p className="text-xs font-medium text-slate-500">Employee identity</p><div className="mt-5 grid gap-3 sm:grid-cols-2">{detailRows.map(([label, value, icon]) => <div key={label} className="rounded-[20px] bg-slate-50 p-4"><span className="flex items-center gap-2 text-xs font-medium text-slate-500">{icon}{label}</span><strong className="mt-3 block break-words text-sm text-slate-900">{value}</strong></div>)}</div></article>
      <article className="rounded-[26px] border border-blue-100 bg-blue-50/70 p-5 sm:p-6"><span className="grid size-11 place-items-center rounded-2xl bg-blue-600 text-white"><ShieldCheck size={21}/></span><p className="mt-5 text-xs font-medium text-slate-500">Your access boundary</p><h2 className="mt-1 text-xl font-black text-slate-950">{definition.label}</h2><p className="mt-2 text-sm leading-6 text-slate-600">{definition.summary}</p><div className="mt-5 grid gap-2">{definition.capabilities.map(item => <span key={item} className="rounded-xl bg-white px-3 py-2 text-sm font-bold text-slate-700 shadow-sm">{item}</span>)}</div></article>
    </section>

    <section className="flex items-start gap-3 rounded-[22px] border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-600 sm:p-5"><CircleUserRound className="mt-0.5 shrink-0 text-blue-600" size={20}/><p>You can update personal contact details here. Role, employee code, designation, department, and account status are controlled by authorized administrators.</p></section>
    {editing && <EditMyProfileModal user={user} action={action} onClose={() => setEditing(false)}/>}
  </div>;
}

export function UsersPage(props) {
  return managementRoles.has(props.user.role) ? <AccessDirectory {...props}/> : <PersonalProfile {...props}/>;
}
