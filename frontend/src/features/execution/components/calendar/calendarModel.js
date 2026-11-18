import { actualRange, daysBetween, needsReview, plannedRange, toDay } from "../executionViewHelpers";

// Pure helpers for the three calendar views (Gantt, month, portfolio).
// Everything works in UTC calendar days, like executionViewHelpers.

const DAY_MS = 86400000;
export const addDays = (day, count) => new Date(day.getTime() + count * DAY_MS);
export const isoDay = day => day.toISOString().slice(0, 10);

export const MONTH = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });
export const MONTH_YEAR = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
export const DAY_MONTH = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
export const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });
export const formatDay = value => { const day = toDay(value); return day ? DAY_MONTH.format(day) : "-"; };

// Pixels per day for each zoom. Day labels every day; week labels Mondays;
// month and quarter label months.
export const GANTT_ZOOMS = { day: 44, week: 22, month: 8, quarter: 3 };
export const PORTFOLIO_ZOOMS = { month: 14, quarter: 5, year: 1.6 };

/** One task's look on the calendar: colour, words, days late, and its bars. */
export function taskState(task, today) {
  const late = task.variance?.status === "late" ? Math.max(0, task.variance.variance_days || 0) : 0;
  const blocked = task.readiness?.state === "blocked" && !["completed", "cancelled"].includes(task.lifecycle_status);
  let tone = "planned";
  let label = "Planned";
  if (task.lifecycle_status === "completed") { tone = "done"; label = "Completed"; }
  else if (task.lifecycle_status === "cancelled") { tone = "cancelled"; label = "Cancelled"; }
  else if (blocked) { tone = "blocked"; label = "Blocked"; }
  else if (needsReview(task)) { tone = "review"; label = "Needs review"; }
  else if (task.lifecycle_status === "in_progress") { tone = "active"; label = "In progress"; }
  else if (task.readiness?.state === "ready") { tone = "planned"; label = "Ready to start"; }
  return { tone, label, late, blocked, planned: plannedRange(task), actual: actualRange(task, today) };
}

// Tailwind classes per tone: bar outline, bar fill, text.
export const TONES = {
  done: { outline: "border-emerald-600 bg-emerald-100", fill: "bg-emerald-600", text: "text-emerald-700", dot: "bg-emerald-600" },
  active: { outline: "border-blue-500 bg-blue-50", fill: "bg-blue-500", text: "text-blue-700", dot: "bg-blue-500" },
  review: { outline: "border-violet-500 bg-violet-50", fill: "bg-violet-500", text: "text-violet-700", dot: "bg-violet-500" },
  blocked: { outline: "border-rose-500 bg-rose-100", fill: "bg-rose-500", text: "text-rose-700", dot: "bg-rose-500" },
  planned: { outline: "border-dashed border-slate-400 bg-white", fill: "bg-slate-400", text: "text-slate-600", dot: "bg-slate-400" },
  cancelled: { outline: "border-slate-300 bg-slate-100", fill: "bg-slate-300", text: "text-slate-400", dot: "bg-slate-300" },
};

