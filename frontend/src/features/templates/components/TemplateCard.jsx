import { CalendarClock, CheckCircle2, ChevronRight, GitBranch, ListChecks, ShieldCheck } from "lucide-react";
import { Button, Pill } from "../../../components/ui";

export function formatTemplateDate(value) {
  if (!value) return "Not published";
  return new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function statusTone(status) {
  if (status === "archived") return "gray";
  return status === "published" ? "green" : "orange";
}

function Count({ icon: Icon, value, label }) {
  return <div className="rounded-xl border border-line bg-slate-50 px-3 py-2.5"><span className="flex items-center gap-1.5 text-xs text-slate-500"><Icon size={13}/>{label}</span><strong className="mt-1 block text-lg font-light tabular-nums text-slate-950">{value}</strong></div>;
}

export function TemplateCard({ item, selected, onSelect }) {
  return <article data-testid={`template-card-${item.version_id}`} data-selected={selected || undefined} className={`rounded-[20px] border bg-white p-4 transition ${selected ? "border-blue-300 ring-4 ring-blue-600/10" : "border-line"}`}>
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><span className="text-xs font-medium text-slate-500">{item.template_code}</span><h3 className="mt-0.5 text-[15px] leading-6 text-slate-950">{item.template_name}</h3></div><Pill tone={statusTone(item.status)}>{item.status}</Pill></div>
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500"><span>Version {item.version_no}</span><span>{item.duration_days} days</span>{item.is_current_published && <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-emerald-800"><CheckCircle2 size={13}/> Current published</span>}</div>
    <div className="mt-4 grid grid-cols-3 gap-2"><Count icon={ListChecks} value={item.task_count} label="Tasks"/><Count icon={GitBranch} value={item.dependency_count} label="Links"/><Count icon={ShieldCheck} value={item.gate_count} label="Gates"/></div>
    <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-3"><span className="inline-flex items-center gap-1.5 text-xs text-slate-500"><CalendarClock size={14}/>{formatTemplateDate(item.published_at)}</span><Button size="sm" variant="secondary" aria-pressed={selected} onClick={() => onSelect(item.version_id)}>View Details <ChevronRight size={15}/></Button></div>
  </article>;
}