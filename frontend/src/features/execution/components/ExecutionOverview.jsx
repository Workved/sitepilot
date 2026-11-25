import { CircleDot, Plus } from "lucide-react";
import { Pill } from "../../../components/ui";

const prettyStatus = value => String(value || "assigned").replaceAll("_", " ");

const metricTones = {
  blue: "[&>div>span]:bg-blue-50 [&>div>span]:text-blue-700",
  orange: "[&>div>span]:bg-amber-50 [&>div>span]:text-amber-700",
  red: "[&>div>span]:bg-rose-50 [&>div>span]:text-rose-700 [&>p]:text-rose-600",
  green: "[&>div>span]:bg-emerald-50 [&>div>span]:text-emerald-700",
  violet: "[&>div>span]:bg-violet-50 [&>div>span]:text-violet-700",
};

export function ExecutionMetric({ icon, label, value, helper, tone, progress }) {
  return <article className={`min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_10px_28px_rgba(27,47,76,0.065)] [&>div]:flex [&>div]:items-center [&>div]:gap-2 [&>div>span]:grid [&>div>span]:size-9 [&>div>span]:place-items-center [&>div>span]:rounded-xl [&>strong]:mt-3 [&>strong]:block [&>strong]:font-serif [&>strong]:text-3xl [&>p]:m-0 [&>p]:mt-1 [&>p]:text-xs [&>p]:font-black [&>p]:text-emerald-600 [&>i]:mt-3 [&>i]:block [&>i]:h-1.5 [&>i]:overflow-hidden [&>i]:rounded-full [&>i]:bg-slate-200 [&>i>b]:block [&>i>b]:h-full [&>i>b]:rounded-full [&>i>b]:bg-emerald-500 ${metricTones[tone] || metricTones.blue}`}><div><span>{icon}</span><small>{label}</small></div><strong>{value}</strong><p>{helper}</p>{progress !== undefined && <i><b style={{ width: `${progress}%` }} /></i>}</article>;
}

export function DayColumn({ day, tasks, canManage, add, select }) {
  return <article className="min-w-0 border-r border-slate-200 last:border-0 max-[720px]:rounded-2xl max-[720px]:border">
    <header className="grid place-items-center p-3 text-center"><small className="font-medium text-slate-600">Day {day.day_no}</small><strong className="text-xs">{new Date(day.scheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</strong></header>
    <div className="grid gap-2 px-2 pb-3">
      {tasks.map(task => <button type="button" className={`grid min-h-16 grid-cols-[8px_minmax(0,1fr)_auto] items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-left text-slate-900 ${task.is_overdue ? "!border-rose-300 !bg-rose-50" : task.rescheduled_date ? "!border-amber-300 !bg-amber-50" : ""}`} key={task.id} onClick={() => select(task)}>
        <span className={`size-1.5 rounded-full ${task.is_overdue || task.priority === "high" ? "bg-rose-500" : task.priority === "low" ? "bg-emerald-500" : "bg-blue-500"}`} />
        <div className="grid min-w-0 gap-1"><strong className="truncate text-xs">{task.title}</strong><small className="truncate text-xs text-slate-500">{task.subcontractor_name || task.contractor_name || "Internal task"}</small>{task.rescheduled_date && <small className="truncate text-xs font-bold text-orange-700">Revised · {new Date(task.rescheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</small>}</div>
        <Pill tone={task.is_overdue ? "red" : task.status === "completed" ? "green" : task.priority === "high" ? "orange" : "blue"}>{task.is_overdue ? `Overdue ${task.overdue_days}d` : prettyStatus(task.status)}</Pill>
      </button>)}
      {canManage && <button type="button" className="flex min-h-11 items-center justify-center gap-2 rounded-xl border border-dashed border-blue-300 bg-white font-medium text-blue-700" onClick={add}><Plus /> Add task</button>}
      {!tasks.length && !canManage && <EmptySmall text="No tasks planned" />}
    </div>
  </article>;
}
export function TeamMember({ icon, name, role, phone }) {
  return <article><span>{icon}</span><div><strong>{name}</strong><small>{role}</small><p>{phone || "Phone not added"}</p></div></article>;
}

export function EmptySmall({ text }) {
  return <div className="exec-empty-small grid place-items-center gap-2 p-7 text-center text-xs text-slate-400 [&_svg]:size-5"><CircleDot /><span>{text}</span></div>;
}
