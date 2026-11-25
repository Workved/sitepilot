import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { reviewStateFor, TaskDecisionModal } from "./components/TaskDecisionModal";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { verify: vi.fn(), approve: vi.fn() } }));

const workTask = { id: "t1", original_code: "T001", title: "Mobilise site", task_kind: "work", task_class: "standard", lifecycle_status: "submitted" };
const classATask = { ...workTask, task_class: "class_a", lifecycle_status: "verified" };
const gateTask = { id: "t2", original_code: "T010", title: "Fire NOC", task_kind: "approval_gate", task_class: null, lifecycle_status: "submitted" };

beforeEach(() => {
  vi.clearAllMocks();
});

const supervisor = { role: "supervisor" };
const pm = { role: "project_manager" };
const admin = { role: "admin" };

describe("TaskDecisionModal", () => {
  it("renders nothing when the task has no pending decision", () => {
    const { container } = render(<TaskDecisionModal projectId="p1" task={{ ...workTask, lifecycle_status: "in_progress" }} user={supervisor} onDecided={vi.fn()}/>);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers Verify for a submitted work task and calls the verify endpoint", async () => {
    taskExecutionApi.verify.mockResolvedValue({});
    const onDecided = vi.fn();
    render(<TaskDecisionModal projectId="p1" task={workTask} user={supervisor} onDecided={onDecided}/>);
    expect(screen.getByText("Supervisor verification")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Verify completion" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm verification/i }));
    await waitFor(() => expect(taskExecutionApi.verify).toHaveBeenCalledWith("p1", "t1", { decision: "verified", remarks: null }));
    expect(onDecided).toHaveBeenCalledTimes(1);
  });

  it("requires a reason to reject and blocks submission until provided", async () => {
    taskExecutionApi.verify.mockResolvedValue({});
    render(<TaskDecisionModal projectId="p1" task={workTask} user={supervisor} onDecided={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.submit(screen.getByRole("button", { name: /confirm rejection/i }).closest("form"));
    expect(await screen.findByText(/correction reason is required/i)).toBeInTheDocument();
    expect(taskExecutionApi.verify).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/correction reason/i), { target: { value: "Missing site photos." } });
    fireEvent.click(screen.getByRole("button", { name: /confirm rejection/i }));
    await waitFor(() => expect(taskExecutionApi.verify).toHaveBeenCalledWith("p1", "t1", { decision: "rejected", remarks: "Missing site photos." }));
  });

  it("offers Approve for Class A verified work and calls the approve endpoint", async () => {
    taskExecutionApi.approve.mockResolvedValue({});
    render(<TaskDecisionModal projectId="p1" task={classATask} user={pm} onDecided={vi.fn()}/>);
    expect(screen.getByText("PM approval")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm approval/i }));
    await waitFor(() => expect(taskExecutionApi.approve).toHaveBeenCalledWith("p1", "t1", { decision: "approved", remarks: null }));
  });

  it("offers Approve directly for a submitted approval gate (no verification step)", async () => {
    taskExecutionApi.approve.mockResolvedValue({});
    render(<TaskDecisionModal projectId="p1" task={gateTask} user={pm} onDecided={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm approval/i }));
    await waitFor(() => expect(taskExecutionApi.approve).toHaveBeenCalledWith("p1", "t2", { decision: "approved", remarks: null }));
  });

  it("surfaces a backend error inline without closing the modal", async () => {
    taskExecutionApi.verify.mockRejectedValue(new Error("This task has no pending progress submission to verify."));
    render(<TaskDecisionModal projectId="p1" task={workTask} user={supervisor} onDecided={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "Verify completion" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm verification/i }));
    expect(await screen.findByText("This task has no pending progress submission to verify.")).toBeInTheDocument();
  });

  // ---- role gating: only the valid approver/verifier sees the action -----

  it("does not offer Approve to a Supervisor - only PM/Admin may approve - and shows an awaiting message instead", () => {
    render(<TaskDecisionModal projectId="p1" task={classATask} user={supervisor} onDecided={vi.fn()}/>);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText("Awaiting PM approval")).toBeInTheDocument();
  });

  it("does not offer Verify to an actor with no recognised role and shows an awaiting message instead", () => {
    render(<TaskDecisionModal projectId="p1" task={workTask} user={{ role: "internal_employee" }} onDecided={vi.fn()}/>);
    expect(screen.queryByRole("button", { name: "Verify completion" })).not.toBeInTheDocument();
    expect(screen.getByText("Awaiting Supervisor verification")).toBeInTheDocument();
  });

  it("shows no awaiting message and no action for an actor viewing a task with nothing pending", () => {
    const { container } = render(<TaskDecisionModal projectId="p1" task={{ ...workTask, lifecycle_status: "in_progress" }} user={{ role: "internal_employee" }} onDecided={vi.fn()}/>);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers both Verify and Approve to Admin regardless of decision type", () => {
    render(<TaskDecisionModal projectId="p1" task={workTask} user={admin} onDecided={vi.fn()}/>);
    expect(screen.getByRole("button", { name: "Verify completion" })).toBeInTheDocument();
  });

  // ---- task_kind is nullable - a task with no kind is still ordinary work

  it("offers Verify completion for a submitted task with no task_kind assigned", async () => {
    taskExecutionApi.verify.mockResolvedValue({});
    const nullKindTask = { ...workTask, task_kind: null };
    render(<TaskDecisionModal projectId="p1" task={nullKindTask} user={supervisor} onDecided={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "Verify completion" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm verification/i }));
    await waitFor(() => expect(taskExecutionApi.verify).toHaveBeenCalledWith("p1", "t1", { decision: "verified", remarks: null }));
  });

  it("does not treat a milestone or approval gate as work even without task_class", () => {
    const { container: milestoneContainer } = render(<TaskDecisionModal projectId="p1" task={{ ...workTask, task_kind: "milestone", task_class: null }} user={supervisor} onDecided={vi.fn()}/>);
    expect(milestoneContainer).toBeEmptyDOMElement();
  });

  // ---- Admin override confirmation: a speed bump, not a block, when the
  // role that normally owns this decision is actually available -----------

  describe("Admin override confirmation", () => {
    const projectWithActiveSupervisor = { memberships: [{ project_role: "site_supervisor", ends_at: null }] };
    const projectWithEndedSupervisor = { memberships: [{ project_role: "site_supervisor", ends_at: "2026-08-01T00:00:00Z" }] };
    const projectWithActivePm = { memberships: [{ project_role: "project_manager", ends_at: null }] };

    it("warns Admin before verifying while a Supervisor is active, and proceeds only after confirming", async () => {
      taskExecutionApi.verify.mockResolvedValue({});
      render(<TaskDecisionModal projectId="p1" project={projectWithActiveSupervisor} task={workTask} user={admin} onDecided={vi.fn()}/>);
      fireEvent.click(screen.getByRole("button", { name: "Verify completion" }));
      expect(await screen.findByText(/supervisor is currently assigned/i)).toBeInTheDocument();
      expect(taskExecutionApi.verify).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: /continue as admin/i }));
      fireEvent.click(await screen.findByRole("button", { name: /confirm verification/i }));
      await waitFor(() => expect(taskExecutionApi.verify).toHaveBeenCalledWith("p1", "t1", { decision: "verified", remarks: null }));
    });

    it("lets Cancel on the warning drop the action entirely", async () => {
      render(<TaskDecisionModal projectId="p1" project={projectWithActiveSupervisor} task={workTask} user={admin} onDecided={vi.fn()}/>);
      fireEvent.click(screen.getByRole("button", { name: "Verify completion" }));
      fireEvent.click(await screen.findByRole("button", { name: /^cancel$/i }));
      expect(screen.queryByText(/supervisor is currently assigned/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /confirm verification/i })).not.toBeInTheDocument();
    });

    it("skips the warning when no Supervisor is currently active (a genuine fallback)", async () => {
      taskExecutionApi.verify.mockResolvedValue({});
      render(<TaskDecisionModal projectId="p1" project={projectWithEndedSupervisor} task={workTask} user={admin} onDecided={vi.fn()}/>);
      fireEvent.click(screen.getByRole("button", { name: "Verify completion" }));
      expect(screen.queryByText(/supervisor is currently assigned/i)).not.toBeInTheDocument();
      fireEvent.click(await screen.findByRole("button", { name: /confirm verification/i }));
      await waitFor(() => expect(taskExecutionApi.verify).toHaveBeenCalled());
    });

    it("also warns before an Admin approves while a PM is active", async () => {
      taskExecutionApi.approve.mockResolvedValue({});
      render(<TaskDecisionModal projectId="p1" project={projectWithActivePm} task={classATask} user={admin} onDecided={vi.fn()}/>);
      fireEvent.click(screen.getByRole("button", { name: "Approve" }));
      expect(await screen.findByText(/pm is currently assigned/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /continue as admin/i }));
      fireEvent.click(await screen.findByRole("button", { name: /confirm approval/i }));
      await waitFor(() => expect(taskExecutionApi.approve).toHaveBeenCalled());
    });

    it("does not warn a non-Admin verifier even with an active Supervisor", async () => {
      taskExecutionApi.verify.mockResolvedValue({});
      render(<TaskDecisionModal projectId="p1" project={projectWithActiveSupervisor} task={workTask} user={supervisor} onDecided={vi.fn()}/>);
      fireEvent.click(screen.getByRole("button", { name: "Verify completion" }));
      expect(screen.queryByText(/supervisor is currently assigned/i)).not.toBeInTheDocument();
      fireEvent.click(await screen.findByRole("button", { name: /confirm verification/i }));
      await waitFor(() => expect(taskExecutionApi.verify).toHaveBeenCalled());
    });
  });
});

