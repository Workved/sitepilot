import { useEffect, useMemo, useState } from "react";
import {
  BadgeCheck,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  CircleUserRound,
  Pencil,
  Search,
  ShieldCheck,
  UserPlus,
  UsersRound,
} from "lucide-react";
import { Button, Input, Pill, RefreshButton } from "../../components/ui";
import { projectsApi } from "../../api/projectsApi";
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
  return <article className="rounded-[20px] border border-line bg-white p-4 sm:p-5"><span className={`grid size-10 place-items-center rounded-2xl ${tones[tone]}`}>{icon}</span><strong className="mt-5 block text-3xl font-normal tracking-[-.04em] text-slate-950">{value}</strong><span className="mt-1 block text-sm font-semibold text-slate-500">{label}</span></article>;
}

function EmptyState() {
  return <div className="grid place-items-center px-5 py-16 text-center"><span className="grid size-14 place-items-center rounded-[20px] bg-slate-100 text-slate-400"><UsersRound size={25}/></span><h3 className="mt-4 font-medium text-slate-900">No matching identities</h3><p className="mt-1 max-w-xs text-sm leading-6 text-slate-500">Try a different name, email, or role filter.</p></div>;
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

    <section className="grid gap-3 lg:grid-cols-3">{catalog.map(item => <article key={item.role} className="rounded-[20px] border border-line bg-white p-5"><div className="flex items-start justify-between gap-3"><span className="grid size-10 place-items-center rounded-2xl bg-blue-50 text-blue-700"><ShieldCheck size={19}/></span><Pill tone={manageableRoles.includes(item.role) ? "blue" : "gray"}>{manageableRoles.includes(item.role) ? "Manageable" : "Fixed"}</Pill></div><h3 className="mt-4 font-medium text-slate-950">{item.label}</h3><p className="mt-1 text-sm leading-6 text-slate-500">{item.summary}</p></article>)}</section>

    {selected && <UserModal selectedUser={selected} actor={user} catalog={catalog} manageableRoles={manageableRoles} onClose={() => setSelected(null)} action={action}/>}
    {inviting && <CreateUserModal create={invite} catalog={catalog} manageableRoles={manageableRoles} onClose={() => setInviting(false)}/>}
  </div>;
}

const PROJECT_ROLE_LABEL = { project_manager: "Project manager", site_supervisor: "Site supervisor", internal_employee: "Support employee" };
const PROJECT_STATUS_TONE = { active: "green", draft: "gray", on_hold: "orange", completed: "blue", archived: "gray" };

// The projects this person is a current member of, with their role on each.
function MyProjects({ user, onOpenProject }) {
  const [state, setState] = useState({ loading: true, items: [] });
  useEffect(() => {
    let alive = true;
    projectsApi.list().then(list => {
      if (!alive) return;
      const items = list.map(project => ({
        project,
        role: (project.memberships || []).find(m => m.user_id === user.id && !m.ends_at)?.project_role,
      })).filter(item => item.role);
      setState({ loading: false, items });
    }).catch(() => alive && setState({ loading: false, items: [] }));
    return () => { alive = false; };
  }, [user.id]);

  return <section aria-label="Your projects" className="rounded-[20px] border border-line bg-white">
    <header className="flex items-baseline justify-between gap-3 border-b border-line px-5 py-4">
      <h3 className="text-[15px] font-medium text-slate-950">Your projects</h3>
      {!state.loading && <span className="text-sm text-slate-500">{state.items.length}</span>}
    </header>
    {state.loading
      ? <p className="px-5 py-6 text-sm text-slate-500">Loading projects…</p>
      : !state.items.length
        ? <p className="px-5 py-6 text-sm text-slate-500">You aren't on any project yet. An admin adds you when a project is set up.</p>
        : <ul className="divide-y divide-line">{state.items.map(({ project, role }) => <li key={project.id}>
            <button type="button" onClick={() => onOpenProject?.(project.code)} className="flex w-full items-center gap-3 px-5 py-3 text-left transition hover:bg-slate-50">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-slate-950">{project.name}</span>
                <span className="block truncate text-xs text-slate-500">{PROJECT_ROLE_LABEL[role] || role} · {project.code}</span>
              </span>
              <Pill tone={PROJECT_STATUS_TONE[project.status] || "gray"}>{String(project.status).replaceAll("_", " ")}</Pill>
              <ChevronRight size={16} className="shrink-0 text-slate-400" aria-hidden="true"/>
            </button>
          </li>)}</ul>}
  </section>;
}

function PersonalProfile({ data, user, action, onOpenProject }) {
  const [editing, setEditing] = useState(false);
  const definition = (data.access_catalog || []).find(item => item.role === user.role) || { label: roles[user.role] || user.role, summary: "Role-based SiteOps access.", capabilities: [] };
  const profile = user.employee_profile || {};
  const details = [
    ["Email login", user.email],
    ["Mobile number", user.phone || null],
    ["Employee code", profile.employee_code || "Not assigned"],
    ["Designation", profile.designation || definition.label],
    ["Department", profile.department || "Not set"],
  ];

  return <div className="grid gap-4">
    <header className="flex flex-wrap items-center gap-4">
      <Avatar name={user.name} large/>
      <div className="min-w-0 flex-1 basis-[12rem]">
        <h2 className="text-2xl font-light tracking-[-0.01em] text-slate-950">{user.name}</h2>
        <div className="mt-1.5 flex flex-wrap items-center gap-2"><Pill>{definition.label}</Pill><AccountStatus person={user}/></div>
      </div>
      <Button variant="secondary" onClick={() => setEditing(true)}><Pencil size={16}/> Edit contact details</Button>
    </header>

    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <div className="grid content-start gap-4">
        <section aria-label="Contact and identity" className="rounded-[20px] border border-line bg-white">
          <h3 className="border-b border-line px-5 py-4 text-[15px] font-medium text-slate-950">Contact and identity</h3>
          <dl className="divide-y divide-line">
            {details.map(([label, value]) => <div key={label} className="flex items-center justify-between gap-4 px-5 py-3">
              <dt className="text-sm text-slate-500">{label}</dt>
              <dd className="min-w-0 truncate text-right text-sm text-slate-950">
                {value ?? <button type="button" onClick={() => setEditing(true)} className="text-blue-700 hover:underline">Add mobile number</button>}
              </dd>
            </div>)}
          </dl>
          <p className="flex items-start gap-2 border-t border-line px-5 py-3 text-xs leading-5 text-slate-500"><CircleUserRound size={14} className="mt-0.5 shrink-0" aria-hidden="true"/>You can change your name and mobile number. Role, employee code, designation and department are set by an admin.</p>
        </section>
        <MyProjects user={user} onOpenProject={onOpenProject}/>
      </div>

      <section aria-label="What you can do" className="h-fit rounded-[20px] border border-line bg-white p-5">
        <h3 className="text-[15px] font-medium text-slate-950">What you can do as {definition.label}</h3>
        <p className="mt-1 text-sm leading-6 text-slate-500">{definition.summary}</p>
        <ul className="mt-4 grid gap-2.5">
          {definition.capabilities.map(item => <li key={item} className="flex items-start gap-2.5 text-sm text-slate-800">
            <Check size={16} className="mt-0.5 shrink-0 text-ok" aria-hidden="true"/>{item}
          </li>)}
        </ul>
      </section>
    </div>
    {editing && <EditMyProfileModal user={user} action={action} onClose={() => setEditing(false)}/>}
  </div>;
}

export function UsersPage(props) {
  return managementRoles.has(props.user.role) ? <AccessDirectory {...props}/> : <PersonalProfile {...props}/>;
}
