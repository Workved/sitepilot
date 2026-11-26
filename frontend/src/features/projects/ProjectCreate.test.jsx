import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectFormModal } from "./components/ProjectFormModal";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("../../api/projectsApi", () => ({
  projectsApi: {
    list: vi.fn(), references: vi.fn(), publishedTemplates: vi.fn(), create: vi.fn(), update: vi.fn(),
    summaries: vi.fn(), attention: vi.fn(),
  },
}));
vi.mock("./components/ProjectWorkspace", () => ({
  ProjectWorkspace: ({ projectId }) => <div data-testid="opened-project">{projectId}</div>,
}));

const references = {
  project_managers: [{ employee_id: "employee-pm", user_id: "user-pm", name: "Priya Manager", designation: "Project Manager" }],
  supervisors: [{ employee_id: "employee-supervisor", user_id: "user-supervisor", name: "Sameer Supervisor", designation: "Site Supervisor" }],
  internal_employees: [],
};
// Shaped like project_json(): the split view selects by `code` and the list
// pane reads `setup` and `memberships`.
function createdProject(id = "project-created") {
  return {
    id, code: "PRJ-20260810-CREATED", name: "Mumbai HQ Fit-Out", client_name: "Acme India",
    site_address: "Lower Parel, Mumbai", status: "draft", start_date: "2026-08-10",
    target_handover_date: "2026-09-24", memberships: [],
    setup: { has_project_manager: true, has_site_supervisor: true, has_template: true, has_target_handover_date: true, activation_ready: true },
  };
}

const templateResponse = {
  items: [{ version_id: "version-published", version_no: 2, template_name: "Workved 45-Day Template", duration_days: 45, status: "published", is_current_published: true }],
  pagination: { page: 1, page_size: 100, total: 1, total_pages: 1 },
};

function setup(role = "admin") {
  return render(<ProjectsPage user={{ role }} action={vi.fn(async operation => {
    try { await operation(); return { ok: true }; } catch (error) { return { ok: false, error: error.message }; }
  })}/>);
}

async function openForm(role = "admin") {
  setup(role);
  await screen.findByText("No projects yet");
  fireEvent.click(screen.getByRole("button", { name: /new project/i }));
  return screen.findByRole("heading", { name: /create draft project/i });
}

function fillForm() {
  fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Mumbai HQ Fit-Out" } });
  fireEvent.change(screen.getByLabelText("Client"), { target: { value: "Acme India" } });
  fireEvent.change(screen.getByLabelText("Location"), { target: { value: "Lower Parel, Mumbai" } });
  fireEvent.change(screen.getByLabelText("Proposed start date"), { target: { value: "2026-08-10" } });
  fireEvent.change(screen.getByLabelText("Project Manager"), { target: { value: "user-pm" } });
  fireEvent.change(screen.getByLabelText("Supervisor"), { target: { value: "user-supervisor" } });
  fireEvent.change(screen.getByLabelText("Published template version"), { target: { value: "version-published" } });
}

