import { useEffect, useRef, useState } from "react";
import { ArrowLeftRight, Building2, ChevronRight, ClipboardList, FolderKanban, KeyRound, Mail, MapPin, MessageCircle, MoreVertical, Pencil, Phone, Plus, ShieldAlert, ShieldCheck, ShieldOff, Ban, Unlink, UserRound, UsersRound, Wrench, X } from "lucide-react";
import { channelToggleApi } from "../../../api/channelToggleApi";
import { telegramConnectApi } from "../../../api/telegramConnectApi";
import { Button, ConfirmModal, Pill } from "../../../components/ui";
import { ContactWorkSummary } from "./ContactWorkSummary";
import { BlacklistBanner, BlacklistPill, canBlacklist, canUnblacklist, isBlocked } from "./VendorBlacklist";
import { VendorWorkHistory } from "./VendorWorkHistory";

const cleanPhone = (value = "") => value.replace(/[^\d+]/g, "");
const projectStatusLabel = value => ({ draft: "Draft", active: "Active", on_hold: "On hold", completed: "Completed", archived: "Archived" }[value] || value);

function ContactActions({ contact, labels = true }) {
  if (!contact) return null;
  return <div className="flex flex-wrap gap-2"><a className="flex min-h-10 items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 text-xs font-black text-blue-700 transition hover:bg-blue-100" href={`tel:${cleanPhone(contact.phone)}`}><Phone size={16}/>{labels && "Call"}</a><a className="flex min-h-10 items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-xs font-black text-emerald-700 transition hover:bg-emerald-100" href={`https://wa.me/${cleanPhone(contact.whatsapp || contact.phone).replace("+", "")}`} target="_blank" rel="noreferrer"><MessageCircle size={16}/>{labels && "WhatsApp"}</a></div>;
}

function EmptyPanel({ icon: Icon, title, text, action }) {
  return <div className="grid min-h-64 place-items-center rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 p-8 text-center"><div><span className="mx-auto grid size-12 place-items-center rounded-2xl bg-white text-slate-400 shadow-sm"><Icon/></span><h4 className="mt-4 font-black text-slate-900">{title}</h4><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">{text}</p>{action}</div></div>;
}

function DetailItem({ icon: Icon, label, value }) {
  return <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4"><span className="grid size-9 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-600"><Icon size={16}/></span><div className="min-w-0"><span className="block text-[10px] font-black uppercase tracking-[0.16em] text-slate-400">{label}</span><strong className="mt-1 block break-words text-sm leading-6 text-slate-800">{value || "Not provided"}</strong></div></div>;
}

function CapabilityGroups({ vendor, categories }) {
  const selected = new Set(vendor.category_ids || []);
  const roots = categories
    .filter(category => !category.parent_id && (selected.has(category.id) || categories.some(child => child.parent_id === category.id && selected.has(child.id))))
    .map(root => ({ root, children: categories.filter(child => child.parent_id === root.id && selected.has(child.id)) }));
  return <section className="rounded-2xl border border-blue-200 bg-blue-50/70 p-5">
    <header className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-blue-700 text-white"><Wrench size={18}/></span><div><p className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-500">Capabilities</p><h4 className="font-black text-slate-950">Categories selected</h4></div></header>
    <div className="mt-4 grid gap-2">{roots.map(({ root, children }) => <div key={root.id} className="rounded-xl border border-white/80 bg-white/80 p-3 shadow-sm"><strong className="text-sm text-slate-900">{root.name}</strong>{children.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{children.map(child => <span key={child.id} className="rounded-full bg-blue-100 px-2.5 py-1 text-[11px] font-bold text-blue-900">{child.name}</span>)}</div>}</div>)}{!roots.length && <p className="rounded-xl border border-dashed border-slate-300/80 p-4 text-sm text-slate-500">No capabilities selected.</p>}</div>
  </section>;
}

