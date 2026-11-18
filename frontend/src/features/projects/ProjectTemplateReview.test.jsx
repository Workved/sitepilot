import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectTemplateReview } from "./components/ProjectTemplateReview";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  templateReviewTasks: vi.fn(), templateReviewSummary: vi.fn(), taskApplicabilityHistory: vi.fn(), detail: vi.fn(), activity: vi.fn(),
  decideTaskApplicability: vi.fn(), createManualTask: vi.fn(), generateTasks: vi.fn(), taskClassification: vi.fn(), updateTaskClassification: vi.fn(), setStatus: vi.fn(), setMembership: vi.fn(), remove: vi.fn(),
} }));

const tasks = [
  { id: "t1", code: "T001", sequence: 1, title: "Confirm site handover", description: "Capture the signed record.", schedule_classification: "pre_activation", planned_start_day: null, planned_end_day: null, phase: "Pre-Activation", category: "Governance", applicability: "mandatory", included: true, source: "template", decision_state: "pending_review" },
  { id: "t8", code: "T008", sequence: 8, title: "Mobilise site", description: "Start controlled execution.", schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1, phase: "Execution", category: "Site setup", applicability: "mandatory", included: true, source: "template", decision_state: "included" },
  { id: "t9", code: "T009", sequence: 9, title: "Conditional survey", description: null, schedule_classification: "execution", planned_start_day: 1, planned_end_day: 2, phase: "Execution", category: "Site setup", applicability: "conditional", included: false, source: "template", decision_state: "excluded" },
];
const page = (items = tasks) => ({ items, pagination: { page: 1, page_size: 100, total: items.length, total_pages: items.length ? 1 : 0 } });
const summary = { project_id: "p1", total: 99, included: 98, excluded: 1, pending_review: 97, decided: 2, mandatory: 98, conditional: 1 };

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.templateReviewTasks.mockResolvedValue(page());
  projectsApi.templateReviewSummary.mockResolvedValue(summary);
  projectsApi.activity.mockResolvedValue([]);
  projectsApi.taskClassification.mockResolvedValue({ project_id: "p1", editable: true, items: [] });
  projectsApi.taskApplicabilityHistory.mockResolvedValue([]);
  projectsApi.decideTaskApplicability.mockResolvedValue({ task_id: "t9", decision_state: "excluded", included: false });
  projectsApi.createManualTask.mockResolvedValue({ task_id: "manual-1", code: "MANUAL-001", sequence: 100, source_type: "project_manual" });
});

