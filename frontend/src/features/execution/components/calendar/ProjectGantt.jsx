import "@svar-ui/react-gantt/all.css";
import { Gantt, Tooltip, Willow } from "@svar-ui/react-gantt";
import { ChevronDown, Lock } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { plannedRange } from "../executionViewHelpers";
import { formatDay, groupByPhase, taskState, TONES } from "./calendarModel";
import { daysFrom, phaseSchedule, projectSchedule, TARGET_STYLE, targetLabel, taskSchedule } from "./scheduleModel";
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
// Actual-track colour by status.
const ACTUAL = {
  done: "bg-emerald-600", active: "bg-blue-600", review: "bg-violet-600",
  blocked: "bg-rose-600", planned: "bg-slate-500", cancelled: "bg-slate-300",
};
const TAG_TONE = {
  late: "bg-rose-600 text-white", early: "bg-emerald-600 text-white", started: "bg-blue-600 text-white", moved: "bg-violet-100 text-violet-800",
};

const isoOf = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

/** API tasks -> SVAR rows and links. Each row spans everything it draws -
 *  plan, actual, original plan and target - so nothing is clipped; the bar
 *  template then places the tracks inside that span. */
export function toGanttData(tasks, today, { changes = [], targets = [], project = null } = {}) {
  const rows = [];
  const links = [];
  const changeByTask = new Map(changes.map(change => [change.task_id, change]));
  const targetByTask = new Map(targets.filter(t => t.kind === "task" && t.status === "active").map(t => [t.task_id, t]));
  const row = (schedule, extra) => ({ start: schedule.span.start, end: plusDays(schedule.span.end, 1), schedule, ...extra });

  const projectPlan = projectSchedule(project, today);
  if (projectPlan?.span) rows.push(row(projectPlan, { id: "project", type: "task", text: project.name || "Project", isProject: true, label: "Project", tone: projectPlan.actual && !projectPlan.actual.running ? "done" : projectPlan.actual ? "active" : "planned" }));

  const projectTargets = targets.filter(t => t.kind === "project" && t.status === "active");
  for (const target of projectTargets) {
    const day = localDay(target.target_date);
    rows.push({ id: `target:${target.id}`, type: "task", text: target.title, start: day, end: plusDays(day, 1), isTarget: true, target,
      schedule: { span: { start: day, end: day }, target: { date: day, state: target.outcome?.state || "open", days: target.outcome?.days || 0 }, tags: [] } });
  }

  for (const group of groupByPhase(tasks.filter(task => plannedRange(task)))) {
    const phaseId = `phase:${group.phase}`;
    const phase = phaseSchedule(group.tasks, today);
    rows.push({ id: phaseId, text: group.phase, type: "summary", open: true, progress: group.pct, isPhase: true, count: group.tasks.length, schedule: phase });
    for (const task of group.tasks) {
      const state = taskState(task, today);
      const schedule = taskSchedule(task, today, changeByTask.get(task.id), targetByTask.get(task.id));
      rows.push(row(schedule, {
        id: task.id, parent: phaseId, type: "task", text: `${task.original_code} · ${task.title}`,
        code: task.original_code, tone: state.tone, label: state.label, late: state.late, blocked: state.blocked, source: task,
        change: changeByTask.get(task.id) || null, targetRecord: targetByTask.get(task.id) || null,
      }));
      for (const predecessorId of task.predecessor_ids || []) links.push({ id: `${predecessorId}>${task.id}`, source: predecessorId, target: task.id, type: "e2s" });
    }
  }
  const ids = new Set(rows.map(item => item.id));
  return { rows, links: links.filter(link => ids.has(link.source) && ids.has(link.target)) };
}

// Position of a range inside the row, as percentages of the row's span.
function placer(start, end) {
  const total = Math.max(daysFrom(start, end), 1);
  return range => ({ left: `${(daysFrom(start, range.start) / total) * 100}%`, width: `${((daysFrom(range.start, range.end) + 1) / total) * 100}%` });
}

function Diamond({ target, place }) {
  const style = TARGET_STYLE[target.state] || TARGET_STYLE.open;
  const at = place({ start: target.date, end: target.date });
  return <span className="absolute top-[calc(50%+6px)] z-20 -translate-x-1/2 -translate-y-1/2" style={{ left: `calc(${at.left} + ${at.width} / 2)` }} title={style.label}>
    <span className="block size-3 rotate-45 rounded-[2px] ring-2 ring-white" style={{ background: style.color }}/>
  </span>;
}

