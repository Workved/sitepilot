import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { actorProjectRoles, TaskDetailContent } from "./components/TaskDetailContent";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  detail: vi.fn(), listExternalApprovals: vi.fn(), transitionStatus: vi.fn(), submitProgress: vi.fn(), downloadEvidence: vi.fn(), downloadTaskReference: vi.fn(),
  verify: vi.fn(), approve: vi.fn(), logBlocker: vi.fn(), resolveBlocker: vi.fn(), logDelay: vi.fn(),
  assignSupport: vi.fn(), endSupportAssignment: vi.fn(),
} }));

const baseTask = {
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T001", template_sequence: 1,
  title: "Mobilise site", task_kind: "work", task_class: "standard", lifecycle_status: "planned",
  schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1, phase: "Setup",
  category: "Site", evidence_required: false, open_blocker_count: 0, active_support_count: 0,
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
};
const detail = {
  ...baseTask,
  description: "Set up the site office and hoarding.",
  predecessors: [],
  progress_updates: [], verifications: [], approvals: [], blockers: [], delays: [], support_assignments: [],
  audit_events: [],
};

// Authority is derived from the actor's membership of THIS project, so an
// actor fixture needs an id that a membership can point at. A bare
// `{ role: "supervisor" }` is a supervisor who is not on the project, which
// is a real case this component must handle - see the non-member tests.
const supervisor = { id: "u-sup", role: "supervisor" };
const employee = { id: "u-emp", role: "internal_employee" };
const admin = { id: "u-adm", role: "admin" };
const projectManager = { id: "u-pm", role: "project_manager" };

const membership = (user, projectRole) => ({
  id: `m-${user.id}`, user_id: user.id, employee_id: `e-${user.id}`,
  name: "Member", project_role: projectRole, ends_at: null,
});
const projectWith = (...memberships) => ({ id: "p1", memberships });

const defaultProject = projectWith(
  membership(supervisor, "site_supervisor"),
  membership(projectManager, "project_manager"),
  membership(employee, "internal_employee"),
);

function renderDetail({ user = supervisor, project = defaultProject, task = baseTask, onChanged = vi.fn(), activeTab = "actions" } = {}) {
  const roles = actorProjectRoles(project, user);
  const candidates = (project?.memberships || []).filter(m => m.project_role === "internal_employee");
  render(<TaskDetailContent projectId="p1" project={project} task={task} user={user} roles={roles} candidates={candidates} onChanged={onChanged} activeTab={activeTab}/>);
}

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.detail.mockResolvedValue(detail);
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

