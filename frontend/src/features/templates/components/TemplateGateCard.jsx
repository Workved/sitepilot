import { AlertTriangle, CheckCircle2, ChevronDown, ShieldAlert, ShieldCheck } from "lucide-react";
import { Pill } from "../../../components/ui";
import { gateDueDateText } from "./templateAuthoringOptions";

export function gateMappingLabel(value) {
  if (value === "exact") return "Linked to tasks";
  if (value === "broad_text") return "Imported wording";
  if (value === "unmapped") return "Not linked";
  return value ? value.replaceAll("_", " ") : "Unknown";
}

export function GateTaskLink({ task, onFocusTask }) {
  return <button type="button" className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left hover:border-blue-300 hover:bg-blue-50" onClick={() => onFocusTask?.(task.code)} title={`Open ${task.code} in Tasks`}>
    <span className="font-mono text-[10px] font-black tracking-[.08em] text-blue-700">{task.code}</span>
    <strong className="mt-0.5 block text-xs leading-4 text-slate-900">{task.title || "Untitled task"}</strong>
  </button>;
}

export function TemplateGateDetails({ gate, onFocusTask }) {
  const broad = gate.mapping_classification === "broad_text";
  return <div className="grid gap-3 border-t border-slate-100 pt-3">
    {gate.description && <p className="text-xs font-medium leading-5 text-slate-600">{gate.description}</p>}
    <dl className="grid gap-2 text-xs sm:grid-cols-2">
      <div><dt className="font-black text-slate-500">When needed</dt><dd className="mt-1 font-semibold text-slate-900">{gateDueDateText(gate)}</dd></div>
      <div><dt className="font-black text-slate-500">If late</dt><dd className="mt-1 font-semibold text-slate-900">{gate.impact || "Not specified"}</dd></div>
    </dl>
    {broad ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      <strong className="flex items-center gap-2"><ShieldAlert size={15}/> Imported wording</strong>
      <p className="mt-1 font-medium leading-5">Kept as imported. It is not linked to specific tasks, and no link has been assumed.</p>
      <p className="mt-2 rounded-lg bg-white/70 px-2.5 py-2 font-bold">{gate.broad_mapping_text || "Broad mapping text missing"}</p>
    </div> : gate.affected_tasks.length ? <div>
      <strong className="text-xs font-black text-slate-600">Required before</strong>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">{gate.affected_tasks.map(task => <GateTaskLink key={task.id} task={task} onFocusTask={onFocusTask}/>)}</div>
    </div> : <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs font-bold text-rose-800">Not linked to any task.</p>}
  </div>;
}

export function TemplateGateCard({ gate, onFocusTask }) {
  const invalid = gate.validation_state === "invalid";
  return <article data-testid={`gate-card-${gate.id}`} className={`rounded-2xl border bg-white p-4 ${invalid ? "border-amber-300" : "border-slate-200"}`}>
    <div className="flex items-start justify-between gap-3">
      <div><span className="font-mono text-[11px] font-black tracking-[.12em] text-blue-700">{gate.code}</span><h4 className="mt-1 text-sm font-black text-slate-950">{gate.approval_name || "Unnamed approval"}</h4><p className="mt-1 text-xs font-semibold text-slate-500">{gate.external_party || "External party not specified"}</p></div>
      <Pill tone={invalid ? "orange" : "green"}>{invalid ? "Review" : "Valid"}</Pill>
    </div>
    <div className="mt-3 flex flex-wrap gap-2"><Pill tone={gate.mapping_classification === "exact" ? "blue" : "orange"}>{gateMappingLabel(gate.mapping_classification)}</Pill>{gate.requires_configuration && <Pill tone="orange">Needs tasks linked</Pill>}</div>
    <details className="group mt-4">
      <summary className="flex cursor-pointer list-none items-center justify-between rounded-xl bg-slate-50 px-3 py-2 text-xs font-black text-slate-700">View details <ChevronDown size={15} className="transition group-open:rotate-180"/></summary>
      <div className="mt-3"><TemplateGateDetails gate={gate} onFocusTask={onFocusTask}/></div>
    </details>
    <div className={`mt-3 flex items-start gap-2 rounded-xl px-3 py-2 text-xs font-bold ${invalid ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>{invalid ? <AlertTriangle className="mt-0.5 shrink-0" size={15}/> : <CheckCircle2 className="mt-0.5 shrink-0" size={15}/>}<span>{invalid ? gate.validation_issues.join(", ").replaceAll("_", " ") : "No problems"}</span></div>
  </article>;
}
