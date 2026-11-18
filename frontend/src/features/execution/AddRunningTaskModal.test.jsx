import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { AddRunningTaskModal } from "./components/AddRunningTaskModal";
import { canAddTasks, canAddToTemplate, templateOutcome } from "../projects/components/TaskScope";

vi.mock("../../api/projectsApi", () => ({ projectsApi: { addRunningTask: vi.fn() } }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { list: vi.fn() } }));

const project = { id: "p1", start_date: "2026-08-01" };
const tasks = [
  { id: "t1", original_code: "T001", title: "Wiring", phase: "Electrical", category: "Wiring and conduits", lifecycle_status: "in_progress" },
  { id: "t2", original_code: "T002", title: "Old", phase: "Electrical", category: "Lights", lifecycle_status: "cancelled" },
];

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.list.mockResolvedValue(tasks);
});

async function fill() {
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Lobby patch" } });
  await screen.findByRole("option", { name: "Electrical" });
  fireEvent.change(screen.getByLabelText("Phase"), { target: { value: "Electrical" } });
  fireEvent.change(screen.getByLabelText("Category"), { target: { value: "Wiring and conduits" } });
  fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-05" } });
  fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-08-07" } });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Client asked" } });
}

describe("who can add tasks", () => {
  it("admins, PMs and supervisors add; only admins add to the template", () => {
    for (const role of ["super_admin", "admin", "project_manager", "supervisor"]) expect(canAddTasks({ role })).toBe(true);
    expect(canAddTasks({ role: "internal_employee" })).toBe(false);
    expect(canAddToTemplate({ role: "admin" })).toBe(true);
    expect(canAddToTemplate({ role: "project_manager" })).toBe(false);
    expect(canAddToTemplate({ role: "supervisor" })).toBe(false);
  });

  it("explains a template step that didn't go through", () => {
    expect(templateOutcome({ added: true, task_code: "T002", version_no: 2 }).text).toMatch(/T002 - version 2 is now published/);
    const failed = templateOutcome({ added: false, error: "Validation failed", draft_version_no: 3 });
    expect(failed.ok).toBe(false);
    expect(failed.text).toMatch(/not to the template: Validation failed.*version 3/);
  });
});

describe("AddRunningTaskModal", () => {
  it("adds a task to this project only, with the project's own phases and a start-after task", async () => {
    projectsApi.addRunningTask.mockResolvedValue({ code: "MANUAL-001", title: "Lobby patch", planned_start_date: "2026-08-05", planned_end_date: "2026-08-07", template: null });
    const onAdded = vi.fn();
    render(<AddRunningTaskModal projectId="p1" project={project} user={{ role: "supervisor" }} onClose={vi.fn()} onAdded={onAdded}/>);
    await fill();
    expect(screen.queryByRole("option", { name: /T002/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("Starts after (optional)"), { target: { value: "t1" } });
    expect(screen.getByRole("radio", { name: /This project and the template/ })).toBeDisabled();
    expect(screen.getByText("Only an Admin can change the template.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(projectsApi.addRunningTask).toHaveBeenCalledWith("p1", {
      title: "Lobby patch", description: null, phase: "Electrical", category: "Wiring and conduits",
      planned_start_date: "2026-08-05", planned_end_date: "2026-08-07", evidence_required: false,
      after_task_id: "t1", reason: "Client asked", add_to_template: false,
    }));
    expect(await screen.findByText(/MANUAL-001 · Lobby patch was added/)).toBeInTheDocument();
    expect(onAdded).toHaveBeenCalled();
  });

  it("lets an admin add it to the template too and shows the new version", async () => {
    projectsApi.addRunningTask.mockResolvedValue({ code: "MANUAL-001", title: "Lobby patch", planned_start_date: "2026-08-05", planned_end_date: "2026-08-07", template: { added: true, task_code: "T014", version_no: 3 } });
    render(<AddRunningTaskModal projectId="p1" project={project} user={{ role: "admin" }} onClose={vi.fn()}/>);
    await fill();
    fireEvent.click(screen.getByRole("radio", { name: /This project and the template/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(projectsApi.addRunningTask.mock.calls[0][1].add_to_template).toBe(true));
    expect(await screen.findByText(/T014 - version 3 is now published/)).toBeInTheDocument();
  });

  it("won't start before the project or end before it starts", async () => {
    render(<AddRunningTaskModal projectId="p1" project={project} user={{ role: "admin" }} onClose={vi.fn()}/>);
    await fill();
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-07-20" } });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    expect(screen.getByText(/Can't start before the project/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    expect(screen.getByText("Must be on or after the start date.")).toBeInTheDocument();
    expect(projectsApi.addRunningTask).not.toHaveBeenCalled();
  });
});
