import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { TaskDetailDrawer } from "./components/TaskDetailDrawer";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  detail: vi.fn(), listExternalApprovals: vi.fn(), transitionStatus: vi.fn(), submitProgress: vi.fn(), downloadEvidence: vi.fn(),
  verify: vi.fn(), approve: vi.fn(), logBlocker: vi.fn(), resolveBlocker: vi.fn(), logDelay: vi.fn(),
  assignSupport: vi.fn(), endSupportAssignment: vi.fn(),
} }));

const admin = { id: "u-adm", role: "admin" };
const project = { id: "p1", memberships: [] };

const task = (overrides = {}) => ({
  id: "t1", original_code: "T010", title: "Mark partitions, cabins, workstations and service areas",
  lifecycle_status: "ready", phase: "Mobilisation", category: "Setting Out",
  readiness: { state: "ready", reasons: [], advisories: [] }, variance: null,
  ...overrides,
});

const detail = (overrides = {}) => ({
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T010", template_sequence: 1,
  title: "Mark partitions, cabins, workstations and service areas", task_kind: "work", task_class: "standard",
  lifecycle_status: "ready", schedule_classification: "execution",
  description: "Mark out partition lines per the approved layout.",
  predecessors: [], progress_updates: [], verifications: [], approvals: [],
  blockers: [], delays: [], support_assignments: [], audit_events: [],
  evidence_required: false, actor_is_assigned_support: false,
  readiness: { state: "ready", reasons: [], advisories: [] },
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
  document.body.style.overflow = "";
});

describe("TaskDetailDrawer", () => {
  it("shows the header (code, title, phase/category, status + readiness chips) and the 3 tabs", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail());
    render(<TaskDetailDrawer projectId="p1" project={project} task={task()} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
    expect(screen.getByText("T010")).toBeInTheDocument();
    expect(screen.getByText("Mark partitions, cabins, workstations and service areas")).toBeInTheDocument();
    expect(screen.getByText("Mobilisation / Setting Out")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /overview/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /action forms/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /activity log/i })).toBeInTheDocument();
    // Overview is the default tab.
    expect(await screen.findByText("Mark out partition lines per the approved layout.")).toBeInTheDocument();
  });

  describe("task type badge (from the task's task_kind / task_class)", () => {
    const renderWith = async overrides => {
      taskExecutionApi.detail.mockResolvedValue(detail(overrides));
      render(<TaskDetailDrawer projectId="p1" project={project} task={task(overrides)} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
      await screen.findByText("Task Details");
    };

    it("labels standard work Standard, with no approval-flow text", async () => {
      await renderWith({ task_kind: "work", task_class: "standard" });
      expect(screen.getByText("Standard")).toBeInTheDocument();
      expect(screen.queryByText(/PM Approval/)).not.toBeInTheDocument();
    });

    it("labels Class A work and shows Supervisor Verification → PM Approval", async () => {
      await renderWith({ task_kind: "work", task_class: "class_a" });
      expect(screen.getByText("Class A")).toBeInTheDocument();
      expect(screen.getByText("Supervisor Verification → PM Approval")).toBeInTheDocument();
    });

    it("labels an approval gate by its kind, even when its class is class_a, with Direct PM Approval", async () => {
      await renderWith({ task_kind: "approval_gate", task_class: "class_a" });
      expect(screen.getByText("Approval Gate")).toBeInTheDocument();
      expect(screen.getByText("Direct PM Approval")).toBeInTheDocument();
      expect(screen.queryByText("Class A")).not.toBeInTheDocument();
    });

    it("treats a task with no kind or class as standard work", async () => {
      await renderWith({ task_kind: null, task_class: null });
      expect(screen.getByText("Standard")).toBeInTheDocument();
    });

    it("gives a milestone no type badge", async () => {
      await renderWith({ task_kind: "milestone", task_class: null });
      expect(screen.queryByText("Standard")).not.toBeInTheDocument();
      expect(screen.queryByText("Approval Gate")).not.toBeInTheDocument();
    });
  });

  it("switches to Action Forms and back via tabs", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail({ lifecycle_status: "in_progress" }));
    render(<TaskDetailDrawer projectId="p1" project={project} task={task({ lifecycle_status: "in_progress" })} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
    await screen.findByText("Task Details");
    fireEvent.click(screen.getByRole("button", { name: /action forms/i }));
    expect(await screen.findByText("Log progress")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^overview/i }));
    expect(await screen.findByText("Task Details")).toBeInTheDocument();
    expect(screen.queryByText("Log progress")).not.toBeInTheDocument();
  });

  it("Update Progress quick action switches to Action Forms and lands on the progress form", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail({ lifecycle_status: "in_progress" }));
    render(<TaskDetailDrawer projectId="p1" project={project} task={task({ lifecycle_status: "in_progress" })} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
    await screen.findByText("Task Details");
    fireEvent.click(screen.getByRole("button", { name: /update progress/i }));
    expect(await screen.findByText("Log progress")).toBeInTheDocument();
  });

  it("shows a sticky footer with the primary contextual action for a ready task, and it triggers the same transition", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail());
    taskExecutionApi.transitionStatus.mockResolvedValue({});
    render(<TaskDetailDrawer projectId="p1" project={project} task={task()} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
    // The header's readiness pill ("Ready to start") renders synchronously
    // off the summary `task` prop; the footer only appears once
    // TaskDetailContent's own detail fetch resolves and lifts its state up -
    // wait for the footer's own (differently worded) help text specifically.
    expect(await screen.findByText("Task is ready to start.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start Task" }));
    await waitFor(() => expect(taskExecutionApi.transitionStatus).toHaveBeenCalledWith("p1", "t1", { target_status: "in_progress" }));
  });

  it("disables Mark Ready in the footer and explains why when the task is blocked", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail({
      lifecycle_status: "planned",
      readiness: { state: "blocked", reasons: [{ kind: "dependency", subject_id: "t0", detail: "x", blocking: true }], advisories: [] },
    }));
    render(<TaskDetailDrawer projectId="p1" project={project} task={task({ lifecycle_status: "planned", readiness: { state: "blocked", reasons: [], advisories: [] } })} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
    expect(await screen.findByText(/cannot mark ready yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark Ready" })).toBeDisabled();
  });

  it("closes when the backdrop is clicked and when the close button is clicked", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail());
    const onClose = vi.fn();
    render(<TaskDetailDrawer projectId="p1" project={project} task={task()} user={admin} candidates={[]} onClose={onClose} onChanged={vi.fn()}/>);
    await screen.findByText("T010");
    // The drawer renders in <body> (above the whole page), not inside the page.
    fireEvent.click(document.body.querySelector("div.fixed.inset-0[aria-hidden='true']"));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /close task detail/i }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("locks page scroll while open and restores it once the task is cleared", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail());
    const { rerender } = render(<TaskDetailDrawer projectId="p1" project={project} task={task()} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
    await screen.findByText("T010");
    expect(document.body.style.overflow).toBe("hidden");
    rerender(<TaskDetailDrawer projectId="p1" project={project} task={null} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
    expect(document.body.style.overflow).toBe("");
  });

  it("renders nothing when there is no selected task", () => {
    const { container } = render(<TaskDetailDrawer projectId="p1" project={project} task={null} user={admin} candidates={[]} onClose={vi.fn()} onChanged={vi.fn()}/>);
    expect(container).toBeEmptyDOMElement();
  });
});