describe("self-verification", () => {
  const project = { memberships: [
    { user_id: "u-pm", name: "Prachi", project_role: "project_manager" },
    { user_id: "u-sup", name: "Deepak", project_role: "site_supervisor" },
  ] };
  const submittedBySupervisor = { ...workTask, progress_updates: [
    { id: "a", submitted_by: "u-pm", created_at: "2026-11-24T09:00:00Z" },
    { id: "b", submitted_by: "u-sup", created_at: "2026-11-25T09:00:00Z" },
  ] };

  it("never offers Verify to whoever submitted the latest progress, and names who can", () => {
    render(<TaskDecisionModal projectId="p1" project={project} task={submittedBySupervisor} user={{ id: "u-sup", role: "supervisor" }} onDecided={vi.fn()}/>);
    expect(screen.queryByRole("button", { name: "Verify completion" })).toBeNull();
    expect(screen.getByText("You submitted this work, so someone else has to verify it: Prachi or an admin.")).toBeInTheDocument();
  });

  it("lets the other accountable member and admins verify", () => {
    expect(reviewStateFor(submittedBySupervisor, { id: "u-pm", role: "project_manager" }, project)).toMatchObject({ action: "verify", canAct: true });
    expect(reviewStateFor(submittedBySupervisor, { id: "u-sup", role: "admin" }, project)).toMatchObject({ canAct: true, selfSubmitted: false });
    expect(reviewStateFor(submittedBySupervisor, { id: "u-sup", role: "supervisor" }, project)).toMatchObject({ canAct: false, selfSubmitted: true, waitingOn: "Prachi or an admin" });
  });

  it("says who approval is waiting on", () => {
    expect(reviewStateFor(classATask, { id: "u-sup", role: "supervisor" }, project)).toMatchObject({ action: "approve", canAct: false, waitingOn: "Prachi" });
  });
});
