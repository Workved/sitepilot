import { useEffect, useRef, useState } from "react";
import { Building2, MessageCircle, MoreVertical, Phone, ShieldCheck, UserRound } from "lucide-react";
import { Modal } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { CategorySelector } from "./CategorySelector";
import { BlacklistPill } from "./VendorBlacklist";

const cleanPhone = (value = "") => value.replace(/[^\d+]/g, "");
const inputClass = "min-h-12 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10";

export function QuickActions({ contact }) {
  if (!contact) return null;
  return <div className="flex gap-1.5" onClick={event => event.stopPropagation()}>
    <a aria-label={`Call ${contact.name}`} title="Call" className="grid size-8 place-items-center rounded-lg border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50" href={`tel:${cleanPhone(contact.phone)}`}><Phone size={14}/></a>
    <a aria-label={`WhatsApp ${contact.name}`} title="WhatsApp" className="grid size-8 place-items-center rounded-lg border border-emerald-100 bg-emerald-50 text-emerald-700 hover:bg-emerald-100" href={`https://wa.me/${cleanPhone(contact.whatsapp || contact.phone).replace("+", "")}`} target="_blank" rel="noreferrer"><MessageCircle size={14}/></a>
  </div>;
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
      className="grid size-8 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"><MoreVertical size={16}/></button>
    {open && <div className="absolute right-0 top-[calc(100%+4px)] z-20 grid w-48 gap-0.5 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      {items.map(item => <button key={item.label} type="button" onClick={() => { setOpen(false); item.onClick(); }}
        className={cn("rounded-xl px-3 py-2 text-left text-sm transition", item.danger ? "text-rose-700 hover:bg-rose-50" : "text-slate-800 hover:bg-slate-50")}>{item.label}</button>)}
    </div>}
  </div>;
}

// Columns shared by the list header and every row.
export const VENDOR_COLUMNS = "md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1.3fr)_5.5rem_7.5rem]";