// One row: the plan as a dashed track, what actually happened as a solid
// track on top (red where it ran past the plan), the original plan as a
// faint outline when the task was moved, and a diamond for the target.
function TaskBar({ data }) {
  const schedule = data.schedule;
  if (!schedule?.span || !data.start || !data.end) return null;
  const place = placer(data.start, data.end);
  const { plan, actual, original, target, shifts, tags } = schedule;
  const name = data.isTarget ? data.text : data.isProject ? `Project · ${data.text}` : data.isPhase ? null : (data.source?.title || data.code);
  const fill = ACTUAL[data.tone] || (data.isPhase ? "bg-slate-500" : ACTUAL.planned);
  const late = actual && plan && (shifts.runningLate || shifts.finishedLate) && actual.end > plan.end
    ? { start: plusDays(plan.end, 1), end: actual.end } : null;
  const onTime = actual && late ? { start: actual.start, end: plan.end < actual.start ? actual.start : plan.end } : actual;
  const thick = data.isProject || data.isPhase;

  return <div className="relative h-full w-full">
    {(name || tags.length > 0) && <span className="pointer-events-none absolute bottom-[calc(50%+4px)] left-0 flex items-center gap-1.5 whitespace-nowrap text-[11px] font-bold leading-4 text-slate-800">
      {data.isTarget && <span className="text-slate-500">◆</span>}{name}
      {tags.slice(0, 2).map(tag => <span key={tag.text} className={`rounded-full px-1.5 text-[10px] font-medium leading-4 ${TAG_TONE[tag.tone]}`}>{tag.text}</span>)}
    </span>}
    {original && <span className="absolute top-[calc(50%+6px)] h-3 -translate-y-1/2 rounded-full border border-dotted border-violet-300" style={place(original)} title="Original plan"/>}
    {plan && <span className={`absolute top-[calc(50%+6px)] -translate-y-1/2 rounded-full border border-dashed border-slate-400 ${thick ? "h-3.5" : "h-3"}`} style={place(plan)} title="Plan"/>}
    {onTime && <span className={`absolute top-[calc(50%+6px)] z-10 -translate-y-1/2 rounded-full ${fill} ${thick ? "h-2" : "h-1.5"} ${actual.running ? "opacity-80" : ""}`} style={place(onTime)} title="Actual"/>}
    {late && <span className={`absolute top-[calc(50%+6px)] z-10 -translate-y-1/2 rounded-full bg-rose-600 ${thick ? "h-2" : "h-1.5"}`} style={place(late)} title="Past the plan"/>}
    {data.blocked && <Lock size={10} className="absolute top-[calc(50%+6px)] z-20 -translate-x-1/2 -translate-y-1/2 text-rose-700" style={{ left: place(plan || actual).left }}/>}
    {target && <Diamond target={target} place={place}/>}
  </div>;
}