beforeEach(() => {
  vi.clearAllMocks();
  // New projects can't start in the past; these tests type fixed dates, so
  // pin "today" just before them (only Date is faked - timers stay real).
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-08-01T09:00:00"));
  projectsApi.list.mockResolvedValue([]);
  projectsApi.references.mockResolvedValue(references);
  projectsApi.publishedTemplates.mockResolvedValue(templateResponse);
  // Additive read models: absent until the endpoints ship, and the page is
  // required to render without them.
  projectsApi.summaries.mockRejectedValue(new Error("Not Found"));
  projectsApi.attention.mockRejectedValue(new Error("Not Found"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Admin draft project creation", () => {

  it("deduplicates initial project, role and template reference requests under StrictMode", async () => {
    render(<StrictMode><ProjectsPage user={{ role: "admin" }} action={vi.fn(async operation => {
      try { await operation(); return { ok: true }; } catch (error) { return { ok: false, error: error.message }; }
    })}/></StrictMode>);
    await screen.findByText("No projects yet");
    expect(projectsApi.list).toHaveBeenCalledTimes(1);
    expect(projectsApi.references).toHaveBeenCalledTimes(1);
    expect(projectsApi.publishedTemplates).toHaveBeenCalledTimes(1);
  });

  it("loads the published template reference list for Super Admin fallback", async () => {
    await openForm("super_admin");
    expect(projectsApi.publishedTemplates).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("option", { name: /Workved 45-Day Template.*Current/ })).toHaveValue("version-published");
  });

  it("renders active role selectors and published template options", async () => {
    await openForm();
    expect(screen.getByRole("option", { name: /Priya Manager/ })).toHaveValue("user-pm");
    expect(screen.getByRole("option", { name: /Sameer Supervisor/ })).toHaveValue("user-supervisor");
    expect(screen.getByRole("option", { name: /Workved 45-Day Template.*Current/ })).toHaveValue("version-published");
  });

  it("shows the approved template section before accountability and never hides an empty state", async () => {
    await openForm();
    const templateHeading = screen.getByText("Approved published template");
    const accountabilityHeading = screen.getByText("Accountability");
    expect(templateHeading.compareDocumentPosition(accountabilityHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText("Published template version")).toBeVisible();
  });

  it("submits the accepted backend contract and opens the created project", async () => {
    projectsApi.create.mockResolvedValue(createdProject());
    projectsApi.list.mockResolvedValueOnce([]).mockResolvedValue([createdProject()]);
    await openForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));

    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledWith({
      name: "Mumbai HQ Fit-Out",
      client_name: "Acme India",
      site_address: "Lower Parel, Mumbai",
      start_date: "2026-08-10",
      project_manager_user_id: "user-pm",
      supervisor_user_id: "user-supervisor",
      template_version_id: "version-published",
    }));
    expect(await screen.findByTestId("opened-project")).toHaveTextContent("project-created");
  });

  it("derives the handover date from the start date and template duration", async () => {
    await openForm();
    // Nothing to derive from yet.
    expect(screen.getByLabelText("Target handover date")).toHaveTextContent("Select a start date and template");

    fillForm();
    // 2026-08-10 is day 1 of a 45-day template, so day 45 is 2026-09-23.
    // en-GB abbreviates September as "Sept" in current ICU; match either.
    expect(screen.getByLabelText("Target handover date")).toHaveTextContent(/23 Sept? 2026/);
    expect(screen.getByText(/day 45 of Workved 45-Day Template/i)).toBeInTheDocument();
  });

  it("moves the derived handover date when the start date changes", async () => {
    await openForm();
    fillForm();
    fireEvent.change(screen.getByLabelText("Proposed start date"), { target: { value: "2026-09-01" } });
    expect(screen.getByLabelText("Target handover date")).toHaveTextContent("15 Oct 2026");
  });

  it("never sends a handover date - the server derives it", async () => {
    projectsApi.create.mockResolvedValue(createdProject());
    projectsApi.list.mockResolvedValueOnce([]).mockResolvedValue([createdProject()]);
    await openForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalled());
    expect(projectsApi.create.mock.calls[0][0]).not.toHaveProperty("target_handover_date");
  });

  it("prevents double submit and disables controls while pending", async () => {
    let resolveCreate;
    projectsApi.create.mockReturnValue(new Promise(resolve => { resolveCreate = resolve; }));
    projectsApi.list.mockResolvedValueOnce([]).mockResolvedValue([createdProject("project-pending")]);
    await openForm();
    fillForm();
    const submit = screen.getByRole("button", { name: /create draft/i });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(submit).toBeDisabled();
    expect(screen.getByLabelText("Project name")).toBeDisabled();
    resolveCreate(createdProject("project-pending"));
    expect(await screen.findByTestId("opened-project")).toHaveTextContent("project-pending");
  });

  it("shows field and API errors without closing the form", async () => {
    await openForm();
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByText("Project name is required.")).toBeInTheDocument();
    expect(projectsApi.create).not.toHaveBeenCalled();

    fillForm();
    projectsApi.create.mockRejectedValue(new Error("Select a published template version."));
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Select a published template version");
    expect(screen.getByRole("heading", { name: /create draft project/i })).toBeInTheDocument();
  });

  it("allows today or a future start date, but not a past one", async () => {
    await openForm();
    const start = screen.getByLabelText("Proposed start date");
    expect(start).toHaveAttribute("min", "2026-08-01");
    fillForm();
    fireEvent.change(start, { target: { value: "2026-07-31" } });
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByText("The proposed start date cannot be before today.")).toBeInTheDocument();
    expect(projectsApi.create).not.toHaveBeenCalled();

    projectsApi.create.mockResolvedValue({ id: "project-new", code: "PRJ-NEW" });
    fireEvent.change(start, { target: { value: "2026-08-01" } });
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledWith(expect.objectContaining({ start_date: "2026-08-01" })));
  });

  it("uses responsive full-width mobile actions", async () => {
    await openForm();
    expect(screen.getByRole("button", { name: /create draft/i })).toHaveClass("w-full", "sm:w-auto");
    expect(screen.getByRole("button", { name: /cancel/i })).toHaveClass("w-full", "sm:w-auto");
  });
});

describe("Editing a project that already has a template", () => {
  const attached = {
    id: "project-1", code: "PRJ-1", name: "Khar Fit-Out", client_name: "Castrol",
    site_address: "Khar, Mumbai", description: null, status: "draft",
    start_date: "2026-08-10", target_handover_date: "2026-09-23",
    template_version_id: "version-published", memberships: [],
  };

  function renderEdit(onSubmit) {
    return render(<ProjectFormModal
      project={attached}
      references={references}
      templates={templateResponse.items}
      onClose={vi.fn()}
      onSubmit={onSubmit}
      saving={false}
    />);
  }

  it("locks the start date and shows the derived handover instead of an input", () => {
    renderEdit(vi.fn());
    expect(screen.getByLabelText("Proposed start date")).toBeDisabled();
    expect(screen.getByLabelText("Target handover date")).toHaveTextContent(/23 Sept? 2026/);
    expect(screen.getByLabelText("Target handover date").tagName).toBe("OUTPUT");
  });

  it("still submits the start date even though its input is disabled", async () => {
    // Regression: a disabled input is dropped from FormData, which would
    // fail the edit form's own "start date is required" validation.
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderEdit(onSubmit);
    fireEvent.change(screen.getByLabelText("Reason for change"), { target: { value: "Corrected the client name." } });
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.start_date).toBe("2026-08-10");
    expect(payload).not.toHaveProperty("target_handover_date");
    expect(payload).not.toHaveProperty("template_version_id");
  });
});

describe("empty Projects page", () => {
  it("offers one New project button, not a second full-width one", async () => {
    setup();
    await screen.findByText("No projects yet");
    await waitFor(() => expect(screen.getAllByRole("button", { name: /new project/i })).toHaveLength(1));
  });

  it("asks for a published template first, and links to Templates", async () => {
    projectsApi.publishedTemplates.mockResolvedValue({ items: [] });
    const onTabChange = vi.fn();
    render(<ProjectsPage user={{ role: "super_admin" }} onTabChange={onTabChange} action={vi.fn()}/>);
    expect(await screen.findByText("Publish a template first")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new project/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /go to templates/i }));
    expect(onTabChange).toHaveBeenCalledWith("templates");
  });
});
