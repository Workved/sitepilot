import { describe, expect, it } from "vitest";
import { phaseSchedule, projectSchedule, targetLabel, taskSchedule } from "./components/calendar/scheduleModel";
import { localDay } from "./components/calendar/svarSetup";

const today = localDay("2026-11-26");
const task = overrides => ({ planned_start_date: "2026-11-20", planned_end_date: "2026-11-25", lifecycle_status: "planned", ...overrides });

describe("schedule model", () => {
  it("shows a task that started early and finished early", () => {
    const s = taskSchedule(task({ actual_start_at: "2026-11-18T09:00:00Z", actual_finish_at: "2026-11-22T17:00:00Z", lifecycle_status: "completed" }), today);
    expect(s.shifts).toMatchObject({ startedEarly: 2, finishedEarly: 3 });
    expect(s.tags.map(tag => tag.text)).toEqual(["Done 3 days early", "Started 2 days early"]);
    expect(s.span.start).toEqual(localDay("2026-11-18"));
  });

  it("runs a late task's actual track to today and says how late", () => {
    const s = taskSchedule(task({ actual_start_at: "2026-11-21T09:00:00Z", lifecycle_status: "in_progress" }), today);
    expect(s.actual).toMatchObject({ running: true, end: today });
    expect(s.tags[0]).toEqual({ text: "+1d late", tone: "late" });
  });

  it("marks a rescheduled task as moved and keeps the original plan", () => {
    const s = taskSchedule(task(), today, { original_start: "2026-11-14", original_end: "2026-11-19" });
    expect(s.shifts.moved).toBe(6);
    expect(s.original.start).toEqual(localDay("2026-11-14"));
    expect(s.tags.map(tag => tag.text)).toContain("Moved +6d");
  });

  it("places the target inside the row and carries its state", () => {
    const s = taskSchedule(task(), today, null, { target_date: "2026-11-28", outcome: { state: "due_soon", days: 2 } });
    expect(s.target).toMatchObject({ state: "due_soon", days: 2 });
    expect(s.span.end).toEqual(localDay("2026-11-28"));
    expect(targetLabel({ target_date: "2026-11-28", outcome: { state: "due_soon", days: 2 } })).toBe("Target 28 Nov · 2 days left");
  });

  it("compares the project's start and handover with what actually happened", () => {
    const s = projectSchedule({ start_date: "2026-11-25", target_handover_date: "2027-01-09", activated_at: "2026-11-23T10:00:00Z", completed_at: "2026-12-30T10:00:00Z", status: "completed" }, today);
    expect(s.tags.map(tag => tag.text)).toEqual(["Done 10 days early", "Started 2 days early"]);
  });

  it("rolls tasks up into a phase", () => {
    const s = phaseSchedule([
      task({ actual_start_at: "2026-11-19T00:00:00Z", actual_finish_at: "2026-11-23T00:00:00Z", lifecycle_status: "completed" }),
      task({ planned_start_date: "2026-11-22", planned_end_date: "2026-11-27", actual_start_at: "2026-11-22T00:00:00Z", actual_finish_at: "2026-11-24T00:00:00Z", lifecycle_status: "completed" }),
    ], today);
    expect(s.shifts).toMatchObject({ startedEarly: 1, finishedEarly: 3 });
  });
});
