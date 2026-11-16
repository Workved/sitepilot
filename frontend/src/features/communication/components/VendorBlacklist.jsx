import { useState } from "react";
import { Ban, ShieldOff } from "lucide-react";
import { Modal, Pill } from "../../../components/ui";

// The only vendor status: blacklisted. A vendor on the list is simply a
// vendor - nothing is shown for that. Mirrors the backend's
// BLACKLIST_ROLES / UNBLACKLIST_ROLES.
export const canBlacklist = user => ["super_admin", "admin", "project_manager", "supervisor"].includes(user?.role);
export const canUnblacklist = user => ["super_admin", "admin"].includes(user?.role);

// A sub-vendor is blocked while its main vendor is blacklisted.
export const isBlocked = vendor => Boolean(vendor?.blacklisted || vendor?.blocked_by_parent);

export function BlacklistPill({ vendor }) {
  if (vendor?.blacklisted) return <Pill tone="red">Blacklisted</Pill>;
  if (vendor?.blocked_by_parent) return <Pill tone="red">Main vendor blacklisted</Pill>;
  return null;
}

function formatDate(iso) {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "";
}

export function BlacklistBanner({ vendor, parentVendor }) {
  if (vendor?.blacklisted) {
    const who = [vendor.blacklisted_by_name && `by ${vendor.blacklisted_by_name}`, vendor.blacklisted_at && `on ${formatDate(vendor.blacklisted_at)}`].filter(Boolean).join(" ");
    return <div role="status" className="mt-3 flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
      <Ban className="mt-0.5 shrink-0" size={18}/>
      <div><strong className="block">Blacklisted{who ? ` ${who}` : ""}</strong><span className="mt-1 block whitespace-pre-line">Reason: {vendor.blacklist_reason}</span><span className="mt-1 block text-xs text-rose-700">Can't be added to projects or tasks.</span></div>
    </div>;
  }
  if (vendor?.blocked_by_parent) {
    return <div role="status" className="mt-3 flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
      <Ban className="mt-0.5 shrink-0" size={18}/>
      <span>Its main vendor{parentVendor ? ` ${parentVendor.name}` : ""} is blacklisted, so this sub-vendor can't be added to projects or tasks.</span>
    </div>;
  }
  return null;
}

// Blacklist (or remove from the blacklist) with a required reason.
export function BlacklistModal({ vendor, mode, projectCount = 0, subVendorCount = 0, saving = false, error = "", onClose, onSubmit }) {
  const [reason, setReason] = useState("");
  const removing = mode === "remove";
  const tooShort = reason.trim().length < 4;
  const effects = removing
    ? ["They can be added to projects and tasks again.", "Projects and tasks they were removed from are not restored."]
    : [
        projectCount > 0 ? `They'll be removed from ${projectCount} current project${projectCount === 1 ? "" : "s"} and their tasks (history is kept).` : "They'll be removed from any current projects and tasks (history is kept).",
        subVendorCount > 0 ? `Their ${subVendorCount} sub-vendor${subVendorCount === 1 ? " is" : "s are"} blocked too.` : null,
        "They won't be sent any message about this.",
        "Only an Admin can remove them from the blacklist.",
      ].filter(Boolean);

  return <Modal className="max-w-lg" title={removing ? `Remove ${vendor.name} from the blacklist?` : `Blacklist ${vendor.name}?`} onClose={onClose}>
    <form onSubmit={event => { event.preventDefault(); if (!tooShort) onSubmit(reason.trim()); }} className="grid gap-4">
      <ul className="grid gap-1.5 rounded-xl bg-slate-50 p-3 text-sm text-slate-700">{effects.map(item => <li key={item} className="flex gap-2"><span aria-hidden="true">•</span>{item}</li>)}</ul>
      <label className="grid gap-2 text-sm font-black text-slate-700">{removing ? "Why remove them from the blacklist?" : "Reason for blacklisting"}
        <textarea autoFocus value={reason} onChange={event => setReason(event.target.value)} maxLength={1000} className="min-h-24 w-full resize-y rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-50" placeholder={removing ? "e.g. Issue resolved after meeting" : "e.g. Repeated delays and poor workmanship on site"} required/>
      </label>
      {error && <p role="alert" className="text-sm font-bold text-rose-700">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="min-h-11 rounded-xl border border-slate-200 px-4 text-sm font-black text-slate-700 hover:bg-slate-50">Cancel</button>
        <button type="submit" disabled={tooShort || saving} className={`flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-black text-white disabled:cursor-not-allowed disabled:opacity-60 ${removing ? "bg-blue-700 hover:bg-blue-800" : "bg-rose-700 hover:bg-rose-800"}`}>
          {removing ? <ShieldOff size={16}/> : <Ban size={16}/>}{saving ? "Saving..." : removing ? "Remove from blacklist" : "Blacklist vendor"}
        </button>
      </div>
    </form>
  </Modal>;
}
