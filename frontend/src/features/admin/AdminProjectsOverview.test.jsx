import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminVisibilityApi } from "../../api/adminVisibilityApi";
import { projectsApi } from "../../api/projectsApi";
import { AdminProjectsOverview, eventKind, portfolioStanding, sortPortfolio, weekDigest } from "./AdminProjectsOverview";

vi.mock("../../api/adminVisibilityApi", () => ({ adminVisibilityApi: { projectsOverview: vi.fn(), activity: vi.fn() } }));
vi.mock("../../api/projectsApi", () => ({ projectsApi: { timeline: vi.fn() } }));

function project(overrides) {
  return {
    id: overrides.id, code: `PRJ-${overrides.id}`, name: overrides.name, status: "active", health: "on_track",
    site: "New Delhi", pm_name: "Ved", progress_percent: 50, total_count: 4, planned_count: 1, active_count: 1,
    completed_count: 2, blocked_count: 0, delayed_count: 0, overdue_count: 0, no_update_count: 0, ...overrides,
  };
}

const PROJECTS = [
  project({ id: "a", name: "Head Office", progress_percent: 67 }),
  project({ id: "b", name: "Trip Jack", progress_percent: 0 }),
  project({ id: "c", name: "Exterior", status: "draft", health: "on_track", progress_percent: 0 }),
  project({ id: "d", name: "Lobby", overdue_count: 3, health: "delayed" }),
];
// Trip Jack is well into its window with nothing done: behind plan.
const TIMELINE = [
  { project_id: "a", health: "on_track", start_date: "2026-01-01", target_handover_date: "2099-01-01", days_late: 0 },
  { project_id: "b", health: "on_track", start_date: "2020-01-01", target_handover_date: "2026-01-01", days_late: 0 },
  { project_id: "d", health: "delayed", start_date: "2026-01-01", target_handover_date: "2026-06-01", days_late: 9 },
];
const ACTIVITY = [
  { id: "e1", project_id: "b", action: "TASK_STATUS_CHANGED", actor_name: "Ved", reason: "Standard work completed", occurred_at: new Date().toISOString() },
  { id: "e2", project_id: null, action: "TEMPLATE_DRAFT_DELETED", actor_name: "Admin", reason: "Remove", occurred_at: new Date().toISOString() },
];

beforeEach(() => {
  vi.clearAllMocks();
  adminVisibilityApi.projectsOverview.mockResolvedValue(PROJECTS);
  adminVisibilityApi.activity.mockResolvedValue(ACTIVITY);
  projectsApi.timeline.mockResolvedValue(TIMELINE);
});

const table = () => within(screen.getByRole("region", { name: "Projects" }));

