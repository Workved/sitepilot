import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Ban, ChevronRight, FolderKanban, Mail, MapPin, MessageCircle, MoreHorizontal, Pencil, Phone, Plus, ShieldAlert, ShieldCheck, ShieldOff, UsersRound } from "lucide-react";
import { Button, ConfirmModal, Pill } from "../../../components/ui";
import { StatStrip } from "../../../components/layout/PaneKit";
import { cn } from "../../../utils/cn";
import { initials } from "../../../utils/format";
import { ContactWorkSummary } from "./ContactWorkSummary";
import { BlacklistBanner, BlacklistPill, canBlacklist, canUnblacklist, isBlocked } from "./VendorBlacklist";
import { VendorWorkHistory } from "./VendorWorkHistory";
import { RatingSummary, summarizeFeedback } from "../vendorFeedback";

/*
 * A vendor's profile as a full page (linked by ?vendor=<id>), replacing the
 * old side drawer: who they are and what they do up top, live work and
 * history in the main column, people and business details beside it.
 * Everything the drawer could do is still here.
 */

const cleanPhone = (value = "") => value.replace(/[^\d+]/g, "");
const waLink = contact => `https://wa.me/${cleanPhone(contact.whatsapp || contact.phone).replace("+", "")}`;
const projectStatusLabel = value => ({ draft: "Draft", active: "Active", on_hold: "On hold", completed: "Completed", archived: "Archived" }[value] || value);

function Card({ title, action, children, className }) {
  return <section className={cn("rounded-[20px] border border-line bg-white", className)}>
    {(title || action) && <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
      <h3 className="text-[15px] font-medium text-slate-950">{title}</h3>{action}
    </header>}
    <div className="p-5">{children}</div>
  </section>;
}

function ContactButtons({ contact, size = "md" }) {
  if (!contact) return null;
  const box = size === "sm" ? "size-8" : "size-10";
  return <div className="flex gap-1.5">
    <a aria-label={`Call ${contact.name}`} href={`tel:${cleanPhone(contact.phone)}`} className={cn("grid place-items-center rounded-lg border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50", box)}><Phone size={size === "sm" ? 14 : 16}/></a>
    <a aria-label={`WhatsApp ${contact.name}`} href={waLink(contact)} target="_blank" rel="noreferrer" className={cn("grid place-items-center rounded-lg border border-emerald-100 bg-emerald-50 text-emerald-700 hover:bg-emerald-100", box)}><MessageCircle size={size === "sm" ? 14 : 16}/></a>
  </div>;
}

function ActionsMenu({ items }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
    const onKey = event => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  if (!items.length) return null;
  return <div ref={ref} className="relative">
    <button type="button" aria-label="More vendor actions" aria-expanded={open} onClick={() => setOpen(value => !value)} className="grid size-10 place-items-center rounded-xl border border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"><MoreHorizontal size={18}/></button>
    {open && <div role="menu" className="absolute right-0 top-[calc(100%+6px)] z-20 grid w-52 gap-0.5 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      {items.map(item => <button key={item.label} type="button" role="menuitem" onClick={() => { setOpen(false); item.onClick(); }}
        className={cn("flex items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-slate-50", item.danger ? "text-rose-700 hover:bg-rose-50" : "text-slate-800")}>
        {item.icon && <item.icon size={15} aria-hidden="true"/>}{item.label}
      </button>)}
    </div>}
  </div>;
}

