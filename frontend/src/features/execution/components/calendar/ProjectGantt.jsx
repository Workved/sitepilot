import "@svar-ui/react-gantt/all.css";
import { Gantt, Tooltip, Willow } from "@svar-ui/react-gantt";
import { ChevronDown, Lock } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { plannedRange } from "../executionViewHelpers";
import { formatDay, groupByPhase, taskState, TONES } from "./calendarModel";
import { chartRange, highlightWeekends, localDay, plusDays, scalesWithToday, todayLocal, ZOOMS } from "./svarSetup";

// Project Gantt on SVAR React Gantt (MIT). Read-only: dates change through
// the task's reschedule form (which records a reason), never by dragging.
// Phases are summary rows; each task bar is coloured by its state, shows
// progress, and carries its days late. Dependencies are drawn as links.

// Google-Calendar-style chips: a soft tint, a coloured left edge, dark text.
export const CHIP = {
  done: "bg-emerald-50 border-emerald-500 text-emerald-900",
  active: "bg-blue-50 border-blue-500 text-blue-900",
  review: "bg-violet-50 border-violet-500 text-violet-900",
  blocked: "bg-rose-50 border-rose-500 text-rose-900",
  planned: "bg-slate-50 border-slate-400 text-slate-700",
  cancelled: "bg-slate-100 border-slate-300 text-slate-400 line-through",
};
// Marker colours by status: the pin and end cap, and a lighter line.
const MARK = {
  done: { pin: "bg-emerald-600", line: "bg-emerald-300" },
  active: { pin: "bg-blue-600", line: "bg-blue-300" },
  review: { pin: "bg-violet-600", line: "bg-violet-300" },
  blocked: { pin: "bg-rose-600", line: "bg-rose-300" },
  planned: { pin: "bg-slate-500", line: "bg-slate-300" },
  cancelled: { pin: "bg-slate-300", line: "bg-slate-200" },
};


const isoOf = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

function progressOf(task, today) {
  if (task.lifecycle_status === "completed") return 100;
  if (!task.actual_start_at) return 0;
  const plan = plannedRange(task);
  if (!plan) return 10;
  const start = localDay(task.planned_start_date);
  const end = localDay(task.planned_end_date) || start;
  const total = (end - start) / 86400000 + 1;
  const done = (today - start) / 86400000 + 1;
  return Math.max(5, Math.min(95, Math.round((100 * done) / total)));
}

/** API tasks -> SVAR tasks (phase summary rows + task rows) and links. */
export function toGanttData(tasks, today) {
  const rows = [];
  const links = [];
  for (const group of groupByPhase(tasks.filter(task => plannedRange(task)))) {
    const phaseId = `phase:${group.phase}`;
    rows.push({ id: phaseId, text: group.phase, type: "summary", open: true, progress: group.pct, isPhase: true, count: group.tasks.length });
    for (const task of group.tasks) {
      const state = taskState(task, today);
      const start = localDay(task.planned_start_date);
      const end = plusDays(localDay(task.planned_end_date) || start, 1);
      rows.push({
        id: task.id, parent: phaseId, type: "task", text: `${task.original_code} · ${task.title}`, start, end,
        progress: progressOf(task, today), code: task.original_code, tone: state.tone, label: state.label, late: state.late, blocked: state.blocked, source: task,
      });
      for (const predecessorId of task.predecessor_ids || []) links.push({ id: `${predecessorId}>${task.id}`, source: predecessorId, target: task.id, type: "e2s" });
    }
  }
  const ids = new Set(rows.map(row => row.id));
  return { rows, links: links.filter(link => ids.has(link.source) && ids.has(link.target)) };
}

