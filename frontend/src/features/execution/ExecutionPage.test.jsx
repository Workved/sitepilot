import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionPage } from "./ExecutionPage";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  detail: vi.fn(),
  list: vi.fn(), executionTasks: vi.fn(), dependencies: vi.fn(), externalGates: vi.fn(),
} }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  list: vi.fn(), detail: vi.fn(), listExternalApprovals: vi.fn(), decideExternalApproval: vi.fn(),
} }));

const activeProjects = [{ id: "p1", name: "Sample Fitout Project", code: "P1", status: "active" }];
const assignedTask = {
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T001", template_sequence: 1,
  title: "Freeze approved architectural layout", task_kind: "work", task_class: "standard", lifecycle_status: "in_progress",
  schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1, phase: "Design",
  category: "Planning", evidence_required: false, open_blocker_count: 0, active_support_count: 1,
  created_at: "2026-08-05T00:00:00Z", updated_at: "2026-08-05T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.list.mockResolvedValue(activeProjects);
  // ExecutionCalendarView/SupervisorOperationsBoard resolve the actor's
  // authority from the project's active memberships, so every render needs
  // this even when the test is about something else.
  projectsApi.detail.mockResolvedValue({ id: "p1", memberships: [] });
  projectsApi.executionTasks.mockResolvedValue({
    project_id: "p1", project_name: "Sample Fitout Project", total_tasks: 42, included_task_count: 40, excluded_task_count: 2, tasks: [],
  });
  projectsApi.dependencies.mockResolvedValue({ items: [], total: 12, excluded_warning_count: 0 });
  projectsApi.externalGates.mockResolvedValue([]);
  taskExecutionApi.list.mockResolvedValue([assignedTask]);
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

describe("ExecutionPage - Internal Employee scoping", () => {
  it("does not fetch the whole-project baseline/dependencies/gates for an Internal Employee", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    expect(await screen.findByText("Freeze approved architectural layout")).toBeInTheDocument();
    expect(projectsApi.executionTasks).not.toHaveBeenCalled();
    expect(projectsApi.dependencies).not.toHaveBeenCalled();
    expect(projectsApi.externalGates).not.toHaveBeenCalled();
  });

  it("shows the project name from the project list, not from the (skipped) whole-project fetch", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    expect(await screen.findByText("Sample Fitout Project")).toBeInTheDocument();
    expect(screen.getByText("Your assigned tasks")).toBeInTheDocument();
  });

  it("shows My Work and External Approvals, but no Dependencies or Execution Calendar tab", async () => {
    // External Approvals is the one other sub-tab offered to an Internal
    // Employee: they can be a gate's assignee and need to submit evidence
    // for it. list_for_project scopes what they see there to their own
    // assigned gates - see the ExternalApprovalsPanel test file.
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    await screen.findByText("Freeze approved architectural layout");
    expect(screen.queryByText("Total tasks")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dependencies/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execution calendar/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /my work/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /external approvals/i })).toBeInTheDocument();
  });

  it("lets an Internal Employee open External Approvals and see a gate assigned to them", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([{
      id: "a1", project_id: "p1", project_gate_id: "g1", gate_code: "FIRE-NOC", gate_name: "Fire NOC",
      status: "assigned", blocking: true, coverage_state: "exact", coverage_text: null, covered_task_ids: [],
      assigned_to_user_id: "u-ie", assigned_to_name: "Employee", assigned_by: "u-adm", assigned_at: "2026-08-10T09:00:00Z",
      rejection_reason: null, decided_by: null, decided_by_name: null, decided_at: null,
    }]);
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    await screen.findByText("Freeze approved architectural layout");
    fireEvent.click(screen.getByRole("button", { name: /external approvals/i }));
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Fire NOC"));
    expect(await screen.findByText("Update / submit evidence")).toBeInTheDocument();
  });

  it("opens the Task Detail Action View from a row and can go back", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    fireEvent.click(await screen.findByText("Freeze approved architectural layout"));
    expect(await screen.findByRole("button", { name: /back to my assigned work/i })).toBeInTheDocument();
    // The header repeats the task title in the Action View.
    expect(screen.getAllByText("Freeze approved architectural layout").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /back to my assigned work/i }));
    expect(await screen.findByRole("group", { name: /my work summary/i })).toBeInTheDocument();
  });
});

describe("ExecutionPage - role-specific view per tab", () => {
  it("shows the 3-Day Operations Board for a Supervisor, with Dependencies and External Approvals tabs", async () => {
    render(<ExecutionPage user={{ role: "supervisor", id: "u-sup" }}/>);
    await waitFor(() => expect(projectsApi.executionTasks).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText("3-Day Operations Board")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dependencies/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /external approvals/i })).toBeInTheDocument();
  });

  it("shows the Execution Calendar for an Admin, with Dependencies and External Approvals tabs", async () => {
    render(<ExecutionPage user={{ role: "admin", id: "u-adm" }}/>);
    await waitFor(() => expect(projectsApi.executionTasks).toHaveBeenCalledWith("p1"));
    expect(await screen.findByRole("group", { name: /execution summary/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dependencies/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /external approvals/i })).toBeInTheDocument();
  });
});