// One vendor as a table-style row. Sub-vendors render indented under their
// main vendor (`nested`), so the hierarchy reads at a glance.
export function VendorRow({ vendor, primary, projectCount, selected, nested = false, parentName, onSelect, onEdit, onDelete, onBlacklist, onUnblacklist, canBlacklist = false, canUnblacklist = false }) {
  const isMain = vendor.engagement_type === "main";
  const trades = (vendor.categories?.length ? vendor.categories : [vendor.category]).filter(Boolean);
  const menuItems = [
    ...(onEdit ? [{ label: "Edit vendor", onClick: onEdit }] : []),
    ...(!vendor.blacklisted && canBlacklist ? [{ label: "Blacklist vendor", onClick: onBlacklist, danger: true }] : []),
    ...(vendor.blacklisted && canUnblacklist ? [{ label: "Remove from blacklist", onClick: onUnblacklist }] : []),
    ...(onDelete ? [{ label: "Delete vendor", onClick: onDelete, danger: true }] : []),
  ];

  return <article onClick={onSelect} aria-current={selected ? "true" : undefined}
    className={cn("grid cursor-pointer items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors hover:bg-slate-50 md:px-5", VENDOR_COLUMNS, selected && "bg-blue-50/50")}>
    <div className={cn("flex min-w-0 items-center gap-3", nested && "md:pl-8")}>
      {nested && <span className="hidden h-5 w-3 shrink-0 rounded-bl-md border-b border-l border-slate-300 md:-ml-5 md:mr-0 md:block" aria-hidden="true"/>}
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-[10px] text-xs font-medium", vendor.blacklisted ? "bg-rose-50 text-rose-800" : isMain ? "bg-blue-50 text-blue-800" : "bg-emerald-50 text-emerald-800")}>{vendor.name.slice(0, 2).toUpperCase()}</span>
      <div className="min-w-0">
        <h3 className="truncate text-sm text-slate-950">{vendor.name}</h3>
        <p className="truncate text-xs text-slate-500">{isMain ? "Main vendor" : `Sub-vendor${parentName ? ` of ${parentName}` : ""}`}</p>
      </div>
    </div>

    <div className="flex min-w-0 flex-wrap gap-1">
      {trades.slice(0, 2).map(trade => <span key={trade} className="truncate rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{trade}</span>)}
      {trades.length > 2 && <span className="rounded-md px-1 py-0.5 text-xs text-slate-500" title={trades.slice(2).join(", ")}>+{trades.length - 2}</span>}
    </div>

    <div className="flex min-w-0 items-center justify-between gap-3">
      {primary
        ? <div className="min-w-0"><strong className="block truncate text-sm font-normal text-slate-950">{primary.name}</strong><span className="block truncate text-xs text-slate-500">{[primary.designation, primary.phone].filter(Boolean).join(", ")}</span></div>
        : <span className="text-xs text-orange-700">No contact yet</span>}
      <QuickActions contact={primary}/>
    </div>

    <div className="text-sm tabular-nums text-slate-950 md:text-right"><span className="text-xs text-slate-500 md:hidden">Projects </span>{projectCount}</div>

    <div className="flex items-center justify-end gap-1">
      <BlacklistPill vendor={vendor}/>
      {menuItems.length > 0 && <RowMenu items={menuItems}/>}
    </div>
  </article>;
}

function SectionHeading({ icon: Icon, eyebrow, title, text }) {
  return <header className="col-span-full flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-700"><Icon size={18}/></span><div><p className="text-xs text-slate-500">{eyebrow}</p><h3 className="mt-0.5 text-[15px] font-medium text-slate-950">{title}</h3>{text && <p className="mt-0.5 text-[13px] leading-5 text-slate-500">{text}</p>}</div></header>;
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
    {fixedMainVendor && <div className="col-span-full flex items-center gap-4 rounded-[20px] border border-line bg-white p-4"><span className="grid size-11 place-items-center rounded-xl bg-blue-50 text-blue-800"><Building2 size={20}/></span><div><span className="text-xs text-slate-500">Approved parent vendor</span><strong className="mt-0.5 block font-normal text-slate-950">{fixedMainVendor.name}</strong></div><ShieldCheck className="ml-auto text-emerald-600"/><input type="hidden" name="main_contractor_id" value={fixedMainVendor.id}/></div>}

    <section className="col-span-full grid grid-cols-2 gap-4 rounded-[20px] border border-line bg-slate-50 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={Building2} eyebrow="Company" title="Vendor profile" text="Core identity."/>
      <label className="col-span-full grid gap-1.5 text-sm font-medium text-slate-700 max-[720px]:col-span-1">Company name<input className={inputClass} name="name" defaultValue={vendor?.name || ""} required/></label>
    </section>

    <CategorySelector categories={categories} selected={selectedCategories} onChange={value => { setSelectedCategories(value); setCategoryError(""); }} error={categoryError}/>

    {includeContact && <section className="col-span-full grid grid-cols-2 gap-4 rounded-[20px] border border-line bg-slate-50 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={UserRound} eyebrow="Primary contact" title="Who should the site team call?" text="This contact is created as the vendor's primary person."/>
      <label className="grid gap-1.5 text-sm font-medium text-slate-700">Contact name<input className={inputClass} name="contact_person" required/></label>
      <label className="grid gap-1.5 text-sm font-medium text-slate-700">Designation<input className={inputClass} name="designation" placeholder="Site supervisor, owner…"/></label>
      <label className="grid gap-1.5 text-sm font-medium text-slate-700">Phone<input className={inputClass} name="phone" inputMode="tel" required/></label>
      <label className="grid gap-1.5 text-sm font-medium text-slate-700">WhatsApp<input className={inputClass} name="whatsapp" inputMode="tel" placeholder="Use phone number if blank"/></label>
    </section>}

    <section className="col-span-full grid grid-cols-2 gap-4 rounded-[20px] border border-line bg-slate-50 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={ShieldCheck} eyebrow="Business details" title="Compliance and communication" text="Optional information that helps your operations team."/>
      <label className="grid gap-1.5 text-sm font-medium text-slate-700">Email<input className={inputClass} name="email" type="email" defaultValue={vendor?.email || ""}/></label>
      <label className="grid gap-1.5 text-sm font-medium text-slate-700">GST number<input className={inputClass} name="gst_number" defaultValue={vendor?.gst_number || ""}/></label>
      <label className="col-span-full grid gap-1.5 text-sm font-medium text-slate-700 max-[720px]:col-span-1">Address<textarea className={`${inputClass} min-h-24 resize-y`} name="address" defaultValue={vendor?.address || ""}/></label>
      <label className="col-span-full grid gap-1.5 text-sm font-medium text-slate-700 max-[720px]:col-span-1">Internal notes<textarea className={`${inputClass} min-h-24 resize-y`} name="notes" defaultValue={vendor?.notes || ""} placeholder="Scope, working preferences, important context…"/></label>
    </section>

  </form>;
}

const submitButtonClass = "min-h-11 rounded-xl bg-slate-950 px-5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60";

export function CompanyModal({ title, categories, fixedMainContractor, saving = false, onClose, onSubmit }) {
  const formId = "vendor-company-form";
  const submitLabel = fixedMainContractor ? "Create sub-vendor" : "Create main vendor";
  return <Modal className="max-w-5xl" title={title} subtitle={fixedMainContractor ? "Create a sub-vendor inside the approved parent relationship." : "Create a structured vendor profile for project and task assignment."} onClose={onClose} footer={<div className="flex justify-end"><button type="submit" form={formId} disabled={saving} className={submitButtonClass}>{saving ? "Saving..." : submitLabel}</button></div>}><VendorForm formId={formId} categories={categories} fixedMainVendor={fixedMainContractor} includeContact onSubmit={onSubmit}/></Modal>;
}

export function ProfileModal({ vendor, categories, saving = false, onClose, onSubmit }) {
  const formId = "vendor-profile-form";
  return <Modal className="max-w-5xl" title={`Edit ${vendor.name}`} subtitle="Update company details, categories and assignment availability." onClose={onClose} footer={<div className="flex justify-end"><button type="submit" form={formId} disabled={saving} className={submitButtonClass}>{saving ? "Saving..." : "Save vendor changes"}</button></div>}><VendorForm formId={formId} vendor={vendor} categories={categories} onSubmit={onSubmit}/></Modal>;
}