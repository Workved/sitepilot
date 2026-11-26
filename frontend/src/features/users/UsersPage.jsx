import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Check, ChevronRight, CircleUserRound, Pencil, Search, UserPlus, UsersRound } from "lucide-react";
import { Button, Pill } from "../../components/ui";
import { projectsApi } from "../../api/projectsApi";
import { usersApi } from "../../api/usersApi";
import { useRoute } from "../../lib/route";
import { cn } from "../../utils/cn";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";
import { AccountStatus, CreateUserModal, EditMyProfileModal } from "./components/UserModals";
import { lastActiveLabel, PersonPanel } from "./components/PersonPanel";
import { ATTENTION, attentionFor, filterPeople, ROLE_ORDER, sortPeople, STATUS_FILTERS, summaryLine } from "./teamHelpers";

const managementRoles = new Set(["super_admin", "admin"]);
const COLUMNS = "md:grid-cols-[minmax(0,1.6fr)_8.5rem_minmax(0,1fr)_8rem_8.5rem_1.25rem]";

function Avatar({ name, large = false }) {
  return <span className={`grid shrink-0 place-items-center bg-blue-50 font-medium text-blue-800 ${large ? "size-16 rounded-[18px] text-lg" : "size-9 rounded-[10px] text-xs"}`}>{initials(name)}</span>;
}

function WhatsAppState({ person }) {
  return person.phone
    ? <span className="inline-flex items-center gap-1 text-[13px] text-slate-700"><Check size={14} className="text-ok" aria-hidden="true"/>Ready</span>
    : <span className="text-[13px] text-orange-700">No mobile</span>;
}

const PROBLEM_SHORT = { not_signed_in: "Never signed in", no_phone: "No mobile", no_profile: "No employee profile" };

function PersonRow({ person, isSelf, selected, onOpen }) {
  const profile = person.employee_profile;
  const flags = attentionFor(person);
  const lastActive = lastActiveLabel(person).replace(/^Active /, "");
  return <button type="button" onClick={onOpen} aria-label={`Open ${person.name}`} aria-current={selected ? "true" : undefined}
    className={cn("grid w-full items-center gap-x-4 px-4 py-3 text-left transition-colors hover:bg-slate-50 md:px-5", COLUMNS, selected && "bg-slate-100", !person.active && "opacity-60")}>
    <span className="flex min-w-0 items-center gap-3">
      <Avatar name={person.name}/>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 text-sm text-slate-950"><span className="truncate">{person.name}</span>{isSelf && <Pill tone="gray" className="shrink-0">You</Pill>}{flags.length > 0 && <span className="size-1.5 shrink-0 rounded-full bg-orange-500" title="Needs attention" aria-label="Needs attention"/>}</span>
        <span className="block truncate text-xs text-slate-500">{person.email}</span>
        {/* Phones: one compact line instead of four stacked cells. */}
        <span className="mt-0.5 block truncate text-xs text-slate-500 md:hidden">
          {roles[person.role] || person.role} · {lastActive}
          {flags.filter(key => key !== "not_signed_in").map(key => <span key={key} className="text-orange-700"> · {PROBLEM_SHORT[key]}</span>)}
        </span>
      </span>
      <ChevronRight size={16} className="shrink-0 text-slate-400 md:hidden" aria-hidden="true"/>
    </span>
    <span className="hidden text-[13px] text-slate-700 md:block">{roles[person.role] || person.role}</span>
    <span className="hidden min-w-0 md:block">
      {profile
        ? <><span className="block truncate text-[13px] text-slate-950">{profile.designation}</span><span className="block truncate text-xs tabular-nums text-slate-500">{profile.employee_code}</span></>
        : <span className={cn("text-[13px]", flags.includes("no_profile") ? "text-orange-700" : "text-slate-400")}>No employee profile</span>}
    </span>
    <span className="hidden md:block"><WhatsAppState person={person}/></span>
    <span className={cn("hidden text-[13px] md:block", person.last_login_at ? "text-slate-700" : "text-slate-400")}>{lastActive}</span>
    <ChevronRight size={16} className="hidden text-slate-400 md:block" aria-hidden="true"/>
  </button>;
}

