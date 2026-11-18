import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionPage } from "./ExecutionPage";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  detail: vi.fn(), list: vi.fn(), executionTasks: vi.fn(), dependencies: vi.fn(), externalGates: vi.fn(),
} }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  list: vi.fn(), detail: vi.fn(), listExternalApprovals: vi.fn(), decideExternalApproval: vi.fn(),
} }));

// A deliberately messy, realistic mix of shapes a real project's execution
// tasks actually carry - multi-day spans, single-day, undated, dated only by
// actuals (no planned_start_date - the shape that crashed the calendar),
// every lifecycle_status, blocked/late/approval_pending readiness. This is
// an end-to-end render smoke test, not a behavior assertion: if any shape in
// here throws while rendering the Execution Calendar, the 3-Day Board or My
// Assigned Work, this test fails the same way the browser did.
const project = {
  id: "p1", name: "Sample Fitout Project", code: "P1", status: "active",
  memberships: [
    { id: "m1", user_id: "u-admin", employee_id: null, name: "Admin User", project_role: "project_manager", ends_at: null },
    { id: "m2", user_id: "u-emp", employee_id: "e1", name: "Rahul Verma", project_role: "internal_employee", ends_at: null },
  ],
};

const offsetIso = days => { const d = new Date(); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };

function task(overrides) {
  return {
    id: "t-base", project_id: "p1", baseline_id: "b1", original_code: "T000", template_sequence: 1,
    title: "Base task", task_kind: "work", task_class: "standard", lifecycle_status: "planned",
    schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1,
    planned_start_date: null, planned_end_date: null, actual_start_at: null, actual_finish_at: null,
    phase: "Setup", category: "Site", evidence_required: false, open_blocker_count: 0, active_support_count: 0,
    readiness: { state: "ready", reasons: [], advisories: [] }, variance: null, project_unresolved_approvals: [],
    created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

const tasks = [
  task({ id: "t1", original_code: "T031", title: "Install gypsum partition framework", phase: "Execution / Civil", lifecycle_status: "in_progress", planned_start_date: offsetIso(-2), planned_end_date: offsetIso(3), readiness: { state: "in_progress", reasons: [], advisories: [] }, variance: { status: "late", variance_days: 2, days: 2, measured_against: "planned_finish" } }),
  task({ id: "t2", original_code: "T020", title: "Electrical containment rough-in", phase: "Execution / MEP", lifecycle_status: "in_progress", planned_start_date: offsetIso(-5), planned_end_date: offsetIso(0), readiness: { state: "in_progress", reasons: [], advisories: [] } }),
  task({ id: "t3", original_code: "T032", title: "Plumbing rough-in", phase: "Execution / MEP", lifecycle_status: "ready", planned_start_date: offsetIso(1), planned_end_date: offsetIso(4), readiness: { state: "ready", reasons: [], advisories: [] } }),
  task({ id: "t4", original_code: "T001", title: "Freeze approved architectural layout", phase: "Pre-Activation", lifecycle_status: "planned", readiness: { state: "blocked", reasons: [{ kind: "approval", subject_id: "a1", detail: "Waiting on external approval FIRE-NOC.", blocking: true }], advisories: [] } }),
  // The exact shape that crashed the calendar: dated only by its actuals.
  task({ id: "t5", original_code: "T045", title: "Site mobilisation", phase: "Pre-Activation", lifecycle_status: "in_progress", actual_start_at: `${offsetIso(-1)}T09:00:00Z`, readiness: { state: "in_progress", reasons: [], advisories: [] } }),
  task({ id: "t6", original_code: "T050", title: "Handover documentation", phase: "Handover", lifecycle_status: "approval_pending", readiness: { state: "awaiting_approval", reasons: [], advisories: [] } }),
  task({ id: "t7", original_code: "T060", title: "Client walkthrough support", phase: "Handover", lifecycle_status: "completed", planned_start_date: offsetIso(-10), planned_end_date: offsetIso(-9), readiness: { state: "completed", reasons: [], advisories: [] } }),
  task({ id: "t8", original_code: "T070", title: "Snag list closeout", phase: "Handover", lifecycle_status: "cancelled", readiness: { state: "cancelled", reasons: [], advisories: [] } }),
];

const detailFor = id => ({
  ...tasks.find(t => t.id === id),
  description: "Smoke-test task detail.",
  early_start_reason: null, actor_is_assigned_support: true,
  predecessors: [], progress_updates: [], verifications: [], approvals: [],
  blockers: [], delays: [], support_assignments: [], audit_events: [],
});

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.list.mockResolvedValue([{ id: "p1", name: project.name, code: "P1", status: "active" }]);
  projectsApi.detail.mockResolvedValue(project);
  projectsApi.executionTasks.mockResolvedValue({ project_id: "p1", project_name: project.name, total_tasks: tasks.length, included_task_count: tasks.length, excluded_task_count: 0, tasks: [] });
  projectsApi.dependencies.mockResolvedValue({ items: [], total: 0, excluded_warning_count: 0 });
  projectsApi.externalGates.mockResolvedValue([]);
  taskExecutionApi.list.mockResolvedValue(tasks);
  taskExecutionApi.detail.mockImplementation((_projectId, taskId) => Promise.resolve(detailFor(taskId)));
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

describe("ExecutionPage smoke - realistic mixed task shapes render without throwing", () => {
  it("renders the Execution Calendar for an Admin and opens a task with actual-only dates", async () => {
    render(<ExecutionPage user={{ id: "u-admin", role: "admin" }}/>);
    expect(await screen.findByRole("group", { name: /execution summary/i })).toBeInTheDocument();
    // The Pre-Activation Checklist (undated tasks, like "Site mobilisation"
    // below) is collapsed by default - expand it so every fixture task is
    // reachable somewhere on screen (grid or checklist), nothing silently
    // dropped or thrown away rendering.
    fireEvent.click(screen.getByRole("button", { name: /pre-activation checklist/i }));
    // A task's name shows in the table and inside its bar.
    for (const fixture of tasks) {
      expect(screen.getAllByText(new RegExp(fixture.title)).length).toBeGreaterThan(0);
    }
    fireEvent.click(screen.getByText("Site mobilisation"));
    expect(await screen.findByText("Smoke-test task detail.")).toBeInTheDocument();
  });

  it("renders the 3-Day Operations Board for a Supervisor and opens a task", async () => {
    render(<ExecutionPage user={{ id: "u-sup", role: "supervisor" }}/>);
    expect(await screen.findByText("3-Day Operations Board")).toBeInTheDocument();
    const region = screen.getByRole("region", { name: /attention required/i });
    expect(region).toBeInTheDocument();
    // A multi-day task (planned to span Yesterday through Today+3) legitimately
    // appears in more than one column - that's correct, not a bug.
    fireEvent.click(screen.getAllByText("Install gypsum partition framework")[0]);
    expect(await screen.findByText("Smoke-test task detail.")).toBeInTheDocument();
  });

  it("renders My Assigned Work for an Internal Employee and opens the Action View", async () => {
    render(<ExecutionPage user={{ id: "u-emp", role: "internal_employee" }}/>);
    expect(await screen.findByRole("group", { name: /my work summary/i })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Electrical containment rough-in"));
    expect(await screen.findByRole("button", { name: /back to my assigned work/i })).toBeInTheDocument();
  });
});