// U18's verification: approving the last pending approval on a blocked task
// flips it to ready without the user reloading anything. This is the whole
// point of the unit - the approvals endpoints and the readiness engine both
// shipped weeks ago and nothing on this surface could reach either.
describe("ExecutionPage - external approval decisions", () => {
  const admin = { role: "admin", id: "u-adm" };
  const blockedTask = {
    ...assignedTask, lifecycle_status: "planned",
    readiness: {
      state: "blocked",
      reasons: [{ kind: "approval", subject_id: "a1", detail: "Waiting on external approval FIRE-NOC (submitted).", blocking: true }],
      advisories: [],
    },
  };
  const releasedTask = { ...blockedTask, readiness: { state: "ready", reasons: [], advisories: [] } };
  const approval = {
    id: "a1", project_id: "p1", project_gate_id: "g1", gate_code: "FIRE-NOC", gate_name: "Fire NOC",
    status: "submitted", blocking: true, coverage_state: "exact", coverage_text: null,
    covered_task_ids: ["t1"],
    assigned_to_user_id: "u-emp", assigned_to_name: "Employee", assigned_by: "u-adm", assigned_at: "2026-08-10T09:00:00Z",
    rejection_reason: null, decided_by: null, decided_by_name: null, decided_at: null,
  };

  beforeEach(() => {
    projectsApi.detail.mockResolvedValue({
      id: "p1", memberships: [
        { id: "m1", user_id: "u-pm", project_role: "project_manager", ends_at: null },
        { id: "m2", user_id: "u-emp", employee_id: "emp-1", name: "Employee", project_role: "internal_employee", ends_at: null },
      ],
    });
    taskExecutionApi.listExternalApprovals.mockResolvedValue([approval]);
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
  });

  it("flips a blocked task to ready once its last approval is granted, with no reload", async () => {
    // Neither fixture carries a planned date, so both land in the calendar's
    // Pre-Activation Checklist rather than the day-grid - either way it's a
    // row with the same readiness pill the old flat board showed. The
    // checklist is collapsed by default, so it has to be expanded first.
    taskExecutionApi.list
      .mockResolvedValueOnce([blockedTask])
      .mockResolvedValue([releasedTask]);
    render(<ExecutionPage user={admin}/>);
    fireEvent.click(await screen.findByRole("button", { name: /pre-activation checklist/i }));
    const row = await screen.findByRole("button", { name: /freeze approved architectural layout/i });
    expect(within(row).getByText("Blocked")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /external approvals/i }));
    fireEvent.click(await screen.findByText("Fire NOC"));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm approval" }));
    await waitFor(() => expect(taskExecutionApi.decideExternalApproval).toHaveBeenCalledWith(
      "p1", "a1", { decision: "approved", reason: null },
    ));

    fireEvent.click(screen.getByRole("button", { name: /execution calendar/i }));
    fireEvent.click(await screen.findByRole("button", { name: /pre-activation checklist/i }));
    const releasedRow = await screen.findByRole("button", { name: /freeze approved architectural layout/i });
    expect(within(releasedRow).getByText("Ready to start")).toBeInTheDocument();
    expect(within(releasedRow).queryByText("Blocked")).not.toBeInTheDocument();
  });

  it("renders the tab from the execution layer, not from the planning gates", async () => {
    // The planning-layer gates are still read, but only to explain an empty
    // list (how many are awaiting an applicability decision). What is
    // RENDERED as approvals comes from the execution-layer endpoint - that
    // was the point of the switch, and it is what this pins.
    projectsApi.externalGates.mockResolvedValue({ items: [{ id: "g1", applicability_state: "applicable" }] });
    render(<ExecutionPage user={admin}/>);
    fireEvent.click(await screen.findByRole("button", { name: /external approvals/i }));
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledWith("p1");
  });

  it("explains an empty tab by naming the gates still awaiting review", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
    projectsApi.externalGates.mockResolvedValue({
      items: Array.from({ length: 32 }, (_, index) => ({ id: `g${index}`, applicability_state: "pending_review" })),
    });
    render(<ExecutionPage user={admin}/>);
    fireEvent.click(await screen.findByRole("button", { name: /external approvals/i }));
    expect(await screen.findByText(/32 external approvals are awaiting applicability review/i)).toBeInTheDocument();
  });
});

describe("ExecutionPage - link to a project's External Approvals", () => {
  // A notification can link to ?tab=execution&project=<code>&pane=approvals.
  const projects = [
    { id: "p1", name: "Sample Fitout Project", code: "P1", status: "active" },
    { id: "p2", name: "SIS Interior", code: "P2", status: "active" },
  ];

  afterEach(() => window.history.replaceState({}, "", "/"));

  it("opens the linked project on its External Approvals tab", async () => {
    window.history.replaceState({}, "", "/?tab=execution&project=P2&pane=approvals");
    projectsApi.list.mockResolvedValue(projects);
    projectsApi.detail.mockResolvedValue({ id: "p2", memberships: [] });
    projectsApi.executionTasks.mockResolvedValue({
      project_id: "p2", project_name: "SIS Interior", total_tasks: 0, included_task_count: 0, excluded_task_count: 0, tasks: [],
    });

    render(<ExecutionPage user={{ role: "admin", id: "u-adm" }}/>);

    expect(await screen.findByRole("button", { name: /external approvals/i }, { timeout: 5000 })).toHaveClass("bg-blue-600");
    await waitFor(() => expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledWith("p2"));
    expect(screen.getByRole("combobox")).toHaveValue("p2");
    expect(screen.getByRole("button", { name: /external approvals/i })).toHaveClass("bg-blue-600");
  });

  it("falls back to the first project and default tab without a link", async () => {
    projectsApi.list.mockResolvedValue(projects);
    render(<ExecutionPage user={{ role: "admin", id: "u-adm" }}/>);

    await waitFor(() => expect(screen.getByRole("combobox")).toHaveValue("p1"));
    expect(await screen.findByRole("button", { name: /execution calendar/i }, { timeout: 5000 })).toHaveClass("bg-blue-600");
    expect(taskExecutionApi.listExternalApprovals).not.toHaveBeenCalled();
  });
});
