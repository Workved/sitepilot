import { AlertTriangle, CalendarRange, CheckCircle2 } from "lucide-react";
import { Pill } from "../../../components/ui";

export function formatPlannedDays(task) {
  if (task.schedule_classification === "pre_activation") return "Before activation";
  if (task.planned_start_day == null || task.planned_end_day == null) return "Day not configured";
  if (task.planned_start_day === task.planned_end_day) return `Day ${task.planned_start_day}`;
  return `Days ${task.planned_start_day}-${task.planned_end_day}`;
}

export function TemplateTaskCard({ task }) {
  const invalid = task.validation_state === "invalid";
  return <article data-testid={`task-card-${task.code}`} className={`rounded-2xl border bg-white p-4 ${invalid ? "border-amber-300" : "border-slate-200"}`}>
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <span className="tabular-nums text-xs font-medium text-slate-600">{task.code}</span>
        <h4 className="mt-1 text-sm font-medium leading-5 text-slate-950">{task.title || "Untitled task"}</h4>
      </div>
      <Pill tone={task.applicability === "conditional" ? "orange" : "blue"}>{task.applicability || "Unknown"}</Pill>
    </div>
    <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-slate-500">
      <span className="rounded-lg bg-slate-100 px-2.5 py-1">{task.phase || "No phase"}</span>
      <span className="rounded-lg bg-slate-100 px-2.5 py-1">{task.category || "No category"}</span>
    </div>
    <div className="mt-3 flex items-center justify-between gap-3 border-t border-slate-100 pt-3 text-xs font-bold">
      <span className="inline-flex items-center gap-1.5 text-slate-600"><CalendarRange size={15}/>{formatPlannedDays(task)}</span>
      <span className={`inline-flex items-center gap-1 ${invalid ? "text-amber-700" : "text-emerald-700"}`}>{invalid ? <AlertTriangle size={14}/> : <CheckCircle2 size={14}/>} {invalid ? "Review" : "Valid"}</span>
    </div>
    {invalid && <p className="mt-3 text-xs font-semibold leading-5 text-orange-800">{task.validation_issues.join(", ").replaceAll("_", " ")}</p>}
  </article>;
}