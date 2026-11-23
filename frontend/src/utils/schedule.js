// Planned-vs-actual helpers shared by the Overview dashboard and the
// Projects workspace, so both screens call a project "behind" the same way.

const DAY = 86400000;
const atMidnight = value => new Date(`${value}T00:00:00`);
const daysBetween = (a, b) => Math.round((b - a) / DAY);

// A project counts as behind plan when completed work trails elapsed time
// by more than this many points - small gaps are normal week-to-week noise.
export const BEHIND_TOLERANCE = 5;

// Share of the planned window (start -> target handover) that has elapsed.
export function plannedPercent(project, today = new Date()) {
  if (!project?.start_date || !project?.target_handover_date) return null;
  const start = atMidnight(project.start_date);
  const end = atMidnight(project.target_handover_date);
  const span = daysBetween(start, end);
  if (span <= 0) return 100;
  return Math.max(0, Math.min(100, Math.round(daysBetween(start, today) / span * 100)));
}

// Where a project sits in its planned window, in days. Null without dates.
export function scheduleWindow(project, today = new Date()) {
  if (!project?.start_date || !project?.target_handover_date) return null;
  const start = atMidnight(project.start_date);
  const end = atMidnight(project.target_handover_date);
  const total = Math.max(daysBetween(start, end), 1);
  const elapsed = daysBetween(start, today);
  return {
    total,
    day: Math.min(Math.max(elapsed + 1, 0), total),
    notStarted: elapsed < 0,
    daysToStart: Math.max(-elapsed, 0),
    daysLeft: daysBetween(today, end),
    planned: plannedPercent(project, today),
  };
}

// "Behind by N points", "On plan", or nothing when there is no plan to compare.
export function planGap(project, progressPct, today = new Date()) {
  const planned = plannedPercent(project, today);
  if (planned == null || typeof progressPct !== "number" || project?.status === "completed") return null;
  const gap = planned - progressPct;
  return { planned, gap, behind: gap > BEHIND_TOLERANCE };
}
