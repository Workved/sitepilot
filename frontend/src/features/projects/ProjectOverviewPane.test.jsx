import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProjectOverviewPane } from "./components/ProjectOverviewPane";

const project = { id: "p1", status: "active", start_date: "2026-11-18", target_handover_date: "2027-01-01", site_address: "New Delhi" };
const summary = {
  progress_pct: 0, total_count: 2, completed_count: 0, overdue_count: 1, blocked_count: 0, delayed_count: 0,
  pending_approvals: 0, pending_verifications: 2, no_update_count: 0,
  phases: [{ phase: "IT & ELV", total: 2, completed: 0, in_progress: 1, not_started: 1, pct: 0, status: "in_progress" }],
};
const attention = [{ id: "a1", severity: "critical", title: "1 task overdue", subtitle: "TEST Project", pane: "dashboard" }];

describe("Project overview pane", () => {
  it("shows the overdue count the banner talks about, plus verifications", () => {
    render(<ProjectOverviewPane project={project} summary={summary} attention={attention} onOpenPane={vi.fn()}/>);
    expect(screen.getByRole("button", { name: /Overdue tasks: 1/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Awaiting verification: 2/ })).toBeInTheDocument();
  });

  it("lists each attention item once and opens the pane that resolves it", () => {
    const onOpenPane = vi.fn();
    render(<ProjectOverviewPane project={project} summary={summary} attention={attention} onOpenPane={onOpenPane}/>);
    expect(screen.getAllByText("1 task overdue")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /1 task overdue/ }));
    expect(onOpenPane).toHaveBeenCalledWith("dashboard");
  });

  it("says plainly when nothing is waiting", () => {
    render(<ProjectOverviewPane project={project} summary={summary} attention={[]} onOpenPane={vi.fn()}/>);
    expect(screen.getByText("Nothing is waiting on you here.")).toBeInTheDocument();
  });
});
