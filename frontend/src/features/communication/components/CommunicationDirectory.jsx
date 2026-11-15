import { useEffect, useRef, useState } from "react";
import { Building2, MessageCircle, MoreVertical, Phone, ShieldCheck, UserRound } from "lucide-react";
import { Modal, Pill } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { CategorySelector } from "./CategorySelector";

const cleanPhone = (value = "") => value.replace(/[^\d+]/g, "");
const statusLabel = value => ({ active: "Active", inactive: "Inactive", on_hold: "On hold", blocked_by_parent: "Blocked by parent" }[value] || value);
const inputClass = "min-h-12 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-50";

export function QuickActions({ contact, compact = false }) {
  if (!contact) return <span className="text-xs font-bold text-slate-400">No contact</span>;
  return <div className={`flex flex-wrap gap-2 max-[720px]:col-start-2 ${compact ? "[&_span]:hidden" : ""}`}>
    <a className="flex min-h-10 items-center gap-2 rounded-xl bg-blue-50 px-3 text-xs font-black text-blue-700 transition hover:bg-blue-100" href={`tel:${cleanPhone(contact.phone)}`} onClick={event => event.stopPropagation()}><Phone size={16}/><span>Call</span></a>
    <a className="flex min-h-10 items-center gap-2 rounded-xl bg-emerald-50 px-3 text-xs font-black text-emerald-700 transition hover:bg-emerald-100" href={`https://wa.me/${cleanPhone(contact.whatsapp || contact.phone).replace("+", "")}`} target="_blank" rel="noreferrer" onClick={event => event.stopPropagation()}><MessageCircle size={16}/><span>WhatsApp</span></a>
  </div>;
}

export function Metric({ icon, value, label, hint, action, tone = "border-slate-200 bg-slate-50", className }) {
  return <div className={cn("flex items-center gap-3 rounded-2xl border p-4", tone, className)}>
    <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-white/70 text-blue-700">{icon}</span>
    <div className="min-w-0 flex-1">
      <p className="text-xs font-bold text-slate-500">{label}</p>
      <p className="text-2xl font-black leading-tight text-slate-950">{value}</p>
      {action ? action : hint && <p className="truncate text-[11px] font-semibold text-slate-500">{hint}</p>}
    </div>
  </div>;
}

