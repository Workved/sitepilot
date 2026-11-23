import { cn } from "../../../utils/cn";

export function KpiCard({ icon, tone, label, value, hint, className }) {
  return <div className={cn("flex items-center gap-3 rounded-2xl border p-4", tone, className)}>
    <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-white/70">{icon}</span>
    <div className="min-w-0">
      <p className="text-xs font-bold text-slate-500">{label}</p>
      <p className="text-2xl font-normal leading-tight text-slate-950">{value}</p>
      {hint && <p className="truncate text-[11px] font-semibold text-slate-500">{hint}</p>}
    </div>
  </div>;
}
