import { ChevronDown, GitBranch, ShieldCheck } from "lucide-react";
import { Pill } from "../../../components/ui";
import { todayIso } from "../../../utils/format";

// U18: renders the readiness U12 computes and U15 puts on the task payload.
//
// Nothing here re-derives readiness. The engine resolves a whole project's
// dependencies and approvals in four queries and hands down a state plus the
// facts behind it; a second copy of those rules in the browser would drift
// from the guard the portal actually enforces, and a board that disagrees
// with the backend is worse than no board.
//
// Readiness is ADVISORY this release (R5/KTD1). It is a projection of
// already-persisted facts, never a statement about which transitions are
// permitted - which is why this panel is rendered apart from the lifecycle
// controls and never disables one. The two can legitimately disagree.

// Only `ready` and `blocked` are computed. Every other state is defined by
// the backend as a restatement of the task's own lifecycle_status (see
// `_STATE_BY_LIFECYCLE_STATUS`), which the row and the stepper already show -
// so those get a label here but earn no pill on the row.
export const COMPUTED_READINESS_STATES = ["ready", "blocked"];

const STATE_LABEL = {
  ready: "Ready to start",
  blocked: "Blocked",
  in_progress: "In progress",
  awaiting_verification: "Awaiting verification",
  awaiting_approval: "Awaiting approval",
  rejected: "Rejected",
  completed: "Completed",
  cancelled: "Cancelled",
};

const STATE_TONE = {
  ready: "green",
  blocked: "red",
  in_progress: "blue",
  awaiting_verification: "orange",
  awaiting_approval: "orange",
  rejected: "red",
  completed: "green",
  cancelled: "gray",
};

// Exported so any surface that wants to show "blocked by dependency /
// approval / both" at a glance (not just this panel's own reason list) uses
// the same icon per kind rather than inventing a second vocabulary.
export const REASON_ICON = { dependency: GitBranch, approval: ShieldCheck };

// The distinct kinds of BLOCKING reason on a task, in a stable order
// (dependency before approval) - `advisories` are deliberately excluded,
// since those were marked non-gating and showing them here would claim a
// task is held up by something a PM decided doesn't gate it. A task blocked
// by both a predecessor and an external approval returns both kinds, so a
// caller can render one icon per kind instead of one generic "blocked" mark.
export function blockingReasonKinds(task) {
  const kinds = new Set((task?.readiness?.reasons || []).map(reason => reason.kind));
  return ["dependency", "approval"].filter(kind => kinds.has(kind));
}

// U19: the readiness filters offered above the board. `all` is not a
// readiness state - it is the absence of a filter - so it is handled
// explicitly rather than compared against `readiness.state`.
export const READINESS_FILTERS = [["all", "All"], ["ready", "Ready"], ["blocked", "Blocked"]];

// U19: shared by the board (which rows to draw) and the page (what the count
// tiles say). Defined ONCE and used by both on the same task array, because
// the whole point of R26 is that the number above the board and the number of
// rows in it must be the same number - two copies of this predicate is
// exactly how they drifted apart before.
export function matchesReadinessFilter(task, filter) {
  if (!filter || filter === "all") return true;
  return task.readiness?.state === filter;
}

// U19 (R20): work that could be pulled forward - ready to start, but not due
// to start yet. An undated task is never here: with no planned start there is
// nothing to be ahead of. `todayIso()` is UTC, matching the clock the backend
// compares planned dates against.
// `today` is taken as a named option rather than a second positional
// argument on purpose: passing this straight to `Array.filter` would
// otherwise put the element INDEX in it and silently compare a date string
// against a number, which is false for every task and looks like an empty
// list rather than a bug.
export function isReadyToAccelerate(task, { today = todayIso() } = {}) {
  if (task.readiness?.state !== "ready") return false;
  if (!task.planned_start_date) return false;
  return task.planned_start_date > today;
}

export function readinessCounts(tasks) {
  const counts = { total: tasks.length, ready: 0, blocked: 0, accelerate: 0 };
  for (const task of tasks) {
    if (matchesReadinessFilter(task, "ready")) counts.ready += 1;
    if (matchesReadinessFilter(task, "blocked")) counts.blocked += 1;
    if (isReadyToAccelerate(task)) counts.accelerate += 1;
  }
  return counts;
}

export function readinessLabel(state) {
  return STATE_LABEL[state] || state;
}

export function readinessTone(state) {
  return STATE_TONE[state] || "gray";
}

// `detail` is rendered verbatim - it is the sentence the engine already
// wrote, naming the specific predecessor or approval. Recomposing it here
// from `kind` and `subject_id` would put a second vocabulary in front of the
// user and let the board and the engine describe the same fact differently.
function ReasonRow({ reason }) {
  const Icon = REASON_ICON[reason.kind] || GitBranch;
  return <li className="flex items-start gap-2 text-sm text-slate-700">
    <Icon size={14} className="mt-0.5 shrink-0 text-slate-400"/>
    <span>{reason.detail}</span>
  </li>;
}

export function TaskReadinessPanel({ task }) {
  const readiness = task?.readiness;
  if (!readiness) return null;

  const reasons = readiness.reasons || [];
  const advisories = readiness.advisories || [];

  return <section className="rounded-xl border border-slate-200 bg-white px-4 py-3" aria-label="Task readiness">
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-medium text-slate-500">Readiness</span>
      <Pill tone={readinessTone(readiness.state)}>{readinessLabel(readiness.state)}</Pill>
    </div>

    {reasons.length > 0 && <>
      <p className="mt-2 text-xs font-bold text-slate-500">{reasons.length === 1 ? "One thing is holding this task:" : `${reasons.length} things are holding this task:`}</p>
      <ul className="mt-1.5 grid gap-1.5">{reasons.map(reason => <ReasonRow key={`${reason.kind}-${reason.subject_id}`} reason={reason}/>)}</ul>
    </>}

    {/* Unsatisfied but explicitly non-blocking: a PM marked this dependency
        or approval as not gating, and reporting it as a blocker would
        override that decision. Shown so the picture is complete, kept
        visually distinct so it is not mistaken for one. */}
    {advisories.length > 0 && <details className="group mt-2">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-bold text-blue-700">
        {advisories.length} advisory {advisories.length === 1 ? "note" : "notes"} <ChevronDown size={13} className="transition group-open:rotate-180"/>
      </summary>
      <ul className="mt-1.5 grid gap-1.5">{advisories.map(reason => <ReasonRow key={`${reason.kind}-${reason.subject_id}`} reason={reason}/>)}</ul>
      <p className="mt-1.5 max-w-prose text-xs leading-5 text-slate-500">These are unsatisfied but were marked non-blocking, so they do not stop this task starting.</p>
    </details>}

    {readiness.state === "blocked" && reasons.length === 0 && <p className="mt-2 text-xs font-bold text-slate-500">This task is blocked by its lifecycle state rather than by a dependency or approval.</p>}

    <p className="mt-2 text-xs leading-5 text-slate-400">Readiness is advisory - it reflects dependencies and approvals, and does not by itself permit or refuse a status change.</p>
  </section>;
}