function TaskBar({ data }) {
  if (data.isPhase || data.type === "summary") return null;
  const name = data.source?.title || data.code;
  const mark = MARK[data.tone] || MARK.planned;
  // A timeline marker, not a block: a round pin where the task starts, a
  // slim line for how long it runs, a small cap where it ends. The name sits
  // above the marker, starting at the pin - so dependency arrows (which leave
  // the bar end at mid-height and turn down) never run through it.
  return <div className="relative h-full w-full" title={name}>
    <span className="pointer-events-none absolute bottom-[calc(50%+3px)] left-0 flex items-center gap-1.5 whitespace-nowrap text-[11px] font-bold leading-4 text-slate-800">
      {name}
      {data.late > 0 && <span className="rounded-full bg-rose-600 px-1.5 text-[10px] font-black leading-4 text-white">+{data.late}d</span>}
    </span>
    <span className={`absolute inset-x-1 top-[calc(50%+6px)] h-1.5 -translate-y-1/2 rounded-full ${mark.line}`}/>
    <span className={`absolute left-0 top-[calc(50%+6px)] z-10 grid size-3.5 -translate-y-1/2 place-items-center rounded-full ring-2 ring-white ${mark.pin}`}>{data.blocked && <Lock size={8} className="text-white"/>}</span>
    <span className={`absolute right-0 top-[calc(50%+6px)] z-10 size-2.5 -translate-y-1/2 rounded-full ring-2 ring-white ${mark.pin}`}/>
  </div>;
}

function makeTooltip(rowsById) {
  return function TooltipContent({ data }) { return <TaskTooltip row={rowsById.get(data?.task?.id)}/>; };
}

function TaskTooltip({ row }) {
  if (!row) return null;
  if (row.isPhase) return <div className="rounded-lg border border-slate-200 bg-white p-2 text-xs font-bold shadow">{row.text} · {row.count} tasks · {row.progress}% done</div>;
  const task = row.source;
  return <div className="w-72 rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-lg">
    <p className="font-black text-slate-900">{task.original_code} · {task.title}</p>
    <p className={`mt-1 font-bold ${TONES[row.tone]?.text || ""}`}>{row.label}{row.late > 0 ? ` · ${row.late} day${row.late === 1 ? "" : "s"} late` : ""}</p>
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-slate-600">
      <dt className="font-bold">Plan</dt><dd>{formatDay(task.planned_start_date)} - {formatDay(task.planned_end_date)}</dd>
      <dt className="font-bold">Actual</dt><dd>{task.actual_start_at ? `${formatDay(task.actual_start_at)} - ${task.actual_finish_at ? formatDay(task.actual_finish_at) : "ongoing"}` : "Not started"}</dd>
      {task.phase && <><dt className="font-bold">Phase</dt><dd>{task.phase}{task.category ? ` / ${task.category}` : ""}</dd></>}
      {task.vendor_name && <><dt className="font-bold">Vendor</dt><dd>{task.vendor_name}</dd></>}
      {task.open_blocker_count > 0 && <><dt className="font-bold">Blockers</dt><dd className="text-rose-700">{task.open_blocker_count} open</dd></>}
    </dl>
  </div>;
}

function StatusCell({ row }) {
  if (row.isPhase) return <span className="text-[11px] font-bold text-slate-500">{row.count} tasks · {row.progress}%</span>;
  return <span className={`text-[11px] font-black ${TONES[row.tone]?.text || ""}`}>{row.label}{row.late > 0 ? ` · ${row.late}d late` : ""}</span>;
}

const COLUMNS = [
  { id: "text", header: "Task", flexgrow: 1 },
  { id: "status", header: "Status", width: 140, cell: StatusCell },
  { id: "start", header: "Start", width: 72, align: "center", template: value => (value instanceof Date ? formatDay(isoOf(value)) : "") },
];

