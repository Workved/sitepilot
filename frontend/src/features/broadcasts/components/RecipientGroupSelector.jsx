import { Briefcase, Building2, Check, ContactRound, HardHat, UserRound } from "lucide-react";
import { cn } from "../../../utils/cn";

export const GROUP_META = {
  project_manager: { label: "PMs", long: "Project managers", icon: UserRound },
  site_supervisor: { label: "Supervisors", long: "Site supervisors", icon: HardHat },
  internal_employee: { label: "Internal Employees", long: "Internal employees", icon: Briefcase },
  vendor: { label: "Vendors", long: "Vendors", icon: Building2 },
  vendor_contact: { label: "Vendor Contacts", long: "Vendor contacts", icon: ContactRound },
};
export const GROUP_ORDER = Object.keys(GROUP_META);

// Toggle chips, one per group, each with how many people it holds. Empty
// groups stay visible (so it is clear nobody is there) but can't be picked.
export function RecipientGroupSelector({ counts, selectedGroups, onToggleGroup, onToggleAll, loading }) {
  const allSelected = GROUP_ORDER.every(group => selectedGroups.has(group));

  return <div className="grid gap-2">
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Recipient groups">
      {GROUP_ORDER.map(group => {
        const meta = GROUP_META[group];
        const Icon = meta.icon;
        const active = selectedGroups.has(group);
        const count = counts[group] ?? 0;
        return <button key={group} type="button" onClick={() => onToggleGroup(group)} aria-pressed={active}
          className={cn("inline-flex h-9 items-center gap-2 rounded-full border pl-2.5 pr-3 text-[13px] transition",
            active ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300")}>
          {active ? <Check size={14} aria-hidden="true"/> : <Icon size={14} aria-hidden="true" className="text-slate-500"/>}
          {meta.label}
          <span className={cn("tabular-nums", active ? "text-white/70" : "text-slate-400")}>{loading ? "…" : count}</span>
        </button>;
      })}
    </div>
    <button type="button" onClick={() => onToggleAll(!allSelected)} className="w-fit text-xs text-blue-700 hover:underline">
      {allSelected ? "Clear all groups" : "Select all groups"}
    </button>
  </div>;
}
