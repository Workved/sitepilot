import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { cardStatus, OverviewPage, plannedPercent } from "./OverviewPage";

vi.mock("../../api/projectsApi", () => ({
  projectsApi: { timeline: vi.fn(), attention: vi.fn() },
}));

function row(overrides) {
  return {
    project_id: overrides.code, code: overrides.code, name: overrides.name, status: "active",
    start_date: "2026-01-01", target_handover_date: "2027-01-01", progress_pct: 50,
    task_count: 100, completed_count: 50, overdue_count: 0, blocked_count: 0, days_late: 0,
    health: "on_track", approvals: [], ...overrides,
  };
}

const TIMELINE = [
  row({ code: "WV-1", name: "Meridian Tower", health: "delayed", overdue_count: 6, days_late: 9, progress_pct: 20, completed_count: 20 }),
  row({ code: "WV-2", name: "Harbourview", blocked_count: 2, health: "at_risk", approvals: [{ name: "Fire NOC", overdue: true }] }),
  row({ code: "WV-3", name: "Draft Site", status: "draft", task_count: 0, completed_count: 0, progress_pct: 0 }),
];
const ATTENTION = [
  { id: "a1", group: "Needs a decision", severity: "decision", title: "Approve carpentry samples", subtitle: "Client", project_code: "WV-2", pane: "gates" },
  { id: "a2", group: "Running late", severity: "critical", title: "Ceiling grid overdue", subtitle: "Ceiling", project_code: "WV-1", pane: "overview" },
];

describe("OverviewPage", () => {
  beforeEach(() => {
    projectsApi.timeline.mockResolvedValue(TIMELINE);
    projectsApi.attention.mockResolvedValue(ATTENTION);
  });

  it("derives the headline and health numbers from running projects only", async () => {
    render(<OverviewPage user={{ name: "Anika Rao" }} tabs={[["overview", "Overview"]]} />);
    // 70 of 200 tasks on the two running projects; the draft is excluded.
    expect(await screen.findByText("35%")).toBeInTheDocument();
    expect(screen.getByText(/70 of 200 tasks complete across 2 running projects/)).toBeInTheDocument();
    const health = screen.getByRole("region", { name: "Site health" });
    expect(within(health).getByText("Overdue tasks").closest("div").textContent).toContain("6");
    expect(within(health).getByText("Approvals overdue").closest("div").textContent).toContain("1");
  });

  it("lists critical attention first and deep-links into the project pane", async () => {
    const onOpenProject = vi.fn();
    render(<OverviewPage user={{ name: "Anika Rao" }} tabs={[]} onOpenProject={onOpenProject} />);
    const first = (await screen.findAllByRole("button", { name: /Ceiling grid overdue|Approve carpentry samples/ }))[0];
    expect(first).toHaveTextContent("Ceiling grid overdue");
    fireEvent.click(first);
    expect(onOpenProject).toHaveBeenCalledWith("WV-1", "overview");
  });

  it("only offers the execution board shortcut to roles that can open it", async () => {
    const onTabChange = vi.fn();
    const { unmount } = render(<OverviewPage user={{ name: "A" }} tabs={[["execution", "Execution"]]} onTabChange={onTabChange} />);
    fireEvent.click(await screen.findByRole("button", { name: /Open execution board/ }));
    expect(onTabChange).toHaveBeenCalledWith("execution");
    unmount();
    render(<OverviewPage user={{ name: "A" }} tabs={[]} />);
    await screen.findByText("Site health");
    expect(screen.queryByRole("button", { name: /Open execution board/ })).toBeNull();
  });

  it("filters project cards by health", async () => {
    render(<OverviewPage user={{ name: "A" }} tabs={[]} />);
    await screen.findByRole("button", { name: "Open Meridian Tower" });
    fireEvent.click(screen.getByRole("tab", { name: /Delayed/ }));
    expect(screen.getByRole("button", { name: "Open Meridian Tower" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Harbourview" })).toBeNull();
  });

  it("keeps the portfolio numbers when only the attention feed fails", async () => {
    projectsApi.attention.mockRejectedValue(new Error("Attention feed unavailable"));
    render(<OverviewPage user={{ name: "A" }} tabs={[]} />);
    expect(await screen.findByText("Attention feed unavailable")).toBeInTheDocument();
    expect(screen.getByText("35%")).toBeInTheDocument();
  });
});

describe("plannedPercent", () => {
  it("is the elapsed share of the start-to-handover window, clamped to 0-100", () => {
    const window = { start_date: "2026-01-01", target_handover_date: "2026-01-11" };
    expect(plannedPercent(window, new Date("2026-01-06T00:00:00"))).toBe(50);
    expect(plannedPercent(window, new Date("2025-12-01T00:00:00"))).toBe(0);
    expect(plannedPercent(window, new Date("2026-03-01T00:00:00"))).toBe(100);
    expect(plannedPercent({ start_date: null, target_handover_date: "2026-01-11" })).toBeNull();
  });
});

describe("cardStatus", () => {
  it("never calls a project with overdue tasks 'On plan', even when its forecast is on time", () => {
    expect(cardStatus({ health: "delayed", days_late: 0, overdue_count: 2 }).text).toBe("2 overdue");
    expect(cardStatus({ health: "delayed", days_late: 1, overdue_count: 2 }).text).toBe("1 day late");
    expect(cardStatus({ health: "at_risk", days_late: 0, overdue_count: 0, blocked_count: 1 }).text).toBe("1 blocked");
    expect(cardStatus({ health: "on_track", days_late: 0, overdue_count: 0, blocked_count: 0, behind: true }).text).toBe("Behind plan");
    expect(cardStatus({ health: "on_track", days_late: 0, overdue_count: 0, blocked_count: 0 }).text).toBe("On plan");
  });
});