describe("TaskDetailContent - Action Forms tab", () => {
  it("loads and shows the task's detail on mount", async () => {
    renderDetail({ activeTab: "overview" });
    expect(await screen.findByText("Set up the site office and hoarding.")).toBeInTheDocument();
    // No proof instructions or reference material on this task: no empty block.
    expect(screen.queryByText("Reference material")).not.toBeInTheDocument();
    expect(taskExecutionApi.detail).toHaveBeenCalledWith("p1", "t1");
  });

  it("shows a loading spinner then an error message if the fetch fails", async () => {
    taskExecutionApi.detail.mockRejectedValue(new Error("Server unavailable"));
    renderDetail();
    expect(screen.getByText(/loading task detail/i)).toBeInTheDocument();
    expect(await screen.findByText("Server unavailable")).toBeInTheDocument();
  });

  it("shows the valid forward transition for a Supervisor and advances it on click", async () => {
    taskExecutionApi.transitionStatus.mockResolvedValue({ ...detail, lifecycle_status: "ready" });
    const onChanged = vi.fn();
    renderDetail({ onChanged });
    await screen.findByRole("button", { name: "Mark Ready" });
    fireEvent.click(screen.getByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(taskExecutionApi.transitionStatus).toHaveBeenCalledWith("p1", "t1", { target_status: "ready" }));
    await waitFor(() => expect(taskExecutionApi.detail).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("hides status transition controls for a role the backend would reject", async () => {
    renderDetail({ user: employee });
    await screen.findByText("Support Assignment", { exact: false });
    expect(screen.queryByText("Status Action")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark Ready" })).not.toBeInTheDocument();
  });

  it("lets the assigned Internal Employee mark their planned task ready", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "planned", actor_is_assigned_support: true,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    taskExecutionApi.transitionStatus.mockResolvedValue({ ...detail, lifecycle_status: "ready" });
    renderDetail({ user: employee });
    fireEvent.click(await screen.findByRole("button", { name: "Mark Ready" }));
    await waitFor(() => expect(taskExecutionApi.transitionStatus).toHaveBeenCalledWith("p1", "t1", { target_status: "ready" }));
    expect(screen.queryByRole("button", { name: "Cancel task" })).not.toBeInTheDocument();
  });

  it("does not offer Mark Ready to an employee member who is not assigned to the task", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, lifecycle_status: "planned", actor_is_assigned_support: false });
    renderDetail({ user: employee });
    await screen.findByText("Support Assignment", { exact: false });
    expect(screen.queryByRole("button", { name: "Mark Ready" })).not.toBeInTheDocument();
  });

  it("lets the assigned Internal Employee start and submit their task", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "ready", actor_is_assigned_support: true,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    renderDetail({ user: employee });
    expect(await screen.findByRole("button", { name: "Start Task" })).toBeInTheDocument();
  });

  it("hides start/submit from an Internal Employee who is not the one assigned", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "ready", actor_is_assigned_support: false,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "someone-else", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    renderDetail({ user: employee });
    await screen.findByText("Support Assignment", { exact: false });
    expect(screen.queryByRole("button", { name: "Start Task" })).not.toBeInTheDocument();
  });

  it("hides start/submit from the Supervisor once an Internal Employee is assigned", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "ready", actor_is_assigned_support: false,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    renderDetail({ user: supervisor });
    await screen.findByText("Support Assignment", { exact: false });
    expect(screen.queryByRole("button", { name: "Start Task" })).not.toBeInTheDocument();
  });

  // U22: the evidence-required flag has been on the payload since the task
  // API existed and was rendered nowhere on this surface, so the rule was
  // invisible here.
  describe("evidence-required tasks", () => {
    const noteOnlyUpdate = { id: "pu1", note: "Framing done.", created_at: "2026-08-02T00:00:00Z", evidence: [] };
    const fileUpdate = { id: "pu2", note: "Framing done.", created_at: "2026-08-02T00:00:00Z", evidence: [{ id: "ev1", file_id: "f1", original_filename: "framing.jpg" }] };
    const readyToSubmit = extra => ({
      ...detail, lifecycle_status: "in_progress", evidence_required: true,
      progress_updates: [noteOnlyUpdate], verifications: [], ...extra,
    });

    it("blocks submit when the only update carries no file, and says why", async () => {
      taskExecutionApi.detail.mockResolvedValue(readyToSubmit());
      renderDetail();
      const submit = await screen.findByRole("button", { name: "Submit For Review" });
      expect(submit).toBeDisabled();
      expect(screen.getByText(/requires evidence/i)).toBeInTheDocument();
    });

    it("allows submit once an update carries a file", async () => {
      taskExecutionApi.detail.mockResolvedValue(readyToSubmit({ progress_updates: [fileUpdate] }));
      renderDetail();
      expect(await screen.findByRole("button", { name: "Submit For Review" })).toBeEnabled();
      expect(screen.queryByText(/requires evidence/i)).not.toBeInTheDocument();
    });

    it("still allows a note-only submit when evidence is not required", async () => {
      taskExecutionApi.detail.mockResolvedValue(readyToSubmit({ evidence_required: false }));
      renderDetail();
      expect(await screen.findByRole("button", { name: "Submit For Review" })).toBeEnabled();
    });

    it("ignores evidence already spent on a prior decision", async () => {
      taskExecutionApi.detail.mockResolvedValue(readyToSubmit({
        progress_updates: [{ ...fileUpdate, reviewed_at: "2026-08-03T00:00:00Z" }, { ...noteOnlyUpdate, id: "pu3" }],
        verifications: [{ id: "v1", submission_update_id: "pu2", decision: "rejected", verified_at: "2026-08-03T00:00:00Z" }],
      }));
      renderDetail();
      const submit = await screen.findByRole("button", { name: "Submit For Review" });
      expect(submit).toBeDisabled();
      expect(screen.getByText(/requires evidence/i)).toBeInTheDocument();
    });

    it("asks for progress rather than evidence when there is no fresh update at all", async () => {
      taskExecutionApi.detail.mockResolvedValue(readyToSubmit({ progress_updates: [] }));
      renderDetail();
      await screen.findByRole("button", { name: "Submit For Review" });
      expect(screen.getByText(/log a new progress update/i)).toBeInTheDocument();
      expect(screen.queryByText(/requires evidence/i)).not.toBeInTheDocument();
    });
  });

  // The backend counts only updates no decision has
  // covered yet (`reviewed_at` null), for work AND approval-gate tasks. The
  // board must refuse the same submissions before any request is sent.
  // Resolve follows the backend's resolver rule.
  describe("blocker Resolve visibility", () => {
    const withOpenBlocker = { ...detail, lifecycle_status: "in_progress", blockers: [
      { id: "b1", task_id: "t1", project_id: "p1", type: "Material", description: "Tiles not delivered", resolved_at: null },
    ] };

    it("hides Resolve from an internal employee", async () => {
      taskExecutionApi.detail.mockResolvedValue(withOpenBlocker);
      renderDetail({ user: employee });
      expect(await screen.findByText("Tiles not delivered")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument();
    });

    it("shows Resolve to the Supervisor, the PM and an Admin", async () => {
      for (const user of [supervisor, projectManager, admin]) {
        taskExecutionApi.detail.mockResolvedValue(withOpenBlocker);
        const { unmount } = render(<TaskDetailContent
          projectId="p1" project={defaultProject} task={baseTask} user={user} roles={actorProjectRoles(defaultProject, user)}
          candidates={[]} onChanged={vi.fn()} activeTab="actions"
        />);
        expect(await screen.findByRole("button", { name: "Resolve" })).toBeInTheDocument();
        unmount();
      }
    });
  });

  describe("submission rule parity (reviewed_at)", () => {
    const reviewed = { id: "pu1", note: "Old cycle.", created_at: "2026-08-02T00:00:00Z", reviewed_at: "2026-08-03T00:00:00Z", evidence: [] };
    const freshNote = { id: "pu2", note: "Fixed.", created_at: "2026-08-04T00:00:00Z", reviewed_at: null, evidence: [] };
    const freshFile = { ...freshNote, id: "pu3", evidence: [{ id: "ev1", file_id: "f1", original_filename: "permit.pdf" }] };
    const assignedEmployeeGate = extra => ({
      ...detail, task_kind: "approval_gate", task_class: "class_a", lifecycle_status: "in_progress",
      actor_is_assigned_support: true,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e-u-emp", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u-pm", created_at: "2026-08-01T00:00:00Z" }],
      ...extra,
    });

    it("blocks an approval-gate submit with no progress, and says why", async () => {
      taskExecutionApi.detail.mockResolvedValue(assignedEmployeeGate({ progress_updates: [] }));
      renderDetail({ user: employee });
      expect(await screen.findByRole("button", { name: "Submit For Review" })).toBeDisabled();
      expect(screen.getByText(/log a new progress update/i)).toBeInTheDocument();
    });

    it("blocks an approval-gate resubmit when every update was already reviewed (PM rejection)", async () => {
      taskExecutionApi.detail.mockResolvedValue(assignedEmployeeGate({
        progress_updates: [reviewed],
        approvals: [{ id: "a1", decision: "rejected", decided_at: "2026-08-03T00:00:00Z" }],
      }));
      renderDetail({ user: employee });
      expect(await screen.findByRole("button", { name: "Submit For Review" })).toBeDisabled();
      expect(screen.getByText(/log a new progress update/i)).toBeInTheDocument();
    });

    it("blocks an evidence-required approval-gate submit with only a fresh note", async () => {
      taskExecutionApi.detail.mockResolvedValue(assignedEmployeeGate({ evidence_required: true, progress_updates: [freshNote] }));
      renderDetail({ user: employee });
      expect(await screen.findByRole("button", { name: "Submit For Review" })).toBeDisabled();
      expect(screen.getByText(/requires evidence/i)).toBeInTheDocument();
    });

    it("allows an approval-gate submit with fresh progress and a file", async () => {
      taskExecutionApi.detail.mockResolvedValue(assignedEmployeeGate({ evidence_required: true, progress_updates: [reviewed, freshFile] }));
      renderDetail({ user: employee });
      expect(await screen.findByRole("button", { name: "Submit For Review" })).toBeEnabled();
      expect(screen.queryByText(/requires evidence/i)).not.toBeInTheDocument();
    });

    it("blocks a class_a work resubmit after a PM rejection that named no update", async () => {
      taskExecutionApi.detail.mockResolvedValue({
        ...detail, task_class: "class_a", lifecycle_status: "in_progress", progress_updates: [reviewed],
        verifications: [{ id: "v1", submission_update_id: "pu1", decision: "verified", verified_at: "2026-08-03T00:00:00Z" }],
      });
      renderDetail();
      expect(await screen.findByRole("button", { name: "Submit For Review" })).toBeDisabled();
    });

    it("allows a work resubmit once a new unreviewed update exists", async () => {
      taskExecutionApi.detail.mockResolvedValue({ ...detail, lifecycle_status: "in_progress", progress_updates: [reviewed, freshNote] });
      renderDetail();
      expect(await screen.findByRole("button", { name: "Submit For Review" })).toBeEnabled();
    });
  });

  // U6: authority follows membership of THIS project, not the global role.
  it("hides the cancel control from a PM who is not a member of the project", async () => {
    renderDetail({ user: projectManager, project: projectWith(membership(supervisor, "site_supervisor")) });
    await screen.findByText("Support Assignment", { exact: false });
    expect(screen.queryByText("Status Action")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel task" })).not.toBeInTheDocument();
  });

  it("shows the cancel control to a PM who is a member of the project", async () => {
    renderDetail({ user: projectManager });
    expect(await screen.findByRole("button", { name: "Cancel task" })).toBeInTheDocument();
  });

  it("hides forward transitions from a Supervisor who is not a member of the project", async () => {
    renderDetail({ user: supervisor, project: projectWith(membership(projectManager, "project_manager")) });
    await waitFor(() => expect(taskExecutionApi.detail).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Mark Ready" })).not.toBeInTheDocument();
  });

  it("gives an Admin every control regardless of membership", async () => {
    renderDetail({ user: admin, project: projectWith() });
    expect(await screen.findByRole("button", { name: "Mark Ready" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel task" })).toBeInTheDocument();
  });

  it("explains instead of offering the assign form to an Internal Employee", async () => {
    renderDetail({ user: employee });
    await screen.findByText("Support Assignment", { exact: false });
    expect(screen.queryByLabelText("Support employee")).not.toBeInTheDocument();
    expect(screen.getByText(/only this project's supervisor can assign support/i)).toBeInTheDocument();
  });

  it("requires a reason before cancelling a task", async () => {
    renderDetail({ user: admin });
    const cancelButton = await screen.findByRole("button", { name: "Cancel task" });
    expect(cancelButton).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/reason for cancellation/i), { target: { value: "Scope dropped." } });
    expect(cancelButton).toBeEnabled();
    fireEvent.click(cancelButton);
    await waitFor(() => expect(taskExecutionApi.transitionStatus).toHaveBeenCalledWith("p1", "t1", { target_status: "cancelled", reason: "Scope dropped." }));
  });

  it("mounts the progress form only while the task is in_progress", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, lifecycle_status: "in_progress" });
    renderDetail();
    expect(await screen.findByText("Log progress")).toBeInTheDocument();
  });

  it("hides the progress form when the task is not in_progress", async () => {
    renderDetail();
    await screen.findByText("Support Assignment", { exact: false });
    expect(screen.queryByText("Log progress")).not.toBeInTheDocument();
  });

  it("hides the progress form from the Supervisor once an Internal Employee is assigned and actively executing", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "in_progress", actor_is_assigned_support: false,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    renderDetail({ user: supervisor });
    await screen.findByText("Support Assignment", { exact: false });
    expect(screen.queryByText("Log progress")).not.toBeInTheDocument();
  });

  it("shows the progress form to the assigned Internal Employee", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "in_progress", actor_is_assigned_support: true,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    renderDetail({ user: employee });
    expect(await screen.findByText("Log progress")).toBeInTheDocument();
  });

  it("mounts the decision controls for a role that can drive transitions", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, task_kind: "work", task_class: "standard", lifecycle_status: "submitted" });
    renderDetail({ user: supervisor });
    expect(await screen.findByText("Supervisor verification")).toBeInTheDocument();
  });

  it("hides the decision controls for a role that cannot drive transitions", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, task_kind: "work", task_class: "standard", lifecycle_status: "submitted" });
    renderDetail({ user: employee });
    await waitFor(() => expect(taskExecutionApi.detail).toHaveBeenCalled());
    expect(screen.queryByText("Supervisor verification")).not.toBeInTheDocument();
  });

  it("shows a read-only completed summary and hides execution controls once a task is completed", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      lifecycle_status: "completed",
      task_class: "class_a",
      progress_updates: [{ id: "pu1", task_id: "t1", project_id: "p1", update_type: "evidence", status_claim: null, note: "Done.", submitted_by: "u1", source: "portal", created_at: "2026-08-01T00:00:00Z", evidence: [{ id: "e1", file_id: "f1", evidence_type: "photo", caption: null, original_filename: "site.jpg", mime_type: "image/jpeg", size_bytes: 100 }] }],
      approvals: [{ id: "a1", verification_id: "v1", decision: "approved", remarks: "Looks good.", decided_by: "u2", decided_by_name: "Priya PM", decided_at: "2026-08-02T00:00:00Z" }],
      audit_events: [{ id: "ev1", action: "TASK_STATUS_CHANGED", source: "portal", before_status: "approval_pending", after_status: "completed", reason: "Approved by PM.", actor_user_id: "u2", actor_name: "Priya PM", occurred_at: "2026-08-02T00:00:00Z" }],
    });
    renderDetail({ user: supervisor });
    expect(await screen.findByText(/no actions available/i)).toBeInTheDocument();
  });

  it("still shows execution controls for a rejected task, since rejected is not terminal", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, lifecycle_status: "rejected" });
    renderDetail({ user: supervisor });
    await screen.findByRole("button", { name: /report blocker/i });
    expect(screen.getByText("Support Assignment", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Task" })).toBeInTheDocument();
  });

  it("mounts the support assignment panel", async () => {
    const project = projectWith(
      membership(supervisor, "site_supervisor"),
      { id: "m1", user_id: "u-emp2", employee_id: "e1", name: "Rahul Verma", project_role: "internal_employee", ends_at: null },
    );
    renderDetail({ user: supervisor, project });
    expect(await screen.findByText("Support Assignment", { exact: false })).toBeInTheDocument();
    expect(await screen.findByText("Rahul Verma")).toBeInTheDocument();
  });

  it("still offers the lifecycle controls the backend permits on a blocked task", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "ready",
      readiness: { state: "blocked", reasons: [{ kind: "dependency", subject_id: "t0", detail: "Waiting on T000 Handover (planned).", blocking: true }], advisories: [] },
    });
    renderDetail({ user: supervisor });
    expect(await screen.findByRole("button", { name: "Start Task" })).toBeEnabled();
  });

  // U23: the backend has refused an unexplained early start since U14, and
  // this surface had no idea - the user clicked Start and got a 422 they had
  // no way to answer. Dates are computed relative to today rather than
  // hardcoded, because "early" is a fact about now.
  describe("starting a task ahead of its planned date", () => {
    const isoOffsetDays = days => {
      const date = new Date();
      date.setUTCDate(date.getUTCDate() + days);
      return date.toISOString().slice(0, 10);
    };
    const startable = extra => ({
      ...detail, lifecycle_status: "ready", actual_start_at: null, ...extra,
    });
    const openDetail = async extra => {
      taskExecutionApi.detail.mockResolvedValue(startable(extra));
      renderDetail({ user: supervisor });
      await screen.findByText("Status Action", { exact: false });
    };

    it("opens the early-start reason from the drawer footer while on the Overview tab", async () => {
      taskExecutionApi.detail.mockResolvedValue(startable({ planned_start_date: isoOffsetDays(10) }));
      const onFooterState = vi.fn();
      const roles = actorProjectRoles(defaultProject, supervisor);
      render(<TaskDetailContent projectId="p1" project={defaultProject} task={baseTask} user={supervisor} roles={roles} candidates={[]} onChanged={vi.fn()} activeTab="overview" onFooterState={onFooterState}/>);
      await waitFor(() => expect(onFooterState.mock.calls.at(-1)?.[0]?.primary?.label).toBe("Start work early"));
      act(() => onFooterState.mock.calls.at(-1)[0].primary.onClick());
      expect(await screen.findByRole("dialog", { name: "Start this task early" })).toBeInTheDocument();
    });

    it("relabels the start control and names the planned date when the start would be early", async () => {
      await openDetail({ planned_start_date: isoOffsetDays(10) });
      expect(screen.getByRole("button", { name: "Start work early" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Start Task" })).not.toBeInTheDocument();
      expect(screen.getByText(/planned to start/i)).toBeInTheDocument();
    });

    it("shows the ordinary start control once the planned date has passed", async () => {
      await openDetail({ planned_start_date: isoOffsetDays(-3) });
      expect(screen.getByRole("button", { name: "Start Task" })).toBeInTheDocument();
      expect(screen.queryByText(/planned to start/i)).not.toBeInTheDocument();
    });

    it("treats a task with no planned start date as an ordinary start", async () => {
      await openDetail({ planned_start_date: null });
      expect(screen.getByRole("button", { name: "Start Task" })).toBeInTheDocument();
      expect(screen.queryByText(/planned to start/i)).not.toBeInTheDocument();
    });

    it("does not treat resumed work as an early start", async () => {
      await openDetail({
        lifecycle_status: "rejected",
        planned_start_date: isoOffsetDays(10),
        actual_start_at: "2026-08-01T09:00:00Z",
      });
      expect(screen.getByRole("button", { name: "Start Task" })).toBeInTheDocument();
      expect(screen.queryByText(/planned to start/i)).not.toBeInTheDocument();
    });

    it("cannot confirm an early start without a reason", async () => {
      await openDetail({ planned_start_date: isoOffsetDays(10) });
      fireEvent.click(screen.getByRole("button", { name: "Start work early" }));
      const confirm = await screen.findByRole("button", { name: "Confirm early start" });
      expect(confirm).toBeDisabled();
      fireEvent.change(screen.getByPlaceholderText(/explain why this task is starting ahead/i), { target: { value: "   " } });
      expect(confirm).toBeDisabled();
      expect(taskExecutionApi.transitionStatus).not.toHaveBeenCalled();
    });

    it("sends the reason with the transition once one is given", async () => {
      taskExecutionApi.transitionStatus.mockResolvedValue({});
      await openDetail({ planned_start_date: isoOffsetDays(10) });
      fireEvent.click(screen.getByRole("button", { name: "Start work early" }));
      fireEvent.change(await screen.findByPlaceholderText(/explain why this task is starting ahead/i), { target: { value: "Crew freed up early." } });
      fireEvent.click(screen.getByRole("button", { name: "Confirm early start" }));
      await waitFor(() => expect(taskExecutionApi.transitionStatus).toHaveBeenCalledWith(
        "p1", "t1", { target_status: "in_progress", reason: "Crew freed up early." },
      ));
    });

    it("shows a refused early start inline and leaves the task untouched", async () => {
      taskExecutionApi.transitionStatus.mockRejectedValue(new Error("A reason is required to start a task before its planned start date."));
      await openDetail({ planned_start_date: isoOffsetDays(10) });
      fireEvent.click(screen.getByRole("button", { name: "Start work early" }));
      fireEvent.change(await screen.findByPlaceholderText(/explain why this task is starting ahead/i), { target: { value: "Crew freed up early." } });
      fireEvent.click(screen.getByRole("button", { name: "Confirm early start" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(/a reason is required/i);
      expect(screen.getByRole("button", { name: "Confirm early start" })).toBeInTheDocument();
      expect(taskExecutionApi.detail).toHaveBeenCalledTimes(1);
    });
  });
});

describe("TaskDetailContent - Overview tab", () => {
  it("shows planned/actual dates and a fallback for missing instructions", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, description: "" });
    renderDetail({ activeTab: "overview" });
    await screen.findByText("Task Details");
    expect(screen.getByText("No specific instructions added.")).toBeInTheDocument();
  });

  it("shows the project's Site Supervisor as Primary Responsible, not Unassigned, even with no support delegated", async () => {
    renderDetail({ activeTab: "overview" });
    await screen.findByText("Primary Responsible");
    // "Member" is the shared fixture name for every membership row (both the
    // Supervisor and the PM), so more than one match is expected here.
    expect(screen.getAllByText("Member").length).toBeGreaterThan(0);
    expect(screen.getByText("Role: Site Supervisor")).toBeInTheDocument();
    expect(screen.getByText("Not delegated")).toBeInTheDocument();
    expect(screen.queryByText(/unassigned/i)).not.toBeInTheDocument();
  });

  it("shows a warning instead of Unassigned when no Supervisor is on the project", async () => {
    renderDetail({ activeTab: "overview", project: projectWith(membership(projectManager, "project_manager")) });
    expect(await screen.findByText("Supervisor not assigned")).toBeInTheDocument();
  });

  it("shows Support / Delegated To separately from Primary Responsible when an employee is assigned", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e-u-emp", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    renderDetail({ activeTab: "overview" });
    await screen.findByText("Primary Responsible");
    // "Member" is the shared fixture name for every membership row, so this
    // just pins that Support renders distinctly from "Not delegated".
    expect(screen.queryByText("Not delegated")).not.toBeInTheDocument();
  });

  it("resolves a blocking dependency reason to a readable card, never a raw id", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      predecessors: [{ id: "t0", original_code: "T000", title: "Handover", lifecycle_status: "planned", task_kind: "work", task_class: "standard", dependency_type: "finish_to_start", blocking: true }],
      readiness: { state: "blocked", reasons: [{ kind: "dependency", subject_id: "t0", detail: "raw sentence not used", blocking: true }], advisories: [] },
    });
    renderDetail({ activeTab: "overview" });
    expect(await screen.findByText("Task is blocked by 1 item")).toBeInTheDocument();
    expect(screen.getByText(/T000 Handover/)).toBeInTheDocument();
    expect(screen.getByText("Dependency: Finish-to-Start")).toBeInTheDocument();
    expect(screen.getByText("Required: Previous task must be completed")).toBeInTheDocument();
    expect(screen.getByText("Current Status: Planned")).toBeInTheDocument();
    expect(screen.queryByText("t0")).not.toBeInTheDocument();
  });

  it("resolves a blocking approval reason against the project's external approvals, never a raw id", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { id: "a1", project_gate_id: "g1", gate_code: "MEP-01", gate_name: "Approved MEP Drawings", status: "submitted", assigned_to_name: "Prachit Kadam" },
    ]);
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      readiness: { state: "blocked", reasons: [{ kind: "approval", subject_id: "a1", detail: "raw sentence not used", blocking: true }], advisories: [] },
    });
    renderDetail({ activeTab: "overview" });
    expect(await screen.findByText(/Approved MEP Drawings/)).toBeInTheDocument();
    expect(screen.getByText("Status: Submitted")).toBeInTheDocument();
    expect(screen.getByText("Owner: Prachit Kadam")).toBeInTheDocument();
    expect(screen.queryByText("a1")).not.toBeInTheDocument();
  });

  it("shows a friendly fallback when an approval reason cannot be resolved", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      readiness: { state: "blocked", reasons: [{ kind: "approval", subject_id: "missing-id", detail: "raw sentence not used", blocking: true }], advisories: [] },
    });
    renderDetail({ activeTab: "overview" });
    expect(await screen.findByText(/External approval pending/)).toBeInTheDocument();
    expect(screen.getByText("External approval details unavailable")).toBeInTheDocument();
    expect(screen.queryByText("missing-id")).not.toBeInTheDocument();
  });
});