export const HEALTH = {
  on_track: { label: "On track", bar: "bg-emerald-100", fill: "bg-emerald-600", pill: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  at_risk: { label: "At risk", bar: "bg-amber-100", fill: "bg-amber-500", pill: "bg-amber-50 text-amber-800 border-amber-200" },
  delayed: { label: "Delayed", bar: "bg-rose-100", fill: "bg-rose-500", pill: "bg-rose-50 text-rose-800 border-rose-200" },
  completed: { label: "Completed", bar: "bg-emerald-600", fill: "bg-emerald-600", pill: "bg-slate-50 text-slate-700 border-slate-200" },
};

/** The date span a Gantt draws: every planned and actual date, today, and
 *  the project's own start and handover, with a little padding. */
export function ganttSpan(tasks, today, project) {
  const bounds = [Number(today)];
  for (const task of tasks) {
    const planned = plannedRange(task);
    const actual = actualRange(task, today);
    if (planned) bounds.push(Number(planned.start), Number(planned.end));
    if (actual) bounds.push(Number(actual.start), Number(actual.end));
  }
  const start = toDay(project?.start_date);
  const handover = toDay(project?.target_handover_date);
  if (start) bounds.push(Number(start));
  if (handover) bounds.push(Number(handover));
  const first = addDays(new Date(Math.min(...bounds)), -3);
  const last = addDays(new Date(Math.max(...bounds)), 7);
  return { start: first, end: last, days: daysBetween(first, last) + 1 };
}

/** Header labels for a span at a zoom: [{ offset, label, major }]. */
export function ticks(span, zoom) {
  const out = [];
  for (let i = 0; i < span.days; i += 1) {
    const day = addDays(span.start, i);
    const first = day.getUTCDate() === 1;
    if (zoom === "day") out.push({ offset: i, label: `${WEEKDAY.format(day)} ${day.getUTCDate()}`, major: first || i === 0, month: first || i === 0 ? MONTH.format(day) : null });
    else if (zoom === "week") { if (day.getUTCDay() === 1 || i === 0) out.push({ offset: i, label: DAY_MONTH.format(day), major: first }); }
    // The span's first day gets a label only when it isn't right before the
    // next label (late in a month), so two labels never overlap.
    else if (zoom === "month" || zoom === "quarter") { if (first || (i === 0 && day.getUTCDate() <= 20)) out.push({ offset: i, label: MONTH_YEAR.format(day), major: true }); }
    else if (zoom === "year") { if ((first && day.getUTCMonth() % 3 === 0) || (i === 0 && day.getUTCDate() <= 20 && day.getUTCMonth() % 3 !== 2)) out.push({ offset: i, label: MONTH_YEAR.format(day), major: true }); }
  }
  return out;
}

/** Left offset and width (px) of a range on the span. */
export function place(span, range, pxPerDay) {
  const left = daysBetween(span.start, range.start) * pxPerDay;
  const width = Math.max(daysBetween(range.start, range.end) + 1, 1) * pxPerDay;
  return { left, width };
}

/** Rows for the Gantt: phases (collapsible) with their tasks, in order. */
export function groupByPhase(tasks) {
  const groups = new Map();
  for (const task of tasks) {
    const phase = task.phase || "No phase";
    if (!groups.has(phase)) groups.set(phase, []);
    groups.get(phase).push(task);
  }
  return [...groups.entries()].map(([phase, items]) => {
    const ranges = items.map(plannedRange).filter(Boolean);
    const done = items.filter(task => task.lifecycle_status === "completed").length;
    const counted = items.filter(task => task.lifecycle_status !== "cancelled").length;
    return {
      phase, tasks: items,
      range: ranges.length ? { start: new Date(Math.min(...ranges.map(r => Number(r.start)))), end: new Date(Math.max(...ranges.map(r => Number(r.end)))) } : null,
      pct: counted ? Math.round((100 * done) / counted) : 0,
    };
  });
}

/** What a month-calendar day shows: tasks starting, due, finished, and
 *  (on today only) everything open and late. */
export function dayEvents(tasks, day, today, milestones = []) {
  const iso = isoDay(day);
  const events = [];
  for (const task of tasks) {
    if (task.lifecycle_status === "cancelled") continue;
    const state = taskState(task, today);
    const finished = task.actual_finish_at && String(task.actual_finish_at).slice(0, 10) === iso;
    if (finished) events.push({ kind: "done", task, label: `${task.title} done` });
    else if (task.planned_start_date === iso && task.lifecycle_status !== "completed") events.push({ kind: state.blocked ? "blocked" : "start", task, label: `${task.title} starts` });
    else if (task.planned_end_date === iso && task.lifecycle_status !== "completed") events.push({ kind: "due", task, label: `${task.title} due` });
    if (iso === isoDay(today) && state.late > 0 && task.lifecycle_status !== "completed" && task.planned_end_date !== iso) {
      events.push({ kind: "late", task, label: `${task.title} · ${state.late}d late` });
    }
  }
  for (const milestone of milestones) if (milestone.date === iso) events.push({ kind: "milestone", label: milestone.label });
  const order = { late: 0, blocked: 1, due: 2, start: 3, done: 4, milestone: 5 };
  return events.sort((a, b) => order[a.kind] - order[b.kind]);
}

export const EVENT_STYLE = {
  late: "bg-rose-50 text-rose-800 border-rose-200",
  blocked: "bg-rose-50 text-rose-800 border-rose-200",
  due: "bg-amber-50 text-amber-800 border-amber-200",
  start: "bg-blue-50 text-blue-800 border-blue-200",
  done: "bg-emerald-50 text-emerald-800 border-emerald-200",
  milestone: "bg-slate-100 text-slate-700 border-slate-200",
};

/** The 6-week grid (Monday first) that contains `month` (a UTC day). */
export function monthGrid(month) {
  const first = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1));
  const offset = (first.getUTCDay() + 6) % 7;
  const start = addDays(first, -offset);
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}