function MapToProjects({ unmappedProjects, mapToProjects }) {
  const [open, setOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  if (!unmappedProjects.length) return null;

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
      else { setSelectedIds(new Set()); setOpen(false); }
    } catch (caught) {
      setError(caught?.message || "This vendor could not be mapped to the selected project(s).");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return <button type="button" onClick={() => setOpen(true)} className="flex items-center gap-1 text-[13px] text-blue-700 hover:text-blue-900"><Plus size={14}/> Map to project</button>;
  return <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
    <span className="block text-xs text-slate-600">Map to project(s)</span>
    <div className="mt-2 flex flex-wrap gap-2">{unmappedProjects.map(project => {
      const checked = selectedIds.has(project.id);
      return <label key={project.id} className={cn("flex cursor-pointer items-center gap-1.5 rounded-lg border bg-white px-2.5 py-1.5 text-xs", checked ? "border-slate-950 text-slate-950" : "border-slate-200 text-slate-600")}>
        <input type="checkbox" className="size-3.5 accent-slate-950" checked={checked} onChange={() => toggle(project.id)}/>{project.name}
      </label>;
    })}</div>
    {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
    <div className="mt-3 flex gap-2">
      <Button size="sm" loading={submitting} disabled={!selectedIds.size} onClick={submit}>Map to {selectedIds.size || ""} project{selectedIds.size === 1 ? "" : "s"}</Button>
      <Button size="sm" variant="ghost" onClick={() => { setOpen(false); setSelectedIds(new Set()); }}>Cancel</Button>
    </div>
  </div>;
}

function Fact({ icon: Icon, label, value, href }) {
  return <div className="flex items-start gap-3 py-2.5">
    <Icon size={16} className="mt-0.5 shrink-0 text-slate-400" aria-hidden="true"/>
    <div className="min-w-0">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-slate-950">{href ? <a href={href} className="text-blue-700 hover:text-blue-900">{value}</a> : value}</dd>
    </div>
  </div>;
}

export function VendorProfile({
  vendor, parentVendor, subVendors = [], contacts = [], projects = [], unmappedProjects = [], mapToProjects, categories = [],
  canManage, onBack, remove, edit, blacklist, unblacklist, addContact, addSubcontractor, selectVendor, user, saving = false,
  pastProjects = [], projectHistory = [], savePastProject, deletePastProject, contactProjects = [], contactTasks = [],
  feedback = [], saveFeedback, deleteFeedback,
}) {
  const rating = summarizeFeedback(feedback);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  useEffect(() => { setConfirmDelete(false); setDeleteError(""); window.scrollTo?.({ top: 0 }); }, [vendor.id]);

  const primary = contacts.find(contact => contact.is_primary) || contacts[0];
  const others = contacts.filter(contact => contact !== primary);
  const isMain = vendor.engagement_type === "main";
  const pending = vendor.engagement_type === "migration_pending";
  const blocked = isBlocked(vendor);
  const deletionBlocked = isMain && subVendors.length > 0;
  const trades = vendor.categories?.length ? vendor.categories : (vendor.category ? [vendor.category] : []);
  const liveProjects = projects.filter(project => project.status === "active");
  const details = [
    vendor.gst_number && ["GST number", vendor.gst_number, ShieldCheck],
    vendor.email && ["Email", vendor.email, Mail, `mailto:${vendor.email}`],
    vendor.address && ["Address", vendor.address, MapPin],
  ].filter(Boolean);
  const missingDetails = ["GST number", "email", "address"].filter((_, index) => ![vendor.gst_number, vendor.email, vendor.address][index]);

  const menu = [
    ...(canManage ? [{ label: "Edit vendor", icon: Pencil, onClick: edit }] : []),
    ...(!vendor.blacklisted && canBlacklist(user) ? [{ label: "Blacklist vendor", icon: Ban, onClick: blacklist, danger: true }] : []),
    ...(vendor.blacklisted && canUnblacklist(user) ? [{ label: "Remove from blacklist", icon: ShieldOff, onClick: unblacklist }] : []),
    ...(canManage ? [{ label: "Delete vendor", onClick: () => setConfirmDelete(true), danger: true }] : []),
  ];

  async function confirmVendorDeletion() {
    setDeleteError("");
    const result = await remove();
    if (!result?.ok) setDeleteError(result?.error || "This vendor cannot be deleted while linked records remain.");
  }

  return <div className="grid gap-4" aria-label={`Vendor profile - ${vendor.name}`}>
    <Button variant="ghost" size="sm" className="-ml-2 w-fit" onClick={onBack}><ArrowLeft size={16}/> Vendors</Button>

    <header className="rounded-[20px] border border-line bg-white p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          <span className={cn("grid size-16 shrink-0 place-items-center rounded-2xl text-xl font-medium", blocked ? "bg-rose-50 text-rose-800" : isMain ? "bg-blue-50 text-blue-800" : "bg-emerald-50 text-emerald-800")}>{initials(vendor.name)}</span>
          <div className="min-w-0">
            <h2 className="text-[26px] font-normal leading-tight tracking-[-0.02em] text-slate-950">{vendor.name}</h2>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-500">
              {pending ? <span className="text-orange-700">Parent mapping required</span>
                : isMain ? <span>Main vendor</span>
                : <span>Sub-vendor of {parentVendor ? <button type="button" onClick={() => selectVendor(parentVendor.id)} className="text-blue-700 hover:text-blue-900">{parentVendor.name}</button> : "an approved parent"}</span>}
              <BlacklistPill vendor={vendor}/>
            </p>
            {trades.length > 0 && <div className="mt-2.5 flex flex-wrap gap-1.5">{trades.map(trade => <span key={trade} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{trade}</span>)}</div>}
            {rating.count > 0 && <p className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Vendor rating">
              <RatingSummary summary={rating}/>
              <span className="text-sm text-slate-500">{rating.rehire.yes + rating.rehire.conditional} of {rating.count} would hire again</span>
            </p>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {primary && <a href={`tel:${cleanPhone(primary.phone)}`} className="flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 hover:border-slate-300 hover:bg-slate-50"><Phone size={16}/> Call</a>}
          {primary && <a href={waLink(primary)} target="_blank" rel="noreferrer" className="flex h-10 items-center gap-2 rounded-xl border border-emerald-100 bg-emerald-50 px-3 text-sm text-emerald-800 hover:bg-emerald-100"><MessageCircle size={16}/> WhatsApp</a>}
          {canManage && <Button onClick={edit}><Pencil size={16}/> Edit</Button>}
          <ActionsMenu items={menu.filter(item => item.label !== "Edit vendor")}/>
        </div>
      </div>
      <BlacklistBanner vendor={vendor} parentVendor={parentVendor}/>
      {pending && <div className="mt-3 flex items-start gap-3 rounded-2xl border border-orange-100 bg-orange-50 p-4 text-sm text-orange-900"><ShieldAlert className="mt-0.5 shrink-0" size={18}/><span>This legacy record remains visible but cannot receive project or task assignments until its parent is approved.</span></div>}
    </header>

    <StatStrip items={[
      { label: "Live projects", value: liveProjects.length, tone: "blue" },
      { label: "Contacts", value: contacts.length, tone: "violet" },
      { label: "Past projects", value: pastProjects.length + projectHistory.length, tone: "green" },
      { label: "Rating", value: rating.count ? rating.average.toFixed(1) : 0, hint: rating.count ? `${rating.count} ${rating.count === 1 ? "review" : "reviews"}` : "No reviews yet", tone: "yellow" },
      ...(isMain ? [{ label: "Sub-vendors", value: subVendors.length, tone: "orange" }] : []),
    ]} className={isMain ? "xl:grid-cols-5" : undefined}/>

    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="grid min-w-0 gap-4">
        <Card title={`Projects ${projects.length ? `(${projects.length})` : ""}`.trim()} action={isMain && canManage && !blocked ? <MapToProjects unmappedProjects={unmappedProjects} mapToProjects={mapToProjects}/> : null}>
          {projects.length
            ? <ul className="-my-2 divide-y divide-slate-100">{projects.map(project => <li key={project.id} className="flex items-center gap-3 py-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-slate-100 text-slate-700"><FolderKanban size={16}/></span>
                <div className="min-w-0 flex-1">
                  <strong className="block truncate text-sm font-normal text-slate-950">{project.name}</strong>
                  <span className="block text-xs text-slate-500">{isMain ? "Mapped directly" : "Through the main vendor"}</span>
                </div>
                <Pill tone={project.status === "active" ? "green" : "gray"}>{projectStatusLabel(project.status)}</Pill>
              </li>)}</ul>
            : <p className="text-sm text-slate-500">{isMain ? "Not on any project yet. Map it to a project before assigning its team to tasks." : "Inherits project access from its main vendor."}</p>}
        </Card>

        <section className="rounded-[20px] border border-line bg-white p-5">
          <VendorWorkHistory user={user} vendorName={vendor.name} pastProjects={pastProjects} projectHistory={projectHistory} feedback={feedback} categories={categories} saving={saving}
            savePastProject={savePastProject} deletePastProject={deletePastProject} saveFeedback={saveFeedback} deleteFeedback={deleteFeedback}/>
        </section>

        {isMain && <Card title={`Sub-vendors ${subVendors.length ? `(${subVendors.length})` : ""}`.trim()} action={canManage && !blocked ? <button type="button" onClick={addSubcontractor} className="flex items-center gap-1 text-[13px] text-blue-700 hover:text-blue-900"><Plus size={14}/> Add sub-vendor</button> : null}>
          {subVendors.length
            ? <ul className="-my-1 grid gap-1">{subVendors.map(subVendor => <li key={subVendor.id}>
                <button type="button" onClick={() => selectVendor(subVendor.id)} className="flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-slate-50">
                  <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-emerald-50 text-xs font-medium text-emerald-800">{initials(subVendor.name)}</span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-sm text-slate-950">{subVendor.name}</span><span className="block truncate text-xs text-slate-500">{(subVendor.categories || [subVendor.category]).filter(Boolean).join(", ")}</span></span>
                  <ChevronRight size={16} className="text-slate-400"/>
                </button>
              </li>)}</ul>
            : <p className="flex items-center gap-2 text-sm text-slate-500"><UsersRound size={16}/>No sub-vendors work under this vendor yet.</p>}
        </Card>}
      </div>

      <aside className="grid min-w-0 gap-4">
        <Card title="Primary contact">
          {primary
            ? <div>
                <div className="flex items-center gap-3">
                  <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-slate-100 text-sm font-medium text-slate-700">{initials(primary.name)}</span>
                  <div className="min-w-0 flex-1">
                    <strong className="block truncate text-[15px] font-normal text-slate-950">{primary.name}</strong>
                    <span className="block truncate text-xs text-slate-500">{primary.designation || "Contact person"}</span>
                  </div>
                  <ContactButtons contact={primary}/>
                </div>
                <a href={`tel:${cleanPhone(primary.phone)}`} className="mt-3 block text-sm tabular-nums text-slate-800">{primary.phone}</a>
                {!primary.whatsapp && !primary.phone && canManage && <Pill tone="orange" className="mt-2">Messaging Not Ready</Pill>}
                <ContactWorkSummary projects={contactProjects.filter(row => row.contact_id === primary.id)} tasks={contactTasks.filter(row => row.contact_id === primary.id)}/>
              </div>
            : <div className="text-sm text-slate-500">No contact yet. Add one so assignments and WhatsApp messages reach the right person.{canManage && <Button size="sm" className="mt-3" onClick={addContact}><Plus size={15}/> Add contact</Button>}</div>}
        </Card>

        {(others.length > 0 || (primary && canManage)) && <Card title={`Other contacts ${others.length ? `(${others.length})` : ""}`.trim()} action={canManage ? <button type="button" onClick={addContact} className="flex items-center gap-1 text-[13px] text-blue-700 hover:text-blue-900"><Plus size={14}/> Add</button> : null}>
          {others.length
            ? <ul className="-my-2 divide-y divide-slate-100">{others.map(contact => <li key={contact.id} className="py-2.5">
                <div className="flex items-center gap-3">
                  <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-slate-100 text-xs font-medium text-slate-700">{initials(contact.name)}</span>
                  <div className="min-w-0 flex-1"><span className="block truncate text-sm text-slate-950">{contact.name}</span><span className="block truncate text-xs text-slate-500">{contact.designation || contact.phone}</span></div>
                  <ContactButtons contact={contact} size="sm"/>
                </div>
                <ContactWorkSummary projects={contactProjects.filter(row => row.contact_id === contact.id)} tasks={contactTasks.filter(row => row.contact_id === contact.id)}/>
              </li>)}</ul>
            : <p className="text-sm text-slate-500">Only the primary contact so far.</p>}
        </Card>}

        <Card title="Business details" action={canManage && missingDetails.length > 0 ? <button type="button" onClick={edit} className="text-[13px] text-blue-700 hover:text-blue-900">Add {missingDetails.join(", ")}</button> : null}>
          {details.length
            ? <dl className="-my-2 divide-y divide-slate-100">{details.map(([label, value, icon, href]) => <Fact key={label} icon={icon} label={label} value={value} href={href}/>)}</dl>
            : <p className="text-sm text-slate-500">No GST number, email or address on file.</p>}
        </Card>

        <Card title="Internal notes">
          <p className="whitespace-pre-line text-sm leading-6 text-slate-600">{vendor.notes || "No internal notes yet."}</p>
        </Card>
      </aside>
    </div>

    {confirmDelete && <ConfirmModal
      title={deletionBlocked ? "Deletion blocked" : `Delete ${vendor.name}?`}
      message={deleteError || (deletionBlocked
        ? `This main vendor has ${subVendors.length} linked sub-vendor${subVendors.length === 1 ? "" : "s"}. Transfer or delete them first, or edit this vendor and mark it inactive.`
        : "This permanently removes the company, its contacts and relationships, and unassigns it from current tasks.")}
      confirmLabel={deletionBlocked ? "Linked sub-vendors must be resolved" : "Delete permanently"}
      confirmDisabled={deletionBlocked}
      onClose={() => { setConfirmDelete(false); setDeleteError(""); }}
      onConfirm={confirmVendorDeletion}/>}
  </div>;
}
