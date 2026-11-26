import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { targetsApi } from "../../api/targetsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { toGanttData } from "./components/calendar/ProjectGantt";
import { localDay } from "./components/calendar/svarSetup";
import { targetSummary } from "./components/calendar/TargetsPanel";
import { TaskScheduleCard } from "./components/TaskScheduleCard";

vi.mock("../../api/targetsApi", () => ({ targetsApi: { create: vi.fn(), clear: vi.fn(), list: vi.fn(), scheduleChanges: vi.fn() } }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { reschedule: vi.fn() } }));

const today = localDay("2026-11-26");
const task = overrides => ({ id: "t1", original_code: "T001", title: "Wiring", phase: "Electrical", lifecycle_status: "in_progress",
  planned_start_date: "2026-11-20", planned_end_date: "2026-11-30", actual_start_at: "2026-11-18T09:00:00Z", predecessor_ids: [], ...overrides });
const target = overrides => ({ id: "g1", kind: "task", task_id: "t1", status: "active", target_date: "2026-11-28", note: "Client visit",
  outcome: { state: "due_soon", days: 2 }, created_by_name: "Priya PM", can_manage: true, linked_tasks: [], ...overrides });

beforeEach(() => vi.clearAllMocks());

describe("Gantt data", () => {
  it("spans a row over plan, actual, original plan and target", () => {
    const { rows } = toGanttData([task()], today, {
      changes: [{ task_id: "t1", original_start: "2026-11-15", original_end: "2026-11-25", times_moved: 1, last_reason: "Material late" }],
      targets: [target({ target_date: "2026-12-02" })],
    });
    const row = rows.find(item => item.id === "t1");
    expect(row.start).toEqual(localDay("2026-11-15"));
    expect(row.end).toEqual(localDay("2026-12-03"));
    expect(row.schedule.tags.map(tag => tag.text)).toEqual(["Started 2 days early", "Moved +5d"]);
    expect(row.change.last_reason).toBe("Material late");
  });

  it("adds a project row and project target rows on top", () => {
    const { rows } = toGanttData([task()], today, {
      project: { name: "Tower A", start_date: "2026-11-20", target_handover_date: "2027-01-10", activated_at: "2026-11-18T00:00:00Z", status: "active" },
      targets: [target({ id: "p1", kind: "project", task_id: null, title: "Client walkthrough", target_date: "2026-12-12", outcome: { state: "open", days: 16 } })],
    });
    expect(rows[0]).toMatchObject({ id: "project", isProject: true });
    expect(rows[0].schedule.tags[0].text).toBe("Started 2 days early");
    expect(rows[1]).toMatchObject({ id: "target:p1", isTarget: true, text: "Client walkthrough" });
  });

  it("summarises targets for the toolbar", () => {
    const targets = [target(), target({ id: "g2", target_date: "2026-11-20", outcome: { state: "missed", days: 6 } }), target({ id: "g3", status: "replaced" })];
    expect(targetSummary(targets, today)).toEqual({ active: 2, missed: 1, thisWeek: 1 });
  });
});

describe("Task schedule card", () => {
  const supervisor = { id: "u-sup", role: "supervisor" };
  const detail = task();

  it("shows the active target and sets a new one", async () => {
    const onChanged = vi.fn();
    targetsApi.create.mockResolvedValue({});
    render(<TaskScheduleCard projectId="p1" detail={detail} user={supervisor} roles={["site_supervisor"]} targets={[target()]} onChanged={onChanged}/>);
    expect(screen.getByText("Target 28 Nov · 2 days left")).toBeInTheDocument();
    expect(screen.getByText("Client visit")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change target" }));
    fireEvent.change(screen.getByLabelText("Finish by"), { target: { value: "2026-11-29" } });
    fireEvent.click(screen.getByRole("button", { name: "Save target" }));
    await waitFor(() => expect(targetsApi.create).toHaveBeenCalledWith("p1", { kind: "task", task_id: "t1", target_date: "2026-11-29", note: null }));
    expect(onChanged).toHaveBeenCalled();
  });

  it("changes planned dates only with a reason, and only for leads", async () => {
    taskExecutionApi.reschedule.mockResolvedValue({});
    const { unmount } = render(<TaskScheduleCard projectId="p1" detail={detail} user={supervisor} roles={["site_supervisor"]} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: /Change planned dates/ }));
    fireEvent.change(screen.getByLabelText("New end"), { target: { value: "2026-12-04" } });
    fireEvent.change(screen.getByLabelText("Why the dates are changing"), { target: { value: "Tiles delivered late" } });
    fireEvent.click(screen.getByRole("button", { name: "Change dates" }));
    await waitFor(() => expect(taskExecutionApi.reschedule).toHaveBeenCalledWith("p1", "t1", { new_planned_start_date: "2026-11-20", new_planned_end_date: "2026-12-04", reason: "Tiles delivered late" }));
    unmount();
    render(<TaskScheduleCard projectId="p1" detail={detail} user={{ id: "u-emp", role: "internal_employee" }} roles={["internal_employee"]} onChanged={vi.fn()}/>);
    expect(screen.queryByRole("button", { name: /Change planned dates/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Set target/ })).toBeInTheDocument();
  });

  it("shows the original plan for a moved task", () => {
    render(<TaskScheduleCard projectId="p1" detail={detail} user={supervisor} roles={["site_supervisor"]}
      change={{ original_start: "2026-11-15", original_end: "2026-11-25", times_moved: 2, last_by: "Priya PM", last_reason: "Client change" }} onChanged={vi.fn()}/>);
    expect(screen.getByText("Moved 2 times")).toBeInTheDocument();
    expect(screen.getByText("Last by Priya PM: Client change")).toBeInTheDocument();
  });
});
