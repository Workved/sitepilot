import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionCalendarView } from "./components/ExecutionCalendarView";
import { dayEvents, ganttSpan, groupByPhase, monthGrid, taskState, ticks } from "./components/calendar/calendarModel";
import { toGanttData } from "./components/calendar/ProjectGantt";
import { toPortfolioData } from "./components/calendar/PortfolioTimeline";
import { toCalendarEvents } from "./components/calendar/MonthCalendar";

vi.mock("../../api/projectsApi", () => ({ projectsApi: { detail: vi.fn(), timeline: vi.fn() } }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { list: vi.fn(), detail: vi.fn(), listExternalApprovals: vi.fn() } }));

const admin = { id: "u-adm", role: "admin" };
const day = iso => new Date(`${iso}T00:00:00Z`);
const todayIso = new Date().toISOString().slice(0, 10);
const shift = (iso, n) => new Date(day(iso).getTime() + n * 86400000).toISOString().slice(0, 10);

const task = (overrides = {}) => ({
  id: "t1", project_id: "p1", original_code: "T001", template_sequence: 1, title: "Pour slab",
  task_kind: "work", task_class: "standard", lifecycle_status: "planned", schedule_classification: "execution",
  planned_start_date: todayIso, planned_end_date: shift(todayIso, 2), phase: "Civil", category: "Structure",
  open_blocker_count: 0, readiness: { state: "ready", reasons: [], advisories: [] }, variance: null,
  predecessor_ids: [], vendor_name: null, added_after_start: false,
  ...overrides,
});

const tasks = [
  task(),
  task({ id: "t2", original_code: "T002", title: "Wiring", phase: "Electrical", lifecycle_status: "in_progress", actual_start_at: `${shift(todayIso, -3)}T09:00:00Z`, planned_start_date: shift(todayIso, -5), planned_end_date: shift(todayIso, -2), variance: { status: "late", variance_days: 2, days: 2 }, vendor_name: "Bright Electricals" }),
  task({ id: "t3", original_code: "T003", title: "Ceiling grid", phase: "Electrical", predecessor_ids: ["t2"], planned_start_date: shift(todayIso, 120), planned_end_date: shift(todayIso, 125) }),
  task({ id: "t4", original_code: "P001", title: "Site survey", phase: null, planned_start_date: null, planned_end_date: null, schedule_classification: "pre_activation" }),
];