function VendorProjectMappingForm({ vendor, unmappedProjects, mapToProjects }) {
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  function toggle(projectId) {
    setSelectedIds(current => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId); else next.add(projectId);
      return next;
    });
  }

  async function submit() {
    setSubmitting(true);
    setError("");
    try {
      const result = await mapToProjects(Array.from(selectedIds));
      if (result?.ok === false) setError(result?.error || "This vendor could not be mapped to the selected project(s).");
      else setSelectedIds(new Set());
    } catch (caught) {
      setError(caught?.message || "This vendor could not be mapped to the selected project(s).");
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4">
    <span className="block text-[10px] font-black uppercase tracking-wide text-blue-800">Map to project(s)</span>
    {unmappedProjects.length
      ? <div className="mt-2 flex flex-wrap gap-2">{unmappedProjects.map(project => {
          const checked = selectedIds.has(project.id);
          return <label key={project.id} className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-bold ${checked ? "border-blue-400 bg-blue-100 text-blue-800" : "border-slate-200 bg-white text-slate-600"}`}>
            <input type="checkbox" className="size-3.5" checked={checked} onChange={() => toggle(project.id)}/>
            {project.name}
          </label>;
        })}</div>
      : <p className="mt-2 text-xs font-bold text-slate-500">No unmapped active projects available.</p>}
    {error && <p className="mt-2 text-xs font-bold text-rose-700">{error}</p>}
    {unmappedProjects.length > 0 && <div className="mt-3"><Button size="sm" loading={submitting} disabled={!selectedIds.size} onClick={submit}>Map to {selectedIds.size || ""} project{selectedIds.size === 1 ? "" : "s"}</Button></div>}
  </div>;
}

// Telegram connect-code generation, unlink, and WhatsApp/Telegram channel
// switch for one vendor contact - mirrors ChannelPanel's equivalent section
// in UserModals.jsx exactly (same copy, same flow, same gating), just for
// a V2VendorContact instead of an EmployeeProfile.
function ContactTelegramControl({ contact, canManage, onChanged }) {
  const [channel, setChannel] = useState(contact.active_channel || "whatsapp");
  const [connected, setConnected] = useState(!!contact.telegram_connected);
  const [switchBusy, setSwitchBusy] = useState(false);
  const [switchError, setSwitchError] = useState("");
  const [codeBusy, setCodeBusy] = useState(false);
  const [codeError, setCodeError] = useState("");
  const [connectCode, setConnectCode] = useState(null);
  const [unlinkBusy, setUnlinkBusy] = useState(false);
  const [unlinkError, setUnlinkError] = useState("");

  useEffect(() => {
    setChannel(contact.active_channel || "whatsapp");
    setConnected(!!contact.telegram_connected);
    setConnectCode(null);
  }, [contact.id, contact.active_channel, contact.telegram_connected]);

  if (!canManage) return null;

  const other = channel === "telegram" ? "whatsapp" : "telegram";
  const otherLabel = other === "telegram" ? "Telegram" : "WhatsApp";
  const canSwitchToOther = other !== "telegram" || connected;
  // Same deliberate non-auto-fallback as ChannelPanel: a contact left on
  // "telegram" with no connected chat is shown as not-ready rather than
  // silently treated as reachable on WhatsApp instead.
  const messagingReady = channel === "telegram" ? connected : !!contact.phone;

  async function switchTo(target) {
    setSwitchBusy(true);
    setSwitchError("");
    try {
      const response = await channelToggleApi.toggleVendorContact(contact.id, target);
      const result = response.results?.[0];
      if (!result?.success) setSwitchError(result?.error || "Could not switch channel.");
      else { setChannel(target); await onChanged?.(); }
    } catch (err) {
      setSwitchError(err.message || "Could not switch channel.");
    } finally {
      setSwitchBusy(false);
    }
  }

  async function generateCode() {
    setCodeBusy(true);
    setCodeError("");
    try {
      const response = await telegramConnectApi.generateVendorContactCode(contact.id);
      setConnectCode(response);
    } catch (err) {
      setCodeError(err.message || "Could not generate a connect code.");
    } finally {
      setCodeBusy(false);
    }
  }

  async function unlinkTelegram() {
    // eslint-disable-next-line no-alert -- deliberately simple, mirrors
    // UserModals.jsx's employee unlink: an Admin-only, low-frequency
    // identity action, not worth a full modal.
    if (!window.confirm("Unlink Telegram from this contact? They'll need a new connect code to reconnect, and this frees their chat for someone else to use.")) return;
    setUnlinkBusy(true);
    setUnlinkError("");
    try {
      await telegramConnectApi.unlinkVendorContact(contact.id);
      setConnected(false);
      setConnectCode(null);
      await onChanged?.();
    } catch (err) {
      setUnlinkError(err.message || "Could not unlink Telegram.");
    } finally {
      setUnlinkBusy(false);
    }
  }

  return <div className="mt-3 border-t border-slate-100 pt-3">
    <div className="flex flex-wrap items-center gap-2">
      <Pill tone={channel === "telegram" ? "blue" : "green"}>{channel === "telegram" ? "Telegram" : "WhatsApp"}</Pill>
      {!connected && <Pill tone="gray">Telegram not connected yet</Pill>}
      {!messagingReady && <Pill tone="orange">Messaging Not Ready</Pill>}
    </div>
    {!canSwitchToOther && <p className="mt-2 text-xs font-semibold text-amber-700">They must connect Telegram (below) before they can be switched over.</p>}
    {switchError && <p className="mt-2 text-xs font-semibold text-rose-600">{switchError}</p>}
    <div className="mt-2 flex flex-wrap gap-2">
      <Button type="button" size="sm" variant="secondary" loading={switchBusy} disabled={!canSwitchToOther} onClick={() => switchTo(other)}>
        <ArrowLeftRight size={14}/> Switch to {otherLabel}
      </Button>
      {connected && <Button type="button" size="sm" variant="ghost" loading={unlinkBusy} onClick={unlinkTelegram}><Unlink size={14}/> Unlink Telegram</Button>}
    </div>
    {unlinkError && <p className="mt-1 text-xs font-semibold text-rose-600">{unlinkError}</p>}

    {!connected && <div className="mt-2 rounded-xl border border-dashed border-blue-200 bg-blue-50/60 p-3">
      {!connectCode ? <>
        <p className="text-xs leading-5 text-slate-600">Generates a one-time code. They open Telegram, find the bot themselves, and send the code as a message - no link needed.</p>
        {codeError && <p className="mt-2 text-xs font-semibold text-rose-600">{codeError}</p>}
        <Button type="button" variant="secondary" size="sm" className="mt-2" loading={codeBusy} onClick={generateCode}><KeyRound size={14}/> Generate code</Button>
      </> : <>
        <p className="text-sm leading-6 text-slate-700">Tell them to open Telegram, search for the bot, and send this message:</p>
        <code className="mt-2 block rounded-xl bg-white px-3 py-2 text-sm font-bold text-slate-900 shadow-sm">{connectCode.start_command}</code>
        <p className="mt-2 text-xs font-semibold text-slate-500">Expires {new Date(connectCode.expires_at).toLocaleTimeString("en-GB")}. Refresh this record afterward to confirm it connected.</p>
        <Button type="button" variant="secondary" size="sm" className="mt-2" loading={codeBusy} onClick={generateCode}><KeyRound size={14}/> Generate a new code</Button>
      </>}
    </div>}
  </div>;
}

function HeaderMenu({ onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    function onClickOutside(event) { if (ref.current && !ref.current.contains(event.target)) setOpen(false); }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);
  return <div ref={ref} className="relative">
    <button type="button" aria-label="More vendor actions" onClick={() => setOpen(v => !v)} className="grid size-10 shrink-0 place-items-center rounded-xl border border-slate-200 text-slate-500 transition hover:bg-slate-50"><MoreVertical size={17}/></button>
    {open && <div className="absolute right-0 top-[calc(100%+6px)] z-20 grid w-44 gap-0.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-[0_18px_50px_rgba(15,23,42,.14)]">
      <button type="button" onClick={() => { setOpen(false); onDelete(); }} className="rounded-lg px-3 py-2 text-left text-sm font-bold text-rose-700 transition hover:bg-rose-50">Delete vendor</button>
    </div>}
  </div>;
}

export function VendorDetailPanel({ vendor, parentVendor, subVendors = [], contacts = [], projects = [], unmappedProjects = [], mapToProjects, categories = [], canManage, onClose, remove, edit, blacklist, unblacklist, addContact, addSubcontractor, selectVendor, onContactChanged, user, saving = false, pastProjects = [], projectHistory = [], savePastProject, deletePastProject, contactProjects = [], contactTasks = [] }) {
  const [activeTab, setActiveTab] = useState("overview");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  useEffect(() => { setActiveTab("overview"); setConfirmDelete(false); setDeleteError(""); }, [vendor.id]);

  // The page behind the drawer must not scroll while it's open - same
  // convention as TaskDetailDrawer, which this mirrors.
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, []);

  const primary = contacts.find(contact => contact.is_primary) || contacts[0];
  const isMain = vendor.engagement_type === "main";
  const pending = vendor.engagement_type === "migration_pending";
  const deletionBlocked = isMain && subVendors.length > 0;
  const deleteMessage = deleteError || (deletionBlocked
    ? `This main vendor has ${subVendors.length} linked sub-vendor${subVendors.length === 1 ? "" : "s"}. Transfer or delete them first, or edit this vendor and mark it inactive.`
    : "This permanently removes the company, its contacts and relationships, and unassigns it from current tasks.");
  async function confirmVendorDeletion() {
    setDeleteError("");
    const result = await remove();
    if (!result?.ok) setDeleteError(result?.error || "This vendor cannot be deleted while linked records remain.");
  }
  const tabs = [
    { id: "overview", label: "Overview", icon: ClipboardList },
    { id: "contacts", label: "Contacts", icon: UserRound, count: contacts.length },
    { id: "projects", label: "Projects", icon: FolderKanban, count: projects.length },
    ...(isMain ? [{ id: "subvendors", label: "Sub-vendors", icon: UsersRound, count: subVendors.length }] : []),
  ];

  const blocked = isBlocked(vendor);
  const mayBlacklist = !vendor.blacklisted && canBlacklist(user);
  const mayUnblacklist = vendor.blacklisted && canUnblacklist(user);

  return <>
    <div className="fixed inset-0 z-40 bg-slate-950/40" onClick={onClose} aria-hidden="true"/>
    <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[90vw] flex-col bg-white shadow-[-16px_0_50px_rgba(15,23,42,.18)] sm:w-[640px]" aria-label={`Vendor detail - ${vendor.name}`}>
    <section className="shrink-0 border-b border-slate-200 p-4 sm:p-5">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-blue-600 text-base font-black text-white shadow-[0_10px_24px_rgba(37,99,235,.25)]">{vendor.name.slice(0, 2).toUpperCase()}</div>
          <div className="min-w-0">
            <h2 className="truncate text-lg font-black tracking-tight text-slate-950">{vendor.name}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Pill tone={pending ? "orange" : isMain ? "blue" : "green"}>{pending ? "Mapping required" : isMain ? "Main Vendor" : "Sub-vendor"}</Pill>
              <BlacklistPill vendor={vendor}/>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {primary && <a aria-label="Call primary contact" href={`tel:${cleanPhone(primary.phone)}`} className="grid size-10 place-items-center rounded-xl border border-slate-200 text-slate-500 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"><Phone size={16}/></a>}
          {primary && <a aria-label="WhatsApp primary contact" href={`https://wa.me/${cleanPhone(primary.whatsapp || primary.phone).replace("+", "")}`} target="_blank" rel="noreferrer" className="grid size-10 place-items-center rounded-xl border border-slate-200 text-slate-500 transition hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700"><MessageCircle size={16}/></a>}
          {vendor.email && <a aria-label="Email vendor" href={`mailto:${vendor.email}`} className="grid size-10 place-items-center rounded-xl border border-slate-200 text-slate-500 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"><Mail size={16}/></a>}
          {canManage && <HeaderMenu onDelete={() => setConfirmDelete(true)}/>}
          {onClose && <button type="button" aria-label="Close vendor details" onClick={onClose} className="grid size-10 place-items-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"><X size={18}/></button>}
        </div>
      </div>
      <BlacklistBanner vendor={vendor} parentVendor={parentVendor}/>
      {pending && <div className="mt-3 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><ShieldAlert className="mt-0.5 shrink-0" size={18}/><span>This legacy record remains visible but cannot receive project or task assignments until its parent is approved.</span></div>}
    </section>
    <nav className="grid shrink-0 grid-cols-3 gap-1 border-b border-slate-200 bg-white px-4 py-3 sm:flex sm:flex-wrap sm:px-5" aria-label="Vendor detail sections">{tabs.map(tab => { const Icon = tab.icon; return <button type="button" key={tab.id} onClick={() => setActiveTab(tab.id)} className={`flex min-h-10 min-w-0 items-center justify-center gap-2 rounded-xl px-3 text-sm font-black transition ${activeTab === tab.id ? "bg-slate-950 text-white shadow-sm" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900"}`}><Icon size={16}/>{tab.label}{tab.count !== undefined && <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${activeTab === tab.id ? "bg-white/15" : "bg-slate-100"}`}>{tab.count}</span>}</button>; })}</nav>

    <div className="min-h-0 min-w-0 max-w-full flex-1 overflow-y-auto bg-slate-50 p-6 max-[640px]:p-4">
      {activeTab === "overview" && <div className="grid gap-5">
        <CapabilityGroups vendor={vendor} categories={categories}/>
        <section className="grid grid-cols-2 gap-3 max-[720px]:grid-cols-1"><DetailItem icon={Building2} label="Engagement" value={pending ? "Parent mapping required" : isMain ? "Main vendor" : `Sub-vendor of ${parentVendor?.name || "approved parent"}`}/><DetailItem icon={ShieldCheck} label="GST number" value={vendor.gst_number}/><DetailItem icon={Mail} label="Email" value={vendor.email}/><DetailItem icon={MapPin} label="Address" value={vendor.address}/></section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5"><p className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-400">Internal context</p><h3 className="mt-2 font-black text-slate-950">Operations notes</h3><p className="mt-2 text-sm leading-7 text-slate-600">{vendor.notes || "No internal vendor notes have been added."}</p></section>
      </div>}

      {activeTab === "contacts" && <section className="grid gap-3"><header className="mb-1 flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-lg font-black text-slate-950">Vendor contacts</h3><p className="mt-1 text-sm text-slate-500">People available for site coordination.</p></div>{canManage && <button type="button" onClick={addContact} className="flex min-h-11 items-center gap-2 rounded-xl bg-blue-700 px-4 text-sm font-black text-white"><Plus size={17}/> Add contact</button>}</header>{contacts.map(contact => <article key={contact.id} className="rounded-2xl border border-slate-200 bg-white p-4"><div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 max-[640px]:grid-cols-[auto_minmax(0,1fr)]"><span className="grid size-11 place-items-center rounded-xl bg-slate-100 font-black text-slate-700">{contact.name.slice(0, 2).toUpperCase()}</span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><strong className="text-slate-950">{contact.name}</strong>{contact.is_primary && <Pill tone="blue">Primary</Pill>}</div><span className="mt-1 block text-sm text-slate-500">{contact.designation || "Contact person"}</span><a href={`tel:${cleanPhone(contact.phone)}`} className="mt-1 block text-sm font-bold text-slate-700">{contact.phone}</a></div><div className="max-[640px]:col-span-2"><ContactActions contact={contact}/></div></div><ContactTelegramControl contact={contact} canManage={canManage} onChanged={onContactChanged}/><ContactWorkSummary projects={contactProjects.filter(row => row.contact_id === contact.id)} tasks={contactTasks.filter(row => row.contact_id === contact.id)}/></article>)}{!contacts.length && <EmptyPanel icon={UserRound} title="No contacts yet" text="Add a primary site contact so assignments and WhatsApp messages reach the right person." action={canManage && <button type="button" onClick={addContact} className="mt-4 rounded-xl bg-blue-700 px-4 py-3 text-sm font-black text-white">Add first contact</button>}/>}</section>}

      {activeTab === "projects" && <section className="grid gap-3"><header className="mb-1"><h3 className="text-lg font-black text-slate-950">Assigned projects</h3><p className="mt-1 text-sm text-slate-500">Current project visibility and inherited access.</p></header>{isMain && canManage && !blocked && <VendorProjectMappingForm vendor={vendor} unmappedProjects={unmappedProjects} mapToProjects={mapToProjects}/>}{projects.map(project => <article key={project.id} className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4"><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><FolderKanban size={19}/></span><div className="min-w-0 flex-1"><strong className="block truncate text-slate-950">{project.name}</strong><span className="mt-1 block text-xs text-slate-500">{isMain ? "Direct project mapping" : "Inherited through parent vendor"}</span></div><Pill tone={project.status === "active" ? "green" : "orange"}>{projectStatusLabel(project.status)}</Pill></article>)}{!projects.length && <EmptyPanel icon={FolderKanban} title="No project mapping" text={isMain ? "Map this vendor to a project before assigning its team to project tasks." : "This sub-vendor will inherit project visibility from its parent vendor."}/>}<VendorWorkHistory user={user} pastProjects={pastProjects} projectHistory={projectHistory} categories={categories} saving={saving} savePastProject={savePastProject} deletePastProject={deletePastProject}/></section>}

      {activeTab === "subvendors" && <section className="grid gap-3"><header className="mb-1 flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-lg font-black text-slate-950">Sub-vendor network</h3><p className="mt-1 text-sm text-slate-500">Approved companies operating under this vendor.</p></div>{canManage && !blocked && <button type="button" onClick={addSubcontractor} className="flex min-h-11 items-center gap-2 rounded-xl bg-blue-700 px-4 text-sm font-black text-white"><Plus size={17}/> Add sub-vendor</button>}</header>{subVendors.map(subVendor => <button type="button" key={subVendor.id} onClick={() => selectVendor?.(subVendor.id)} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4 text-left transition hover:border-blue-300 hover:shadow-sm"><span className="grid size-11 place-items-center rounded-xl bg-emerald-50 font-black text-emerald-700">{subVendor.name.slice(0, 2).toUpperCase()}</span><div className="min-w-0"><strong className="block truncate text-slate-950">{subVendor.name}</strong><span className="mt-1 block truncate text-xs text-slate-500">{(subVendor.categories || [subVendor.category]).join(" - ")}</span></div><ChevronRight className="text-slate-400"/></button>)}{!subVendors.length && <EmptyPanel icon={UsersRound} title="No sub-vendors linked" text="Create sub-vendors only from this approved parent profile." action={canManage && !blocked && <button type="button" onClick={addSubcontractor} className="mt-4 rounded-xl bg-blue-700 px-4 py-3 text-sm font-black text-white">Add sub-vendor</button>}/>}</section>}

    </div>

    {(canManage || mayBlacklist || mayUnblacklist) && <footer className="flex shrink-0 flex-wrap gap-2 border-t border-slate-200 bg-white p-4">
      <Button type="button" size="sm" variant="secondary" onClick={() => setActiveTab("overview")}><ClipboardList size={16}/> View profile</Button>
      {canManage && <Button type="button" size="sm" variant="secondary" onClick={edit}><Pencil size={16}/> Edit vendor</Button>}
      {mayBlacklist && <Button type="button" size="sm" variant="danger" onClick={blacklist}><Ban size={16}/> Blacklist</Button>}
      {mayUnblacklist && <Button type="button" size="sm" variant="secondary" onClick={unblacklist}><ShieldOff size={16}/> Remove from blacklist</Button>}
    </footer>}

    {confirmDelete && <ConfirmModal title={deletionBlocked ? "Deletion blocked" : `Delete ${vendor.name}?`} message={deleteMessage} confirmLabel={deletionBlocked ? "Linked sub-vendors must be resolved" : "Delete permanently"} confirmDisabled={deletionBlocked} onClose={() => { setConfirmDelete(false); setDeleteError(""); }} onConfirm={confirmVendorDeletion}/>}
    </aside>
  </>;
}