describe("Portfolio", () => {
  it("lists every project in one table, worst health first", async () => {
    render(<AdminProjectsOverview onOpenProject={vi.fn()} />);
    await screen.findByRole("tab", { name: /All/ });
    const names = table().getAllByRole("button", { name: /^Open / }).map(button => button.getAttribute("aria-label"));
    // Delayed, then at risk (behind plan), then on track, then draft.
    expect(names.slice(0, 4)).toEqual(["Open Lobby", "Open Trip Jack", "Open Head Office", "Open Exterior"]);
  });

  it("filters by health with one row of chips", async () => {
    render(<AdminProjectsOverview onOpenProject={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: /At risk 1/ }));
    expect(table().getAllByRole("button", { name: /^Open / }).map(button => button.getAttribute("aria-label"))).toEqual(["Open Trip Jack", "Open Trip Jack"]);
    expect(table().getByText("1 of 1", { exact: false })).toBeInTheDocument();
  });

  it("opens a project from its row", async () => {
    const onOpenProject = vi.fn();
    render(<AdminProjectsOverview onOpenProject={onOpenProject} />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Open Head Office" }))[0]);
    expect(onOpenProject).toHaveBeenCalledWith("PRJ-a");
  });

  it("opens activity in a panel: project events by default, everything on request", async () => {
    render(<AdminProjectsOverview onOpenProject={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Activity/ }));
    const panel = within(screen.getByRole("dialog", { name: "Activity" }));
    expect(panel.getByText("Task status changed")).toBeInTheDocument();
    expect(panel.queryByText("Template draft deleted")).toBeNull();
    fireEvent.change(panel.getByLabelText("Kind"), { target: { value: "all" } });
    expect(panel.getByText("Template draft deleted")).toBeInTheDocument();
  });

  it("shows each project's last update and opens its own activity from there", async () => {
    render(<AdminProjectsOverview onOpenProject={vi.fn()} />);
    const lastUpdate = await screen.findByRole("button", { name: /Last update just now: Ved, task status changed/ });
    fireEvent.click(lastUpdate);
    const panel = within(screen.getByRole("dialog", { name: "Activity" }));
    expect(panel.getByLabelText("Project")).toHaveValue("b");
    expect(panel.getByText("1 event, newest first")).toBeInTheDocument();
    // Projects with no recent events say so rather than showing a blank.
    expect(screen.getAllByRole("button", { name: /No recent updates/ }).length).toBeGreaterThan(0);
  });

  it("summarises the week in one line", async () => {
    render(<AdminProjectsOverview onOpenProject={vi.fn()} />);
    expect(await screen.findByText("1 task update")).toBeInTheDocument();
  });

  it("keeps the table when the timeline is unavailable", async () => {
    projectsApi.timeline.mockRejectedValue(new Error("down"));
    render(<AdminProjectsOverview onOpenProject={vi.fn()} />);
    expect((await screen.findAllByRole("button", { name: "Open Head Office" })).length).toBeGreaterThan(0);
  });
});

describe("portfolioStanding", () => {
  it("agrees with the Overview: behind plan is at risk, drafts are drafts", () => {
    expect(portfolioStanding(PROJECTS[1], TIMELINE[1])).toBe("at_risk");
    expect(portfolioStanding(PROJECTS[2], undefined)).toBe("draft");
    expect(portfolioStanding(PROJECTS[3], TIMELINE[2])).toBe("delayed");
    expect(portfolioStanding({ ...PROJECTS[0], status: "on_hold" }, TIMELINE[0])).toBe("on_hold");
  });
});

describe("sortPortfolio", () => {
  it("sorts counts biggest first when asked and falls back to name", () => {
    const rows = [{ name: "B", overdue_count: 1 }, { name: "A", overdue_count: 1 }, { name: "C", overdue_count: 5 }];
    expect(sortPortfolio(rows, "overdue", "desc").map(row => row.name)).toEqual(["C", "A", "B"]);
  });
});

describe("activity helpers", () => {
  it("sorts audit actions into kinds", () => {
    expect(eventKind("TASK_STATUS_CHANGED")).toBe("tasks");
    expect(eventKind("PROJECT_EXTERNAL_APPROVAL_DECIDED")).toBe("approvals");
    expect(eventKind("TASK_APPROVAL_DECIDED")).toBe("approvals");
    expect(eventKind("PROJECT_ROLE_ASSIGNED")).toBe("team");
    expect(eventKind("VENDOR_CONTACT_ATTACHED")).toBe("team");
    expect(eventKind("PROJECT_TASKS_GENERATED")).toBe("setup");
    expect(eventKind("BROADCAST_SENT")).toBe("other");
  });

  it("counts only the last seven days and says so when nothing happened", () => {
    const now = new Date("2026-11-23T12:00:00Z").getTime();
    const events = [
      { action: "TASK_STARTED", occurred_at: "2026-11-22T10:00:00Z" },
      { action: "TASK_COMPLETED", occurred_at: "2026-11-21T10:00:00Z" },
      { action: "PROJECT_ACTIVATED", occurred_at: "2026-11-20T10:00:00Z" },
      { action: "TASK_STARTED", occurred_at: "2026-10-01T10:00:00Z" },
    ];
    expect(weekDigest(events, now)).toBe("2 task updates, 1 project activated");
    expect(weekDigest([], now)).toBe("No recorded changes in the last 7 days");
  });
});