export function CategoryChip({ label, count, active, onClick }) {
  return <button type="button" onClick={onClick} aria-pressed={active}
    className={cn("flex shrink-0 items-center gap-2 rounded-xl border px-3.5 py-2 text-sm font-black transition", active ? "border-blue-700 bg-blue-700 text-white" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50")}>
    {label}
    <span className={cn("rounded-full px-1.5 py-0.5 text-xs font-black", active ? "bg-white/20" : "bg-slate-100 text-slate-500")}>{count}</span>
  </button>;
}

function CategoryPills({ vendor }) {
  return <div className="mt-1.5 flex flex-wrap gap-1">{(vendor.categories || [vendor.category]).slice(0, 2).map(category => <Pill key={category} tone="gray">{category}</Pill>)}</div>;
}

function RowMenu({ items }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(event) { if (ref.current && !ref.current.contains(event.target)) setOpen(false); }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  return <div ref={ref} className="relative" onClick={event => event.stopPropagation()}>
    <button type="button" aria-label="Vendor row actions" onClick={() => setOpen(v => !v)}
      className="grid size-9 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"><MoreVertical size={17}/></button>
    {open && <div className="absolute right-0 top-[calc(100%+4px)] z-20 grid w-44 gap-0.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-[0_18px_50px_rgba(15,23,42,.14)]">
      {items.map(item => <button key={item.label} type="button" onClick={() => { setOpen(false); item.onClick(); }}
        className={cn("rounded-lg px-3 py-2 text-left text-sm font-bold transition hover:bg-slate-50", item.danger ? "text-rose-700" : "text-slate-700")}>{item.label}</button>)}
    </div>}
  </div>;
}

export function VendorRow({ vendor, primary, projectCount, selected, layout = "list", onSelect, onEdit, onDeactivate, onDelete }) {
  const isMain = vendor.engagement_type === "main";
  const effectiveStatus = vendor.effective_status || vendor.status;
  const menuItems = [
    { label: "Edit vendor", onClick: onEdit },
    ...(effectiveStatus === "active" ? [{ label: "Deactivate", onClick: onDeactivate }] : []),
    { label: "Delete vendor", onClick: onDelete, danger: true },
  ];

  return <article onClick={onSelect}
    className={cn("grid cursor-pointer gap-3 rounded-2xl border p-4 transition hover:border-blue-200 hover:shadow-[0_12px_30px_rgba(15,23,42,.06)]",
      selected ? "border-blue-300 bg-blue-50/40 ring-2 ring-blue-500/40" : "border-slate-200 bg-white",
      layout === "list" && "sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto_auto] sm:items-center")}>
    <div className="flex items-center gap-3">
      <div className={cn("grid size-11 shrink-0 place-items-center rounded-xl font-black", isMain ? "bg-blue-100 text-blue-700" : "bg-emerald-100 text-emerald-700")}>{vendor.name.slice(0, 2).toUpperCase()}</div>
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-sm font-black text-slate-950">{vendor.name}</h3>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Pill tone={isMain ? "blue" : "green"}>{isMain ? "Main Vendor" : "Sub-vendor"}</Pill>
          <CategoryPills vendor={vendor}/>
        </div>
      </div>
    </div>

    <div className="min-w-0">
      <strong className="block truncate text-sm text-slate-800">{primary?.name || "No primary contact"}</strong>
      <span className="block truncate text-xs text-slate-500">{primary?.designation || "Contact person"}</span>
      {primary && <a href={`tel:${cleanPhone(primary.phone)}`} onClick={event => event.stopPropagation()} className="mt-0.5 block truncate text-xs font-bold text-slate-600 hover:text-blue-700">{primary.phone}</a>}
    </div>

    <div className="flex shrink-0 items-center gap-2" onClick={event => event.stopPropagation()}>
      <QuickActions contact={primary} compact/>
    </div>

    <div className="flex shrink-0 items-center gap-3">
      <div className="text-right">
        <strong className="block text-sm font-black text-slate-950">{projectCount}</strong>
        <span className="block text-[10px] font-bold uppercase tracking-wide text-slate-400">Projects</span>
      </div>
      <Pill tone={effectiveStatus === "active" ? "green" : effectiveStatus === "on_hold" ? "orange" : "gray"}>{statusLabel(effectiveStatus)}</Pill>
      <RowMenu items={menuItems}/>
    </div>
  </article>;
}

function SectionHeading({ icon: Icon, eyebrow, title, text }) {
  return <header className="col-span-full flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-950 text-white"><Icon size={18}/></span><div><p className="text-[11px] font-black uppercase tracking-[0.18em] text-blue-700">{eyebrow}</p><h3 className="mt-1 text-lg font-black text-slate-950">{title}</h3>{text && <p className="mt-1 text-sm leading-6 text-slate-500">{text}</p>}</div></header>;
}

function VendorForm({ formId, vendor, categories, fixedMainVendor, includeContact, onSubmit }) {
  const [selectedCategories, setSelectedCategories] = useState(vendor?.category_ids || []);
  const [categoryError, setCategoryError] = useState("");

  function submit(event) {
    if (!selectedCategories.length) {
      event.preventDefault();
      setCategoryError("Select at least one category.");
      return;
    }
    setCategoryError("");
    onSubmit(event);
  }

  return <form id={formId} className="grid grid-cols-2 gap-5 max-[720px]:grid-cols-1" onSubmit={submit}>
    {fixedMainVendor && <div className="col-span-full flex items-center gap-4 rounded-2xl border border-blue-200 bg-blue-50 p-4"><span className="grid size-11 place-items-center rounded-xl bg-blue-700 text-white"><Building2 size={20}/></span><div><span className="text-[11px] font-black uppercase tracking-[0.16em] text-blue-700">Approved parent vendor</span><strong className="mt-1 block text-slate-950">{fixedMainVendor.name}</strong></div><ShieldCheck className="ml-auto text-blue-700"/><input type="hidden" name="main_contractor_id" value={fixedMainVendor.id}/></div>}

    <section className="col-span-full grid grid-cols-2 gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={Building2} eyebrow="Company" title="Vendor profile" text="Core identity and current availability."/>
      <label className="grid gap-2 text-sm font-black text-slate-700">Company name<input className={inputClass} name="name" defaultValue={vendor?.name || ""} required/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">Status<select className={inputClass} name="status" defaultValue={vendor?.status || "active"}><option value="active">Active</option><option value="on_hold">On hold</option><option value="inactive">Inactive</option></select></label>
    </section>

    <CategorySelector categories={categories} selected={selectedCategories} onChange={value => { setSelectedCategories(value); setCategoryError(""); }} error={categoryError}/>

    {includeContact && <section className="col-span-full grid grid-cols-2 gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={UserRound} eyebrow="Primary contact" title="Who should the site team call?" text="This contact is created as the vendor's primary person."/>
      <label className="grid gap-2 text-sm font-black text-slate-700">Contact name<input className={inputClass} name="contact_person" required/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">Designation<input className={inputClass} name="designation" placeholder="Site supervisor, owner…"/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">Phone<input className={inputClass} name="phone" inputMode="tel" required/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">WhatsApp<input className={inputClass} name="whatsapp" inputMode="tel" placeholder="Use phone number if blank"/></label>
    </section>}

    <section className="col-span-full grid grid-cols-2 gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={ShieldCheck} eyebrow="Business details" title="Compliance and communication" text="Optional information that helps your operations team."/>
      <label className="grid gap-2 text-sm font-black text-slate-700">Email<input className={inputClass} name="email" type="email" defaultValue={vendor?.email || ""}/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">GST number<input className={inputClass} name="gst_number" defaultValue={vendor?.gst_number || ""}/></label>
      <label className="col-span-full grid gap-2 text-sm font-black text-slate-700 max-[720px]:col-span-1">Address<textarea className={`${inputClass} min-h-24 resize-y`} name="address" defaultValue={vendor?.address || ""}/></label>
      <label className="col-span-full grid gap-2 text-sm font-black text-slate-700 max-[720px]:col-span-1">Internal notes<textarea className={`${inputClass} min-h-24 resize-y`} name="notes" defaultValue={vendor?.notes || ""} placeholder="Scope, working preferences, important context…"/></label>
    </section>

  </form>;
}

const submitButtonClass = "min-h-12 rounded-xl bg-blue-700 px-6 font-black text-white shadow-[0_10px_24px_rgba(29,78,216,0.22)] transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60";

export function CompanyModal({ title, categories, fixedMainContractor, saving = false, onClose, onSubmit }) {
  const formId = "vendor-company-form";
  const submitLabel = fixedMainContractor ? "Create sub-vendor" : "Create main vendor";
  return <Modal className="max-w-5xl" title={title} subtitle={fixedMainContractor ? "Create a sub-vendor inside the approved parent relationship." : "Create a structured vendor profile for project and task assignment."} onClose={onClose} footer={<div className="flex justify-end"><button type="submit" form={formId} disabled={saving} className={submitButtonClass}>{saving ? "Saving..." : submitLabel}</button></div>}><VendorForm formId={formId} categories={categories} fixedMainVendor={fixedMainContractor} includeContact onSubmit={onSubmit}/></Modal>;
}

export function ProfileModal({ vendor, categories, saving = false, onClose, onSubmit }) {
  const formId = "vendor-profile-form";
  return <Modal className="max-w-5xl" title={`Edit ${vendor.name}`} subtitle="Update company details, categories and assignment availability." onClose={onClose} footer={<div className="flex justify-end"><button type="submit" form={formId} disabled={saving} className={submitButtonClass}>{saving ? "Saving..." : "Save vendor changes"}</button></div>}><VendorForm formId={formId} vendor={vendor} categories={categories} onSubmit={onSubmit}/></Modal>;
}