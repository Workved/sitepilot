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
  return <div className="rounded-xl border border-slate-200/80 bg-slate-50 px-3 py-2.5"><span className="flex items-center gap-1.5 text-xs font-medium text-slate-500"><Icon size={13}/>{label}</span><strong className="mt-1 block text-base font-black text-slate-900">{value}</strong></div>;
}

export function TemplateCard({ item, selected, onSelect }) {
  return <article data-testid={`template-card-${item.version_id}`} data-selected={selected || undefined} className={`rounded-[22px] border bg-white p-4 transition ${selected ? "border-blue-400 ring-4 ring-blue-600/10" : "border-slate-200"}`}>
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><span className="text-xs font-medium text-slate-500">{item.template_code}</span><h3 className="mt-1 text-base font-black leading-6 text-slate-950">{item.template_name}</h3></div><Pill tone={statusTone(item.status)}>{item.status}</Pill></div>
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs font-bold text-slate-500"><span>Version {item.version_no}</span><span aria-hidden="true">/</span><span>{item.duration_days} days</span>{item.is_current_published && <span className="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 size={14}/> Current published</span>}</div>
    <div className="mt-4 grid grid-cols-3 gap-2"><Count icon={ListChecks} value={item.task_count} label="Tasks"/><Count icon={GitBranch} value={item.dependency_count} label="Links"/><Count icon={ShieldCheck} value={item.gate_count} label="Gates"/></div>
    <div className="mt-4 flex items-center justify-between gap-3 border-t border-slate-100 pt-3"><span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500"><CalendarClock size={14}/>{formatTemplateDate(item.published_at)}</span><Button size="sm" variant="secondary" aria-pressed={selected} onClick={() => onSelect(item.version_id)}>View Details <ChevronRight size={15}/></Button></div>
  </article>;
}