beforeEach(() => {
  vi.clearAllMocks();
  try { window.localStorage.clear(); } catch { /* ignore */ }
  projectsApi.detail.mockResolvedValue({ id: "p1", memberships: [], start_date: shift(todayIso, -10), target_handover_date: shift(todayIso, 30) });
  taskExecutionApi.list.mockResolvedValue(tasks);
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

describe("calendar model", () => {
  const today = day("2026-11-18");

  it("names each task's state, with days late from the variance", () => {
    expect(taskState(task({ lifecycle_status: "completed" }), today).label).toBe("Completed");
    expect(taskState(task({ readiness: { state: "blocked" } }), today)).toMatchObject({ tone: "blocked", label: "Blocked", blocked: true });
    expect(taskState(task({ lifecycle_status: "in_progress", variance: { status: "late", variance_days: 3 } }), today)).toMatchObject({ label: "In progress", late: 3 });
    expect(taskState(task({ lifecycle_status: "submitted" }), today).label).toBe("Needs review");
  });

  it("spans the tasks, today and the project dates with padding", () => {
    const span = ganttSpan([task({ planned_start_date: "2026-11-20", planned_end_date: "2026-11-22" })], today, { start_date: "2026-11-01", target_handover_date: "2026-12-15" });
    expect(span.start.toISOString().slice(0, 10)).toBe("2026-10-29");
    expect(span.end.toISOString().slice(0, 10)).toBe("2026-12-22");
  });

  it("labels Mondays at week zoom and months at month zoom", () => {
    const span = { start: day("2026-11-16"), days: 20 };
    expect(ticks(span, "week").map(t => t.label)).toEqual(["16 Nov", "23 Nov", "30 Nov"]);
    expect(ticks(span, "month").map(t => t.label)).toEqual(["Nov 2026", "Dec 2026"]);
    // A span starting late in a month doesn't label that month (it would
    // overlap the next one).
    expect(ticks({ start: day("2026-10-27"), days: 40 }, "month").map(t => t.label)).toEqual(["Nov 2026", "Dec 2026"]);
  });

  it("groups by phase with a percent done", () => {
    const groups = groupByPhase([task({ phase: "A", lifecycle_status: "completed" }), task({ id: "x", phase: "A" }), task({ id: "y", phase: "B" })]);
    expect(groups.map(g => [g.phase, g.tasks.length, g.pct])).toEqual([["A", 2, 50], ["B", 1, 0]]);
  });

  it("lists starts, dues, finishes and (today only) late work for a day", () => {
    const list = [
      task({ id: "a", title: "Starts", planned_start_date: "2026-11-18", planned_end_date: "2026-11-20" }),
      task({ id: "b", title: "Due", planned_start_date: "2026-11-10", planned_end_date: "2026-11-18" }),
      task({ id: "c", title: "Late", lifecycle_status: "in_progress", planned_start_date: "2026-11-01", planned_end_date: "2026-11-10", variance: { status: "late", variance_days: 8 } }),
    ];
    expect(dayEvents(list, today, today, [{ date: "2026-11-18", label: "Handover" }]).map(e => e.kind)).toEqual(["late", "due", "start", "milestone"]);
    expect(monthGrid(today)[0].toISOString().slice(0, 10)).toBe("2026-10-26");
  });
});

describe("library data", () => {
  const today = new Date(2026, 10, 18);

  it("turns tasks into SVAR rows: key dates, phase summaries, task bars and links", () => {
    const { rows, links } = toGanttData(tasks, today);
    expect(rows.some(r => r.isKey)).toBe(false);
    expect(rows.filter(r => r.isPhase).map(r => [r.text, r.count])).toEqual([["Civil", 1], ["Electrical", 2]]);
    const wiring = rows.find(r => r.id === "t2");
    expect(wiring).toMatchObject({ parent: "phase:Electrical", tone: "active", late: 2, code: "T002" });
    // Exclusive end: a task planned to the 3rd ends at the start of the 4th.
    expect(wiring.end - wiring.start).toBe(4 * 86400000);
    expect(links).toEqual([{ id: "t2>t3", source: "t2", target: "t3", type: "e2s" }]);
    expect(rows.find(r => r.id === "t4")).toBeUndefined();
  });

  it("turns projects into portfolio rows with the late share and approval milestones", () => {
    const rows = toPortfolioData([{ project_id: "p1", name: "HQ", status: "active", start_date: "2026-11-01", target_handover_date: "2026-11-30", forecast_finish_date: "2026-12-10", progress_pct: 40, days_late: 10, health: "delayed", approvals: [{ name: "Fire NOC", due_date: "2026-11-20", status: "assigned" }] }], today);
    const project = rows.find(r => r.id === "p1");
    expect(project.end.getDate()).toBe(11);
    expect(project.lateShare).toBe(25);
    expect(rows.find(r => r.isApproval)).toMatchObject({ parent: "p1", text: "Fire NOC" });
  });

  it("turns tasks into calendar events coloured by state, plus milestones", () => {
    const events = toCalendarEvents(tasks, { start_date: "2026-11-01", target_handover_date: "2026-12-20" }, today);
    expect(events.find(e => e.id === "t2")).toMatchObject({ title: "Wiring · 2d late", backgroundColor: "#fff1f2", borderColor: "#f43f5e" });
    expect(events.find(e => e.id === "t1").borderColor).toBe("#94a3b8");
    expect(events.filter(e => String(e.id).startsWith("key:")).map(e => e.title)).toEqual(["⚑ Project start", "⚑ Handover"]);
  });
});

describe("ExecutionCalendarView", () => {
  it("shows the Gantt by default with phases, key dates, late work and links", async () => {
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    const wiring = await screen.findByTestId("gantt-row-T002");
    expect(screen.getByRole("tab", { name: /gantt/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("gantt-row-phase:Electrical")).toHaveTextContent("2 tasks");
    expect(screen.queryByTestId("gantt-row-key:today")).toBeNull();
    expect(screen.getByText(/Today ·/)).toBeInTheDocument();
    expect(within(wiring).getByText("In progress · 2d late")).toBeInTheDocument();
    expect(within(wiring).getByText("+2d")).toBeInTheDocument();
    expect(screen.getByTestId("gantt-stub")).toHaveAttribute("data-links", "1");
  });

  it("puts undated tasks in a collapsed pre-activation checklist", async () => {
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    const toggle = await screen.findByRole("button", { name: /pre-activation checklist/i });
    expect(screen.queryByText("Site survey")).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByText("Site survey")).toBeInTheDocument();
  });

  it("filters by search, status chip and vendor, and resets", async () => {
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByTestId("gantt-row-T001");
    fireEvent.change(screen.getByPlaceholderText(/search code/i), { target: { value: "wiring" } });
    expect(screen.queryByTestId("gantt-row-T001")).toBeNull();
    expect(screen.getByTestId("gantt-row-T002")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /reset/i }));
    fireEvent.click(within(screen.getByRole("group", { name: /execution summary/i })).getByRole("button", { name: /delayed/i }));
    expect(screen.queryByTestId("gantt-row-T001")).toBeNull();
    expect(screen.getByTestId("gantt-row-T002")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /reset/i }));
    fireEvent.change(screen.getByLabelText("Vendor"), { target: { value: "Bright Electricals" } });
    expect(screen.queryByTestId("gantt-row-T001")).toBeNull();
  });

  it("opens the task drawer when a task is clicked, but not for a phase", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...tasks[0], audit_trail: [], predecessors: [], progress_updates: [], blockers: [], delays: [], support_assignments: [], verifications: [], approvals: [] });
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    fireEvent.click(await screen.findByTestId("gantt-row-phase:Civil"));
    expect(taskExecutionApi.detail).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("gantt-row-T001"));
    await waitFor(() => expect(taskExecutionApi.detail).toHaveBeenCalledWith("p1", "t1"));
  });

  it("offers Day to Year zoom, Week by default", async () => {
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByTestId("gantt-row-T001");
    const zoom = screen.getByRole("group", { name: "Zoom" });
    expect(within(zoom).getAllByRole("button").map(b => b.textContent)).toEqual(["Day", "Week", "Month", "Quarter", "Year"]);
    expect(within(zoom).getByRole("button", { name: "Week" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switches to the month calendar and opens a task from it", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...tasks[0], audit_trail: [], predecessors: [], progress_updates: [], blockers: [], delays: [], support_assignments: [], verifications: [], approvals: [] });
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByTestId("gantt-row-T001");
    fireEvent.click(screen.getByRole("tab", { name: /month/i }));
    expect(await screen.findByRole("button", { name: "Wiring · 2d late" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "⚑ Handover" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /today/i, hidden: false })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Pour slab" }));
    await waitFor(() => expect(taskExecutionApi.detail).toHaveBeenCalledWith("p1", "t1"));
  });

  it("shows the portfolio and opens a running project's Gantt", async () => {
    projectsApi.timeline.mockResolvedValue([
      { project_id: "p1", code: "PRJ-1", name: "Head Office", status: "active", start_date: shift(todayIso, -10), target_handover_date: shift(todayIso, 30), forecast_finish_date: shift(todayIso, 40), pm_name: "Piyush", progress_pct: 40, completed_count: 2, task_count: 5, days_late: 10, health: "delayed", approvals: [{ name: "Fire NOC", due_date: shift(todayIso, 5), status: "assigned", overdue: false }] },
      { project_id: "p2", code: "PRJ-2", name: "Lobby", status: "draft", start_date: shift(todayIso, 20), target_handover_date: shift(todayIso, 60), forecast_finish_date: null, pm_name: null, progress_pct: 0, completed_count: 0, task_count: 0, days_late: 0, health: "on_track", approvals: [] },
    ]);
    const onSelectProject = vi.fn();
    render(<ExecutionCalendarView projectId="p1" user={admin} onSelectProject={onSelectProject}/>);
    await screen.findByTestId("gantt-row-T001");
    fireEvent.click(screen.getByRole("tab", { name: /portfolio/i }));
    const row = await screen.findByTestId("gantt-row-p1");
    expect(within(row).getByText("10d late")).toBeInTheDocument();
    expect(within(row).getByText("Head Office · 40%")).toBeInTheDocument();
    expect(screen.getByText("1 delayed")).toBeInTheDocument();
    expect(within(screen.getByTestId("gantt-row-p2")).getByText("Lobby · not started")).toBeInTheDocument();
    expect(screen.getByTestId("gantt-row-p1:a0")).toHaveTextContent("Fire NOC");
    fireEvent.click(screen.getByTestId("gantt-row-p2"));
    expect(onSelectProject).not.toHaveBeenCalled();
    fireEvent.click(row);
    expect(onSelectProject).toHaveBeenCalledWith("p1");
    expect(screen.getByRole("tab", { name: /gantt/i })).toHaveAttribute("aria-selected", "true");
  });

  it("shows an empty state when the project has no tasks", async () => {
    taskExecutionApi.list.mockResolvedValue([]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    expect(await screen.findByText("No execution tasks yet")).toBeInTheDocument();
  });
});