function makeTooltip(rowsById) {
  return function TooltipContent({ data }) { return <TaskTooltip row={rowsById.get(data?.task?.id)}/>; };
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function TaskTooltip({ row }) {
  if (!row) return null;
  if (row.isTarget) {
    const target = row.target;
    return <div className="w-72 rounded-xl border border-line bg-white p-3 text-xs shadow-lg">
      <p className="font-medium text-slate-900">◆ {target.title}</p>
      <p className={`mt-1 ${TARGET_STYLE[target.outcome?.state || "open"].text}`}>{targetLabel(target)}</p>
      {target.linked_tasks.length > 0 && <p className="mt-1 text-slate-600">{target.outcome?.done ?? 0} of {target.outcome?.total ?? target.linked_tasks.length} linked tasks done</p>}
      {target.note && <p className="mt-1 text-slate-600">{target.note}</p>}
      <p className="mt-1 text-slate-400">Set by {target.created_by_name}</p>
    </div>;
  }
  const schedule = row.schedule || {};
  const fmt = range => (range ? `${formatDay(isoOf(range.start))} - ${formatDay(isoOf(range.end))}` : "-");
  const actualText = schedule.actual ? `${formatDay(isoOf(schedule.actual.start))} - ${schedule.actual.running ? "ongoing" : formatDay(isoOf(schedule.actual.end))}` : "Not started";
  if (row.isPhase && !schedule.plan) return null;
  return <div className="w-80 rounded-xl border border-line bg-white p-3 text-xs shadow-lg">
    <p className="font-medium text-slate-900">{row.isProject ? `Project · ${row.text}` : row.isPhase ? `${row.text}, ${plural(row.count, "task")}, ${row.progress}% done` : `${row.source.original_code} · ${row.source.title}`}</p>
    {!row.isPhase && !row.isProject && <p className={`mt-1 ${TONES[row.tone]?.text || ""}`}>{row.label}</p>}
    {schedule.tags?.length > 0 && <p className="mt-1 flex flex-wrap gap-1">{schedule.tags.map(tag => <span key={tag.text} className={`rounded-full px-1.5 text-[10px] leading-4 ${TAG_TONE[tag.tone]}`}>{tag.text}</span>)}</p>}
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-slate-600">
      <dt>{row.isProject ? "Planned" : "Plan"}</dt><dd>{fmt(schedule.plan)}</dd>
      <dt>Actual</dt><dd>{actualText}</dd>
      {schedule.original && <><dt>Original plan</dt><dd>{fmt(schedule.original)}</dd></>}
      {row.change && <><dt>Moved</dt><dd>{plural(row.change.times_moved, "time")}{row.change.last_by ? ` · last by ${row.change.last_by}` : ""}{row.change.last_reason ? `: ${row.change.last_reason}` : ""}</dd></>}
      {row.targetRecord && <><dt>Target</dt><dd className={TARGET_STYLE[row.targetRecord.outcome?.state || "open"].text}>{targetLabel(row.targetRecord)}{row.targetRecord.note ? ` · ${row.targetRecord.note}` : ""}</dd></>}
      {row.source?.vendor_name && <><dt>Vendor</dt><dd>{row.source.vendor_name}</dd></>}
      {row.source?.open_blocker_count > 0 && <><dt>Blockers</dt><dd className="text-rose-700">{row.source.open_blocker_count} open</dd></>}
    </dl>
  </div>;
}

function StatusCell({ row }) {
  if (row.isPhase) return <span className="text-xs text-slate-500">{row.count} {row.count === 1 ? "task" : "tasks"}, {row.progress}%</span>;
  if (row.isTarget) return <span className={`text-[11px] ${TARGET_STYLE[row.target.outcome?.state || "open"].text}`}>{targetLabel(row.target).replace(/^Target /, "")}</span>;
  const first = row.schedule?.tags?.[0];
  if (row.isProject) return <span className="text-[11px] text-slate-600">{first ? first.text : row.schedule?.actual ? "Running" : "Not started"}</span>;
  return <span className={`text-[11px] font-medium ${TONES[row.tone]?.text || ""}`}>{row.label}{first ? ` · ${first.text}` : ""}</span>;
}

// The row itself spans everything it draws (actuals, a target before the
// plan...), so "Start" shows the planned start, not the row's left edge.
function StartCell({ row }) {
  const start = row.isTarget ? row.schedule?.target?.date : row.schedule?.plan?.start;
  return <span className="text-[13px] text-slate-700">{start ? formatDay(isoOf(start)) : ""}</span>;
}

const COLUMNS = [
  { id: "text", header: "Task", flexgrow: 1 },
  { id: "status", header: "Status", width: 200, cell: StatusCell },
  { id: "start", header: "Plan start", width: 100, align: "center", cell: StartCell },
];

export function ProjectGantt({ tasks, project, zoom = "day", todaySignal = 0, onOpenTask, changes = [], targets = [] }) {
  const [api, setApi] = useState(null);
  const today = todayLocal();
  const { rows, links } = useMemo(() => toGanttData(tasks, today, { changes, targets, project }), [tasks, changes, targets, project]); // eslint-disable-line react-hooks/exhaustive-deps
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
    ganttApi.on("select-task", ev => { const id = String(ev.id || ""); if (id && !/^(phase|target):|^project$/.test(id)) onOpenTask(ev.id); });
  }

  return <div className="grid gap-3">
    {rows.length > 0 && <div className="siteops-gantt overflow-hidden rounded-[20px] border border-line bg-white" style={{ height: Math.min(Math.max(rows.length * 48 + 70, 200), 720) }} data-testid="svar-gantt">
      <Willow>
        <Tooltip api={api} content={tooltip}>
          <Gantt key={zoom} init={init} readonly tasks={rows} links={links} columns={COLUMNS} scales={scalesWithToday(zoom, today)} lengthUnit={config.lengthUnit}
            cellWidth={config.cellWidth} cellHeight={48} scaleHeight={30} start={range.start} end={range.end} gridWidth={560}
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
  return <section className="rounded-[20px] border border-line bg-white">
    <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} className="flex w-full flex-wrap items-center justify-between gap-2 p-4 text-left">
      <span><span className="block text-[15px] text-slate-950">Pre-activation checklist</span><span className="text-xs text-slate-500">{tasks.length} task{tasks.length === 1 ? "" : "s"} with no planned dates</span></span>
      <span className="flex items-center gap-1.5 text-xs"><span className="rounded-md bg-emerald-50 px-2 py-0.5 text-emerald-800">{count("Ready to start")} ready</span><span className="rounded-md bg-rose-50 px-2 py-0.5 text-rose-800">{count("Blocked")} blocked</span><span className="rounded-full bg-blue-50 px-2 py-0.5 text-blue-700">{count("In progress")} in progress</span><ChevronDown size={15} className={`text-slate-400 transition ${open ? "rotate-180" : ""}`}/></span>
    </button>
    {open && <div className="grid gap-1.5 border-t border-slate-100 p-4 pt-3">{tasks.map((task, i) => <button key={task.id} type="button" onClick={() => onOpenTask(task.id)} className="flex items-center gap-2 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-left text-sm hover:border-blue-200">
      <span className="rounded-md bg-white px-1.5 py-0.5 text-xs tabular-nums text-slate-700 ring-1 ring-slate-200">{task.original_code}</span><span className="truncate text-slate-950">{task.title}</span>
      <span className={`ml-auto shrink-0 text-xs ${TONES[states[i].tone].text}`}>{states[i].label}</span>
    </button>)}</div>}
  </section>;
}
