/*
 * Plan vs actual for one bar on the calendar - a task, a phase or the whole
 * project. Pure, so it can be tested on its own.
 *
 * Every date is a local-midnight Date (see svarSetup.localDay). A range's
 * `end` is the LAST day it covers (inclusive).
 */
import { localDay } from "./svarSetup";

const DAY_MS = 86400000;
export const daysFrom = (a, b) => Math.round((b - a) / DAY_MS);

function range(start, end) {
  const from = localDay(start);
  if (!from) return null;
  const to = localDay(end) || from;
  return { start: from, end: to < from ? from : to };
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/**
 * plan:   { start, end } as currently planned
 * actual: { start, end, running } or null - running ones end today
 * original: the plan before any reschedule (only when it differs)
 * target: { date, state, days } for the active task target
 * shifts: started/finished early or late, moved, in days
 * span:   union of everything drawn, so the row is wide enough for it all
 * tags:   short labels for the bar, most important first
 */
export function scheduleOf({ planStart, planEnd, actualStart, actualEnd, done = false, cancelled = false, original = null, target = null, today }) {
  const plan = range(planStart, planEnd);
  let actual = null;
  if (actualStart && !cancelled) {
    const start = localDay(actualStart);
    const finished = localDay(actualEnd);
    if (finished) actual = { start, end: finished < start ? start : finished, running: false };
    else if (done) actual = { start, end: start, running: false };
    else actual = { start, end: today < start ? start : today, running: true };
  }

  const shifts = { startedEarly: 0, startedLate: 0, finishedEarly: 0, finishedLate: 0, runningLate: 0, moved: 0 };
  if (plan && actual) {
    const startDiff = daysFrom(plan.start, actual.start);
    if (startDiff < 0) shifts.startedEarly = -startDiff;
    if (startDiff > 0) shifts.startedLate = startDiff;
    if (!actual.running) {
      const endDiff = daysFrom(plan.end, actual.end);
      if (endDiff < 0) shifts.finishedEarly = -endDiff;
      if (endDiff > 0) shifts.finishedLate = endDiff;
    }
  }
  if (plan && !cancelled && (!actual || actual.running) && today > plan.end && !done) shifts.runningLate = daysFrom(plan.end, today);

  let originalRange = null;
  if (original && plan) {
    const before = range(original.start, original.end);
    if (before && (daysFrom(before.start, plan.start) !== 0 || daysFrom(before.end, plan.end) !== 0)) {
      originalRange = before;
      shifts.moved = daysFrom(before.end, plan.end) || daysFrom(before.start, plan.start);
    }
  }

  const targetDay = target ? localDay(target.target_date || target.date) : null;
  const points = [plan?.start, plan?.end, actual?.start, actual?.end, originalRange?.start, originalRange?.end, targetDay].filter(Boolean);
  const span = points.length ? { start: new Date(Math.min(...points)), end: new Date(Math.max(...points)) } : null;

  const tags = [];
  if (shifts.finishedLate) tags.push({ text: `Done ${plural(shifts.finishedLate, "day")} late`, tone: "late" });
  if (shifts.runningLate) tags.push({ text: `+${shifts.runningLate}d late`, tone: "late" });
  if (shifts.finishedEarly) tags.push({ text: `Done ${plural(shifts.finishedEarly, "day")} early`, tone: "early" });
  else if (done && actual && !shifts.finishedLate) tags.push({ text: "Done on time", tone: "early" });
  if (shifts.startedEarly) tags.push({ text: `Started ${plural(shifts.startedEarly, "day")} early`, tone: "started" });
  if (shifts.startedLate && !shifts.runningLate && !shifts.finishedLate) tags.push({ text: `Started ${plural(shifts.startedLate, "day")} late`, tone: "late" });
  if (shifts.moved) tags.push({ text: `Moved ${shifts.moved > 0 ? "+" : "−"}${Math.abs(shifts.moved)}d`, tone: "moved" });

  return {
    plan, actual, original: originalRange, shifts, span, tags,
    target: targetDay ? { date: targetDay, state: target.outcome?.state || target.state || "open", days: target.outcome?.days ?? target.days ?? 0 } : null,
  };
}

/** A task's schedule, given the reschedule history and its active target. */
export function taskSchedule(task, today, change = null, target = null) {
  return scheduleOf({
    planStart: task.planned_start_date, planEnd: task.planned_end_date,
    actualStart: task.actual_start_at, actualEnd: task.actual_finish_at,
    done: task.lifecycle_status === "completed", cancelled: task.lifecycle_status === "cancelled",
    original: change ? { start: change.original_start, end: change.original_end } : null,
    target, today,
  });
}

/** The project's own plan vs actual: planned start/handover vs activation/completion. */
export function projectSchedule(project, today) {
  if (!project) return null;
  return scheduleOf({
    planStart: project.start_date, planEnd: project.target_handover_date,
    actualStart: project.activated_at, actualEnd: project.completed_at,
    done: ["completed", "archived"].includes(project.status) && Boolean(project.completed_at), today,
  });
}

/** A phase: plan = its tasks' planned span; actual = first start to last finish (or today). */
export function phaseSchedule(tasks, today) {
  const dated = tasks.filter(task => task.planned_start_date && task.lifecycle_status !== "cancelled");
  if (!dated.length) return null;
  const min = values => values.reduce((a, b) => (a < b ? a : b));
  const max = values => values.reduce((a, b) => (a > b ? a : b));
  const started = dated.filter(task => task.actual_start_at);
  const allDone = dated.every(task => task.lifecycle_status === "completed");
  return scheduleOf({
    planStart: min(dated.map(task => task.planned_start_date)), planEnd: max(dated.map(task => task.planned_end_date || task.planned_start_date)),
    actualStart: started.length ? min(started.map(task => String(task.actual_start_at).slice(0, 10))) : null,
    actualEnd: allDone ? max(dated.map(task => String(task.actual_finish_at || task.actual_start_at || task.planned_end_date).slice(0, 10))) : null,
    done: allDone, today,
  });
}

export const TARGET_STYLE = {
  met: { label: "Target met", color: "#059669", text: "text-emerald-700", chip: "bg-emerald-50 text-emerald-800" },
  open: { label: "Target", color: "#2563eb", text: "text-blue-700", chip: "bg-blue-50 text-blue-800" },
  due_soon: { label: "Target due soon", color: "#ea580c", text: "text-orange-700", chip: "bg-orange-50 text-orange-800" },
  missed: { label: "Target missed", color: "#e11d48", text: "text-rose-700", chip: "bg-rose-50 text-rose-800" },
  cancelled: { label: "Target (task cancelled)", color: "#94a3b8", text: "text-slate-500", chip: "bg-slate-100 text-slate-600" },
};

export function targetLabel(target) {
  const state = target.outcome?.state || "open";
  const date = localDay(target.target_date)?.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const days = target.outcome?.days ?? 0;
  if (state === "met") return `Target ${date} met`;
  if (state === "missed") return target.outcome?.finished_on ? `Target ${date} missed by ${plural(days, "day")}` : `Target ${date} missed (${plural(days, "day")} ago)`;
  if (state === "due_soon") return days === 0 ? `Target today` : `Target ${date} · ${plural(days, "day")} left`;
  return `Target ${date}`;
}
