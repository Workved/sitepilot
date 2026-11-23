import { AlertTriangle, Building2, Mail, MessageCircle, Phone, X } from "lucide-react";
import { useEffect } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../../utils/cn";
import { plural } from "../broadcastFormat";
import { GROUP_META, GROUP_ORDER } from "./RecipientGroupSelector";
import { StatusChip } from "./StatusChip";

const CHANNEL_META = {
  whatsapp: { label: "WhatsApp", icon: MessageCircle },
  email: { label: "Email", icon: Mail },
  in_app: { label: "In-app", icon: MessageCircle },
};

export function groupRecipients(recipients) {
  const groups = GROUP_ORDER.map(type => ({ type, label: GROUP_META[type].long, items: recipients.filter(item => item.recipient_type === type) }));
  const known = new Set(GROUP_ORDER);
  const other = recipients.filter(item => !known.has(item.recipient_type));
  if (other.length) groups.push({ type: "other", label: "Others", items: other });
  return groups.filter(group => group.items.length);
}

// One person: name, role/company, how we can reach them, and on the right
// either their delivery status (sent messages) or an include switch (draft).
export function RecipientRow({ recipient, trailing, muted }) {
  const channels = recipient.channels || [];
  return <li className={cn("flex items-start gap-3 px-4 py-3", muted && "opacity-50")}>
    <div className="min-w-0 flex-1">
      <p className="truncate text-sm text-slate-950">{recipient.name}</p>
      <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-500">
        {recipient.company_name && <span className="inline-flex items-center gap-1"><Building2 size={12} aria-hidden="true"/>{recipient.company_name}</span>}
        {recipient.phone && <span className="inline-flex items-center gap-1"><Phone size={12} aria-hidden="true"/>{recipient.phone}</span>}
        {!recipient.phone && recipient.email && <span className="inline-flex items-center gap-1"><Mail size={12} aria-hidden="true"/>{recipient.email}</span>}
        {channels.length
          ? <span className="inline-flex items-center gap-1">{channels.map(channel => CHANNEL_META[channel]?.label || channel).join(", ")}</span>
          : <span className="inline-flex items-center gap-1 text-orange-700"><AlertTriangle size={12} aria-hidden="true"/>No way to reach them</span>}
      </p>
    </div>
    <div className="shrink-0 pt-0.5">{trailing}</div>
  </li>;
}

export function RecipientGroups({ recipients, renderTrailing, isMuted }) {
  return <div className="grid gap-3">
    {groupRecipients(recipients).map(group => <section key={group.type} aria-label={group.label} className="overflow-hidden rounded-2xl border border-line bg-white">
      <h4 className="flex items-center justify-between border-b border-line bg-slate-50 px-4 py-2 text-[13px] text-slate-700">
        {group.label}<span className="tabular-nums text-slate-400">{group.items.length}</span>
      </h4>
      <ul className="divide-y divide-line">
        {group.items.map(recipient => <RecipientRow key={recipient.key || recipient.id} recipient={recipient} trailing={renderTrailing(recipient)} muted={isMuted?.(recipient)}/>)}
      </ul>
    </section>)}
  </div>;
}

// Right-side drawer used while composing: shows exactly who the selected
// groups resolve to and lets you leave individual people out.
export function RecipientPreviewDrawer({ title, subtitle, recipients = [], readOnly = false, excludedKeys, onToggleExclude, onClose }) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = event => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", onKey); };
  }, [onClose]);

  const includedCount = readOnly ? recipients.length : recipients.filter(item => !excludedKeys?.has(item.key)).length;
  const missingContactCount = recipients.filter(item => !(item.channels || []).length).length;

  // Portaled: it opens from inside the composer modal.
  return createPortal(<>
    <div className="fixed inset-0 z-[60] bg-slate-950/30" onClick={onClose} aria-hidden="true"/>
    <aside className="fixed inset-y-0 right-0 z-[70] flex w-full flex-col bg-canvas shadow-[-16px_0_50px_rgba(21,23,26,.14)] sm:w-[520px]" role="dialog" aria-label="Recipient preview">
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-line bg-white px-5 py-4">
        <div className="min-w-0">
          <h2 className="truncate text-[17px] font-medium text-slate-950">{title}</h2>
          <p className="mt-0.5 text-sm text-slate-500">
            {subtitle ? `${subtitle} · ` : ""}{plural(includedCount, "person", "people")} will get it
            {missingContactCount > 0 && <span className="text-orange-700">, {missingContactCount} can't be reached</span>}
          </p>
        </div>
        <button type="button" aria-label="Close recipient preview" onClick={onClose} className="grid size-10 shrink-0 place-items-center rounded-xl text-slate-500 transition hover:bg-slate-100 hover:text-slate-950"><X size={18}/></button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
        {recipients.length === 0
          ? <p className="rounded-2xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">No one is in the selected groups yet.</p>
          : <RecipientGroups recipients={recipients}
              isMuted={recipient => !readOnly && excludedKeys?.has(recipient.key)}
              renderTrailing={recipient => readOnly
                ? <StatusChip status={recipient.delivery_status}/>
                : <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600">
                    Include
                    <input type="checkbox" checked={!excludedKeys?.has(recipient.key)} onChange={() => onToggleExclude(recipient.key)} className="size-4 rounded border-slate-300 accent-slate-950"/>
                  </label>}/>}
      </div>
    </aside>
  </>, document.body);
}