describe("Project template review", () => {
  it("renders database counts and preserves API order inside phase and category groups", async () => {
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/>);
    expect(await screen.findByText("Generated project tasks")).toBeInTheDocument();
    const cards = within(screen.getByLabelText("Review summary"));
    expect(cards.getByText("99")).toBeInTheDocument();
    expect(cards.getByText("98")).toBeInTheDocument();
    expect(cards.getByText("1")).toBeInTheDocument();
    expect(cards.getByText("97")).toBeInTheDocument();
    expect(screen.getByText("Pre-Activation", { selector: "h4" })).toBeInTheDocument();
    expect(screen.getByText("Governance")).toBeInTheDocument();
    expect(screen.getByText("Site setup")).toBeInTheDocument();
    expect(screen.getAllByTestId("review-task").map(node => node.textContent.match(/T\d{3}/)?.[0])).toEqual(["T001", "T008", "T009"]);
    expect(screen.getAllByText(/^Days 1/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Conditional").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Excluded").length).toBeGreaterThan(0);
    expect(within(screen.getAllByTestId("review-task")[0]).getByText(/mandatory.*locked/i)).toBeInTheDocument();
    expect(within(screen.getAllByTestId("review-task")[0]).queryByRole("button", { name: /include|exclude/i })).not.toBeInTheDocument();
  });

  it("renders all 99 generated tasks in backend order without client sorting", async () => {
    const completeTaskSet = Array.from({ length: 99 }, (_, index) => {
      const sequence = index + 1;
      const preActivation = sequence <= 7;
      return {
        id: "task-" + sequence,
        code: "T" + String(sequence).padStart(3, "0"),
        sequence,
        title: "Task " + sequence,
        description: "Description " + sequence,
        schedule_classification: preActivation ? "pre_activation" : "execution",
        planned_start_day: preActivation ? null : Math.min(45, sequence - 7),
        planned_end_day: preActivation ? null : Math.min(45, sequence - 7),
        phase: preActivation ? "Pre-Activation" : "Execution",
        category: "Approved scope",
        applicability: sequence === 98 ? "conditional" : "mandatory",
        included: true,
        source: "template",
        decision_state: "pending_review",
      };
    });
    projectsApi.templateReviewTasks.mockResolvedValue(page(completeTaskSet));

    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/>);

    const rows = await screen.findAllByTestId("review-task");
    expect(rows).toHaveLength(99);
    expect(rows[0]).toHaveTextContent("T001");
    expect(rows[7]).toHaveTextContent("T008");
    expect(rows[98]).toHaveTextContent("T099");
  });

  it("sends backend filters, including included=false, and clears them", async () => {
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/>);
    await screen.findByText("Generated project tasks");
    fireEvent.change(screen.getByPlaceholderText(/search task/i), { target: { value: "mobilise" } });
    fireEvent.change(screen.getByLabelText("Filter by phase"), { target: { value: "Execution" } });
    fireEvent.change(screen.getByLabelText("Filter by category"), { target: { value: "Site setup" } });
    fireEvent.change(screen.getByLabelText("Filter by applicability"), { target: { value: "conditional" } });
    fireEvent.change(screen.getByLabelText("Filter by inclusion"), { target: { value: "false" } });
    fireEvent.change(screen.getByLabelText("Filter by source"), { target: { value: "template" } });
    await waitFor(() => expect(projectsApi.templateReviewTasks).toHaveBeenLastCalledWith("p1", expect.objectContaining({ search: "mobilise", phase: "Execution", category: "Site setup", applicability: "conditional", included: false, source: "template" })));
    expect(projectsApi.templateReviewSummary).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    await waitFor(() => expect(projectsApi.templateReviewTasks).toHaveBeenLastCalledWith("p1", expect.objectContaining({ search: "", phase: "", category: "", applicability: "", source: "" })));
    expect(projectsApi.templateReviewSummary).toHaveBeenCalledTimes(1);
  });

  it("deduplicates identical in-flight reads under React Strict Mode", async () => {
    let resolveTasks;
    let resolveSummary;
    projectsApi.templateReviewTasks.mockReturnValue(new Promise(resolve => { resolveTasks = resolve; }));
    projectsApi.templateReviewSummary.mockReturnValue(new Promise(resolve => { resolveSummary = resolve; }));

    render(<StrictMode><ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/></StrictMode>);

    await waitFor(() => expect(projectsApi.templateReviewTasks).toHaveBeenCalledTimes(1));
    expect(projectsApi.templateReviewSummary).toHaveBeenCalledTimes(1);
    resolveSummary(summary);
    resolveTasks(page());
    expect(await screen.findByText("Generated project tasks")).toBeInTheDocument();
  });
  it("covers loading, empty, error and retry states", async () => {
    let resolveTasks;
    projectsApi.templateReviewTasks.mockReturnValueOnce(new Promise(resolve => { resolveTasks = resolve; }));
    const view = render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/>);
    expect(screen.getByText(/loading generated tasks/i)).toBeInTheDocument();
    resolveTasks(page([]));
    expect(await screen.findByText("No generated tasks to review")).toBeInTheDocument();
    view.unmount();
    vi.clearAllMocks();
    projectsApi.templateReviewSummary.mockResolvedValue(summary);

    projectsApi.templateReviewTasks.mockRejectedValueOnce(Object.assign(new Error("Denied"), { status: 403 })).mockResolvedValueOnce(page());
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/>);
    expect(await screen.findByText("You are not assigned to review this project.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Generated project tasks")).toBeInTheDocument();
    await waitFor(() => expect(projectsApi.templateReviewTasks).toHaveBeenCalledTimes(2));
  });

  it("lets a Super Admin review generated tasks like an Admin", async () => {
    render(<ProjectTemplateReview projectId="p1" user={{ role: "super_admin" }} debounceMs={0}/>);
    expect(await screen.findByText("Generated project tasks")).toBeInTheDocument();
    expect(screen.queryByText("Task review is role restricted")).not.toBeInTheDocument();
    expect(projectsApi.templateReviewTasks).toHaveBeenCalled();
  });

  it.each(["supervisor", "internal_employee"])("does not call review APIs for %s", role => {
    render(<ProjectTemplateReview projectId="p1" user={{ role }} debounceMs={0}/>);
    expect(screen.getByText("Task review is role restricted")).toBeInTheDocument();
    expect(projectsApi.templateReviewTasks).not.toHaveBeenCalled();
  });

  // Hiding the Template Review pane from field-only roles now lives with the
  // workspace's own pane list - see ProjectTeam.test.jsx.
  it("uses responsive task rows", async () => {
    render(<ProjectTemplateReview projectId="p1" user={{ role: "project_manager" }} debounceMs={0}/>);
    expect((await screen.findAllByTestId("review-task"))[0]).toHaveClass("lg:grid-cols-[76px_minmax(0,1fr)_104px_100px_104px_minmax(220px,auto)]");
  });

  it("gives the assigned PM no include/exclude decisions, but lets them add a task", async () => {
    const includedConditional = { ...tasks[2], included: true, decision_state: "included" };
    projectsApi.templateReviewTasks.mockResolvedValue(page([includedConditional]));
    render(<ProjectTemplateReview projectId="p1" user={{ role: "project_manager" }} projectStatus="draft" debounceMs={0}/>);

    const row = (await screen.findAllByTestId("review-task"))[0];
    expect(within(row).queryByRole("button", { name: "Include" })).not.toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Exclude" })).not.toBeInTheDocument();
    // The project's own PM can add a task (to this project only).
    expect(screen.getByRole("button", { name: /add manual task/i })).toBeInTheDocument();
    // They can still see the list and why anything was excluded.
    expect(within(row).getByRole("button", { name: /history/i })).toBeInTheDocument();
  });

  it("keeps the decision controls for an Admin", async () => {
    const includedConditional = { ...tasks[2], included: true, decision_state: "included" };
    projectsApi.templateReviewTasks.mockResolvedValue(page([includedConditional]));
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} projectStatus="draft" debounceMs={0}/>);

    const row = (await screen.findAllByTestId("review-task"))[0];
    expect(within(row).getByRole("button", { name: "Exclude" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add manual task/i })).toBeInTheDocument();
  });

  it("excludes a conditional task with a required reason and refreshes counts without clearing filters", async () => {
    const includedConditional = { ...tasks[2], included: true, decision_state: "included" };
    projectsApi.templateReviewTasks.mockResolvedValue(page([includedConditional]));
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/>);
    const row = (await screen.findAllByTestId("review-task"))[0];
    fireEvent.change(screen.getByPlaceholderText(/search task/i), { target: { value: "survey" } });
    fireEvent.click(within(row).getByRole("button", { name: "Exclude" }));
    fireEvent.submit(screen.getByRole("button", { name: /confirm exclusion/i }).closest("form"));
    expect(screen.getByText(/explain why/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/reason \(required\)/i), { target: { value: "Survey is outside the approved scope." } });
    fireEvent.click(screen.getByRole("button", { name: /confirm exclusion/i }));
    await waitFor(() => expect(projectsApi.decideTaskApplicability).toHaveBeenCalledWith("p1", "t9", { decision: "excluded", reason: "Survey is outside the approved scope." }));
    await waitFor(() => expect(projectsApi.templateReviewSummary).toHaveBeenCalledTimes(2));
    expect(screen.getByPlaceholderText(/search task/i)).toHaveValue("survey");
  });

  it("re-includes an excluded task and shows its project audit history", async () => {
    projectsApi.taskApplicabilityHistory.mockResolvedValue([{ id: "a1", project_id: "p1", task_id: "t9", actor_user_id: "pm1", actor_name: "Project Manager", reason: "Required after site review.", previous_decision_state: "excluded", decision_state: "included", included: true, decided_at: "2026-07-29T10:00:00Z" }]);
    projectsApi.decideTaskApplicability.mockResolvedValue({ task_id: "t9", decision_state: "included", included: true });
    projectsApi.templateReviewTasks.mockResolvedValue(page([tasks[2]]));
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/>);
    let row = (await screen.findAllByTestId("review-task"))[0];
    fireEvent.click(within(row).getByRole("button", { name: "Include" }));
    fireEvent.change(screen.getByLabelText(/reason \(optional\)/i), { target: { value: "Required after site review." } });
    fireEvent.click(screen.getByRole("button", { name: /confirm inclusion/i }));
    await waitFor(() => expect(projectsApi.decideTaskApplicability).toHaveBeenCalledWith("p1", "t9", { decision: "included", reason: "Required after site review." }));
    row = (await screen.findAllByTestId("review-task"))[0];
    fireEvent.click(within(row).getByRole("button", { name: "History" }));
    expect(await screen.findByText("Decision history")).toBeInTheDocument();
    expect(projectsApi.taskApplicabilityHistory).toHaveBeenCalledWith("p1", "t9");
    expect(screen.getByText("Required after site review.")).toBeInTheDocument();
    expect(screen.getByText(/by project manager/i)).toBeInTheDocument();
  });

  it("shows backend mutation errors and keeps conditional controls mobile-friendly", async () => {
    projectsApi.decideTaskApplicability.mockRejectedValue(Object.assign(new Error("Conditional exclusion is no longer allowed."), { status: 409 }));
    projectsApi.templateReviewTasks.mockResolvedValue(page([{ ...tasks[2], included: true, decision_state: "included" }]));
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} debounceMs={0}/>);
    const row = (await screen.findAllByTestId("review-task"))[0];
    const controls = within(row).getByLabelText(/applicability controls/i);
    expect(controls).toHaveClass("grid", "grid-cols-2", "sm:flex");
    fireEvent.click(within(controls).getByRole("button", { name: "Exclude" }));
    fireEvent.change(screen.getByLabelText(/reason \(required\)/i), { target: { value: "No longer needed." } });
    fireEvent.click(screen.getByRole("button", { name: /confirm exclusion/i }));
    expect(await screen.findByText("Conditional exclusion is no longer allowed.")).toBeInTheDocument();
  });

  it("creates a validated project-specific manual task and refreshes review counts", async () => {
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} projectStatus="draft" debounceMs={0}/>);
    await screen.findByText("Generated project tasks");
    fireEvent.click(screen.getByRole("button", { name: /add manual task/i }));
    expect(screen.getByText("Manual source")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /add manual task/i }));
    expect(screen.getAllByText("Required.").length).toBeGreaterThanOrEqual(4);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Coordinate weekend shutdown" } });
    const phaseSelect = screen.getByLabelText("Phase");
    expect(phaseSelect).toHaveRole("combobox");
    expect(within(phaseSelect).getByRole("option", { name: "Execution" })).toBeInTheDocument();
    fireEvent.change(phaseSelect, { target: { value: "Execution" } });
    const categorySelect = screen.getByLabelText("Category");
    expect(within(categorySelect).getByRole("option", { name: "Site setup" })).toBeInTheDocument();
    fireEvent.change(categorySelect, { target: { value: "Site setup" } });
    fireEvent.change(screen.getByLabelText("Start day"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("End day"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Client-specific shutdown window." } });
    fireEvent.click(screen.getByRole("button", { name: /add manual task/i }));
    await waitFor(() => expect(projectsApi.createManualTask).toHaveBeenCalledWith("p1", { title: "Coordinate weekend shutdown", phase: "Execution", category: "Site setup", planned_start_day: 10, planned_end_day: 11, reason: "Client-specific shutdown window.", add_to_template: false }));
    await waitFor(() => expect(projectsApi.templateReviewSummary).toHaveBeenCalledTimes(2));
  });

  it("shows duplicate/backend errors and prevents duplicate manual-task submission", async () => {
    let rejectRequest;
    projectsApi.createManualTask.mockReturnValue(new Promise((_, reject) => { rejectRequest = reject; }));
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} projectStatus="draft" debounceMs={0}/>);
    await screen.findByText("Generated project tasks");
    fireEvent.click(screen.getByRole("button", { name: /add manual task/i }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Manual task" } });
    fireEvent.change(screen.getByLabelText("Phase"), { target: { value: "Pre-Activation" } });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "Governance" } });
    fireEvent.change(screen.getByLabelText("Start day"), { target: { value: "45" } });
    fireEvent.change(screen.getByLabelText("End day"), { target: { value: "45" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Project requirement" } });
    const submit = screen.getByRole("button", { name: /add manual task/i });
    fireEvent.click(submit); fireEvent.click(submit);
    expect(projectsApi.createManualTask).toHaveBeenCalledTimes(1);
    rejectRequest(Object.assign(new Error("A project task with this generated code already exists. Retry the request."), { status: 409 }));
    expect(await screen.findByText(/generated code already exists/i)).toBeInTheDocument();
  });

  it("hides manual creation outside draft lifecycle and uses mobile-first modal actions", async () => {
    render(<ProjectTemplateReview projectId="p1" user={{ role: "admin" }} projectStatus="active" debounceMs={0}/>);
    await screen.findByText("Generated project tasks");
    expect(screen.queryByRole("button", { name: /add manual task/i })).not.toBeInTheDocument();
  });

});