function TeamDirectory({ data, user, action }) {
  const people = useMemo(() => data.users || [], [data.users]);
  const catalog = data.access_catalog || [];
  const manageableRoles = data.manageable_roles || [];
  const [route, setRoute] = useRoute();
  const [inviting, setInviting] = useState(false);
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("all");
  const [status, setStatus] = useState("active");
  const [attention, setAttention] = useState("");
  const [sort, setSort] = useState({ key: "name", direction: "asc" });
  const [rolesOpen, setRolesOpen] = useState(false);

  const selected = people.find(person => person.id === route.person) || null;
  const openPerson = id => setRoute({ person: id || "" });

  async function invite(event) {
    event.preventDefault();
    const result = await action(() => usersApi.invite(Object.fromEntries(new FormData(event.currentTarget))), "Added - they can sign in now");
    if (result?.ok !== false) setInviting(false);
  }

  const shown = useMemo(() => sortPeople(filterPeople(people, { query, role, status, attention }), sort.key, sort.direction), [people, query, role, status, attention, sort]);
  const inStatus = useMemo(() => filterPeople(people, { status }), [people, status]);
  const roleCounts = Object.fromEntries(ROLE_ORDER.map(key => [key, inStatus.filter(person => person.role === key).length]));
  const attentionCounts = ATTENTION.map(([key, many, one, test]) => ({ key, many, one, count: people.filter(test).length })).filter(item => item.count > 0);
  const filtersOn = Boolean(query || role !== "all" || status !== "active" || attention);

  function toggleSort(key) {
    setSort(current => current.key === key ? { key, direction: current.direction === "asc" ? "desc" : "asc" } : { key, direction: key === "last_active" ? "desc" : "asc" });
  }
  function clearFilters() { setQuery(""); setRole("all"); setStatus("active"); setAttention(""); }

  const SortButton = ({ column, label }) => {
    const active = sort.key === column;
    return <button type="button" onClick={() => toggleSort(column)} aria-label={`Sort by ${label}`} className={cn("inline-flex items-center gap-1 text-left hover:text-slate-950", active && "text-slate-950")}>
      {label}{active && (sort.direction === "asc" ? <ArrowUp size={13}/> : <ArrowDown size={13}/>)}
    </button>;
  };

  return <div className="grid gap-4">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-[17px] font-medium text-slate-950">Team</h2>
        <p className="mt-0.5 text-sm text-slate-500">{summaryLine(people)}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => openPerson(user.id)}><CircleUserRound size={17}/> My profile</Button>
        {manageableRoles.length > 0 && <Button onClick={() => setInviting(true)}><UserPlus size={17}/> Add team member</Button>}
      </div>
    </header>

    {attentionCounts.length > 0 && <section aria-label="Needs attention" className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-sm text-slate-500">Needs attention:</span>
      {attentionCounts.map(item => <button key={item.key} type="button" aria-pressed={attention === item.key}
        onClick={() => { setAttention(attention === item.key ? "" : item.key); if (attention !== item.key) setStatus("active"); }}
        className={cn("h-8 rounded-full px-3 text-[13px] transition", attention === item.key ? "bg-slate-950 text-white" : "bg-orange-50 text-orange-800 hover:bg-orange-100")}>
        {item.count} {item.count === 1 ? item.one : item.many}
      </button>)}
    </section>}

    <div className="grid gap-2 rounded-[20px] border border-line bg-white p-2">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-[220px] flex-1">
          <span className="sr-only">Search people</span>
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
          <input value={query} onChange={event => setQuery(event.target.value)} autoComplete="off" placeholder="Search name, email, phone or employee code"
            className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-950 outline-none placeholder:text-slate-400 focus:border-blue-600 focus:bg-white"/>
        </label>
        <div role="group" aria-label="Account status" className="so-scroll flex max-w-full gap-0.5 overflow-x-auto rounded-[10px] bg-slate-100 p-[3px]">
          {STATUS_FILTERS.map(([value, label]) => <button key={value} type="button" aria-pressed={status === value} onClick={() => setStatus(value)}
            className={cn("h-8 shrink-0 whitespace-nowrap rounded-lg px-2.5 text-[13px] transition", status === value ? "bg-white text-slate-950 shadow-[0_1px_3px_rgba(21,23,26,.12)]" : "text-slate-500 hover:text-slate-950")}>{label}</button>)}
        </div>
        {filtersOn && <button type="button" onClick={clearFilters} className="h-9 rounded-lg px-2 text-[13px] text-slate-600 hover:bg-slate-100">Clear</button>}
      </div>
      <div role="group" aria-label="Role" className="flex flex-wrap gap-1 px-0.5 pb-0.5">
        <button type="button" aria-pressed={role === "all"} onClick={() => setRole("all")}
          className={cn("h-8 rounded-full px-3 text-[13px] transition", role === "all" ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-600 hover:text-slate-950")}>
          All <span className={cn("tabular-nums", role === "all" ? "text-white/70" : "text-slate-400")}>{inStatus.length}</span>
        </button>
        {ROLE_ORDER.filter(key => roleCounts[key] > 0 || role === key).map(key => <button key={key} type="button" aria-pressed={role === key} onClick={() => setRole(role === key ? "all" : key)}
          className={cn("h-8 rounded-full px-3 text-[13px] transition", role === key ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-600 hover:text-slate-950")}>
          {roles[key]} <span className={cn("tabular-nums", role === key ? "text-white/70" : "text-slate-400")}>{roleCounts[key]}</span>
        </button>)}
      </div>
    </div>

    <section aria-label="People" className="overflow-hidden rounded-[20px] border border-line bg-white">
      {shown.length === 0
        ? <div className="grid place-items-center px-5 py-14 text-center">
            <UsersRound size={26} className="text-slate-300" aria-hidden="true"/>
            <h3 className="mt-3 text-sm text-slate-950">No one matches</h3>
            <p className="mt-1 max-w-xs text-sm text-slate-500">Try a different search, role or status.</p>
            {filtersOn && <Button variant="secondary" size="sm" className="mt-3" onClick={clearFilters}>Clear filters</Button>}
          </div>
        : <>
          <div className={cn("hidden gap-x-4 border-b border-line bg-slate-50 px-5 py-2.5 text-[13px] text-slate-500 md:grid", COLUMNS)}>
            <SortButton column="name" label="Person"/><SortButton column="role" label="Role"/><span>Employee profile</span><span>WhatsApp</span><SortButton column="last_active" label="Last active"/><span className="sr-only">Open</span>
          </div>
          <div className="divide-y divide-line">
            {shown.map(person => <PersonRow key={person.id} person={person} isSelf={person.id === user.id} selected={person.id === route.person} onOpen={() => openPerson(person.id)}/>)}
          </div>
          <footer className="border-t border-line bg-slate-50 px-5 py-2.5 text-xs text-slate-500">Showing {shown.length} of {people.length}</footer>
        </>}
    </section>

    <section aria-label="What each role can do" className="rounded-[20px] border border-line bg-white">
      <button type="button" aria-expanded={rolesOpen} onClick={() => setRolesOpen(value => !value)} className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left text-sm text-slate-700">
        What each role can do
        <ChevronRight size={16} className={cn("text-slate-400 transition", rolesOpen && "rotate-90")} aria-hidden="true"/>
      </button>
      {rolesOpen && <ul className="divide-y divide-line border-t border-line">
        {catalog.map(item => <li key={item.role} className="grid gap-1 px-5 py-3.5 sm:grid-cols-[10rem_minmax(0,1fr)_auto] sm:items-baseline sm:gap-4">
          <span className="text-sm text-slate-950">{item.label}</span>
          <span className="text-[13px] leading-5 text-slate-600">{item.summary}{item.capabilities?.length ? ` ${item.capabilities.join(", ")}.` : ""}</span>
          <span className="text-xs text-slate-500">{manageableRoles.includes(item.role) ? "You can manage" : "Managed above you"}</span>
        </li>)}
      </ul>}
    </section>

    {selected && <PersonPanel key={selected.id} person={selected} actor={user} catalog={catalog} manageableRoles={manageableRoles} action={action} onClose={() => openPerson("")}/>}
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
  return managementRoles.has(props.user.role) ? <TeamDirectory {...props}/> : <PersonalProfile {...props}/>;
}