export function ProjectGantt({ tasks, project, zoom = "week", todaySignal = 0, onOpenTask }) {
  const [api, setApi] = useState(null);
  const today = todayLocal();
  const { rows, links } = useMemo(() => toGanttData(tasks, today), [tasks]); // eslint-disable-line react-hooks/exhaustive-deps
  const tooltip = useMemo(() => makeTooltip(new Map(rows.map(row => [row.id, row]))), [rows]);
  const undated = useMemo(() => tasks.filter(task => !plannedRange(task)), [tasks]);
  const handover = localDay(project?.target_handover_date);
  const range = useMemo(() => chartRange([today, localDay(project?.start_date), handover, ...rows.flatMap(r => [r.start, r.end])], zoom), [rows, zoom, project]); // eslint-disable-line react-hooks/exhaustive-deps
  const todayKey = today.getTime();
  // Day zoom: shade today's column as well as weekends.
  const highlight = (date, unit) => (unit === "day" && date.getTime() === todayKey ? "siteops-today" : highlightWeekends(date, unit));
  const config = ZOOMS[zoom] || ZOOMS.week;

  // Open on today, and the Today button scrolls back to it.
  useEffect(() => { api?.exec?.("scroll-chart", { date: plusDays(today, -7) }); }, [api, todaySignal]); // eslint-disable-line react-hooks/exhaustive-deps

  function init(ganttApi) {
    setApi(ganttApi);
    // Read-only: a click opens the task instead of editing it.
    ganttApi.on("select-task", ev => { if (ev.id && !String(ev.id).startsWith("phase:")) onOpenTask(ev.id); });
  }

  return <div className="grid gap-3">
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-bold text-slate-500">
      <span className="flex items-center gap-1.5"><span className="h-3 w-1 rounded-full bg-rose-500"/>Today · {formatDay(isoOf(today))}</span>
      {project?.start_date && <span>Project start · <span className="text-slate-800">{formatDay(project.start_date)}</span></span>}
      {project?.target_handover_date && <span>Handover · <span className="text-slate-800">{formatDay(project.target_handover_date)}</span></span>}
    </div>
    {rows.length > 0 && <div className="siteops-gantt overflow-hidden rounded-2xl border border-slate-200 bg-white" style={{ height: Math.min(Math.max(rows.length * 48 + 90, 320), 720) }} data-testid="svar-gantt">
      <Willow>
        <Tooltip api={api} content={tooltip}>
          <Gantt key={zoom} init={init} readonly tasks={rows} links={links} columns={COLUMNS} scales={scalesWithToday(zoom, today)} lengthUnit={config.lengthUnit}
            cellWidth={config.cellWidth} cellHeight={48} scaleHeight={30} start={range.start} end={range.end} gridWidth={480}
            highlightTime={highlight} taskTemplate={TaskBar}/>
        </Tooltip>
      </Willow>
    </div>}
    {undated.length > 0 && <UnscheduledTasks tasks={undated} onOpenTask={onOpenTask}/>}
  </div>;
}

// Tasks with no planned dates can't go on the timeline; they sit in a
// checklist under it, collapsed by default.
function UnscheduledTasks({ tasks, onOpenTask }) {
  const [open, setOpen] = useState(false);
  const today = todayLocal();
  const states = tasks.map(task => taskState(task, today));
  const count = label => states.filter(state => state.label === label).length;
  return <section className="rounded-2xl border border-slate-200 bg-white">
    <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} className="flex w-full flex-wrap items-center justify-between gap-2 p-4 text-left">
      <span><span className="block text-sm font-black text-slate-900">Pre-activation checklist</span><span className="text-xs font-semibold text-slate-500">{tasks.length} task{tasks.length === 1 ? "" : "s"} with no planned dates</span></span>
      <span className="flex items-center gap-1.5 text-[11px] font-black"><span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">{count("Ready to start")} ready</span><span className="rounded-full bg-rose-50 px-2 py-0.5 text-rose-700">{count("Blocked")} blocked</span><span className="rounded-full bg-blue-50 px-2 py-0.5 text-blue-700">{count("In progress")} in progress</span><ChevronDown size={15} className={`text-slate-400 transition ${open ? "rotate-180" : ""}`}/></span>
    </button>
    {open && <div className="grid gap-1.5 border-t border-slate-100 p-4 pt-3">{tasks.map((task, i) => <button key={task.id} type="button" onClick={() => onOpenTask(task.id)} className="flex items-center gap-2 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-left text-sm hover:border-blue-200">
      <span className="font-mono text-xs font-black text-blue-700">{task.original_code}</span><span className="truncate font-bold text-slate-900">{task.title}</span>
      <span className={`ml-auto shrink-0 text-xs font-bold ${TONES[states[i].tone].text}`}>{states[i].label}</span>
    </button>)}</div>}
  </section>;
}
