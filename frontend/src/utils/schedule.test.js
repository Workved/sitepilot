import { describe, expect, it } from "vitest";
import { planGap, scheduleWindow } from "./schedule";

const project = { start_date: "2026-11-01", target_handover_date: "2026-12-01", status: "active" };

describe("scheduleWindow", () => {
  it("reports the day number, total days and time used", () => {
    const window = scheduleWindow(project, new Date("2026-11-16T00:00:00"));
    expect(window).toMatchObject({ day: 16, total: 30, planned: 50, notStarted: false, daysLeft: 15 });
  });

  it("counts down to a start date that has not arrived", () => {
    expect(scheduleWindow(project, new Date("2026-10-29T00:00:00"))).toMatchObject({ notStarted: true, daysToStart: 3, planned: 0 });
  });

  it("has nothing to say without both dates", () => {
    expect(scheduleWindow({ start_date: "2026-11-01" })).toBeNull();
  });
});

describe("planGap", () => {
  const midway = new Date("2026-11-16T00:00:00");
  it("calls a project behind only past the tolerance", () => {
    expect(planGap(project, 20, midway)).toMatchObject({ planned: 50, gap: 30, behind: true });
    expect(planGap(project, 47, midway).behind).toBe(false);
  });

  it("never compares a completed project against its calendar", () => {
    expect(planGap({ ...project, status: "completed" }, 100, midway)).toBeNull();
  });
});