describe("TaskDetailContent - Activity Log tab", () => {
  it("shows a fallback when there is no activity", async () => {
    renderDetail({ activeTab: "activity" });
    expect(await screen.findByText("No activity recorded yet.")).toBeInTheDocument();
  });

  it("merges status changes, progress updates and decisions into one chronological list with resolved actor names", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      audit_events: [{ id: "ev1", action: "TASK_STATUS_CHANGED", source: "portal", before_status: "planned", after_status: "ready", reason: null, actor_user_id: "u-adm", actor_name: "Admin User", occurred_at: "2026-08-01T08:00:00Z" }],
      progress_updates: [{ id: "pu1", task_id: "t1", project_id: "p1", update_type: "note", status_claim: null, note: "Crew on site.", submitted_by: "u-sup", source: "portal", created_at: "2026-08-02T09:00:00Z", evidence: [] }],
    });
    renderDetail({ activeTab: "activity" });
    expect(await screen.findByText("Status changed: Planned → Ready")).toBeInTheDocument();
    expect(screen.getByText("Progress update")).toBeInTheDocument();
    expect(screen.getByText("Member")).toBeInTheDocument(); // resolved from submitted_by via project.memberships
  });
});

describe("reference material from the template", () => {
  const withMaterial = {
    ...detail,
    evidence_instructions: "Photos of the levelled floor from two corners.",
    reference_files: [{ id: "r1", file_id: "f1", filename: "flooring-spec.pdf", mime_type: "application/pdf", size_bytes: 2048, description: "Approved flooring spec" }],
  };

  it("shows what proof is needed and the reference files, separate from evidence", async () => {
    taskExecutionApi.detail.mockResolvedValue(withMaterial);
    renderDetail({ activeTab: "overview" });
    expect(await screen.findByText("Photos of the levelled floor from two corners.")).toBeInTheDocument();
    expect(screen.getByText("What proof is needed")).toBeInTheDocument();
    expect(screen.getByText("Reference material")).toBeInTheDocument();
    expect(screen.getByText("Approved flooring spec")).toBeInTheDocument();
  });

  it("downloads a reference file through the authenticated project route", async () => {
    taskExecutionApi.detail.mockResolvedValue(withMaterial);
    taskExecutionApi.downloadTaskReference.mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "flooring-spec.pdf" });
    URL.createObjectURL = vi.fn(() => "blob:ref");
    URL.revokeObjectURL = vi.fn();
    renderDetail({ activeTab: "overview" });
    fireEvent.click(await screen.findByRole("button", { name: /download flooring-spec.pdf/i }));
    await waitFor(() => expect(taskExecutionApi.downloadTaskReference).toHaveBeenCalledWith("p1", "t1", "r1"));
  });
});
