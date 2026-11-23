import { AlertTriangle, ArrowRight, CheckCircle2, GitBranch } from "lucide-react";
import { Pill } from "../../../components/ui";

export function dependencyTypeLabel(value) {
  if (value === "finish_to_start") return "Finish first";
  if (value === "start_to_start") return "Start together";
  return value ? value.replaceAll("_", " ") : "Unknown";
}

export function dependencyTaskMeta(task) {
  if (!task) return "Task reference missing";
  const parts = [];
  if (task.phase) parts.push(task.phase);
  if (task.day != null) parts.push(`Day ${task.day}`);
  else parts.push("Pre-Activation");
  return parts.join(" / ");
}

export function DependencyTaskLink({ task, onFocusTask }) {
  if (!task) return <span className="font-bold text-rose-700">Missing task</span>;
  return <button type="button" className="group min-w-0 text-left" onClick={() => onFocusTask?.(task.code)} title={`Open ${task.code} in Tasks`}>
    <span className="tabular-nums text-xs font-medium text-slate-600 underline-offset-4 group-hover:underline">{task.code}</span>
    <strong className="mt-1 block text-sm leading-5 text-slate-950">{task.title || "Untitled task"}</strong>
    <span className="mt-1 block text-xs font-semibold text-slate-500">{dependencyTaskMeta(task)}</span>
  </button>;
}

export function TemplateDependencyCard({ dependency, onFocusTask }) {
  const invalid = dependency.validation_state === "invalid";
  return <article data-testid={`dependency-card-${dependency.id}`} className={`rounded-2xl border bg-white p-4 ${invalid ? "border-amber-300" : "border-slate-200"}`}>
    <div className="flex items-center justify-between gap-3">
      <span className="inline-flex items-center gap-2 text-xs font-medium text-slate-500"><GitBranch size={15} className="text-slate-500"/> Link {dependency.sequence_no}</span>
      <Pill tone={invalid ? "orange" : "green"}>{invalid ? "Review" : "Valid"}</Pill>
    </div>
    <div className="mt-4 grid grid-cols-[minmax(0,1fr)_32px_minmax(0,1fr)] items-center gap-2">
      <DependencyTaskLink task={dependency.predecessor} onFocusTask={onFocusTask}/>
      <span className="grid size-8 place-items-center rounded-full bg-slate-100 text-slate-500"><ArrowRight size={16}/></span>
      <DependencyTaskLink task={dependency.successor} onFocusTask={onFocusTask}/>
    </div>
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
      <Pill tone="blue">{dependencyTypeLabel(dependency.dependency_type)}</Pill>
      <Pill tone={dependency.blocking ? "red" : "gray"}>{dependency.blocking ? "Enforced" : "Advisory only"}</Pill>
    </div>
    <p className="mt-3 text-xs font-semibold leading-5 text-slate-600">{dependency.rule_text || "No note."}</p>
    <div className={`mt-3 flex items-start gap-2 rounded-xl px-3 py-2 text-xs font-bold ${invalid ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>
      {invalid ? <AlertTriangle className="mt-0.5 shrink-0" size={15}/> : <CheckCircle2 className="mt-0.5 shrink-0" size={15}/>}
      <span>{invalid ? dependency.validation_issues.join(", ").replaceAll("_", " ") : "No problems"}</span>
    </div>
  </article>;
}
