import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("../../api/projectsApi", () => ({
  projectsApi: {
    list: vi.fn(), references: vi.fn(), publishedTemplates: vi.fn(),
    summaries: vi.fn(), attention: vi.fn(), create: vi.fn(), update: vi.fn(),
  },
}));
vi.mock("./components/ProjectWorkspace", () => ({
  ProjectWorkspace: ({ projectId, pane }) => <div data-testid="workspace">{projectId}:{pane}</div>,
}));

function project(overrides = {}) {
  return {
    id: "p-active", code: "PRJ-ACTIVE", name: "Marathon Neo", client_name: "Neo Wealth",
    site_address: "Mumbai", status: "active", start_date: "2026-08-08", target_handover_date: "2026-09-22",
    memberships: [{ id: "m1", project_role: "project_manager", user_id: "u-pm", name: "Prachit Kadam" }],
    setup: { has_project_manager: true, has_site_supervisor: true, has_template: true, has_target_handover_date: true, activation_ready: true },
    ...overrides,
  };
}

const draft = project({
  id: "p-draft", code: "PRJ-DRAFT", name: "Lodha Amara", client_name: "Lodha", status: "draft",
  setup: { has_project_manager: true, has_site_supervisor: false, has_template: true, has_target_handover_date: false, activation_ready: false },
});

// Exactly the shape backend/app/schemas/project_read_models.py serialises.
const summary = {
  project_id: "p-active", progress_pct: 72, total_count: 60, completed_count: 43,
  blocked_count: 2, delayed_count: 1, overdue_count: 0, no_update_count: 4,
  pending_approvals: 3, pending_verifications: 1,
  last_activity_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
  phases: [{ phase: "Civil Work", total: 20, completed: 18, pct: 90 }],
};
const attentionItem = {
  id: "p-draft:setup-tasks", group: "Setup incomplete", severity: "warning",
  title: "Tasks not generated", subtitle: "Lodha Amara · cannot activate",
  project_id: "p-draft", project_code: "PRJ-DRAFT", pane: "overview", due_label: null,
};

// The phone layout repeats the selected project's name on its list toggle,
// so list assertions look inside the list itself.
const list = () => within(screen.getByRole("navigation", { name: "Project list" }));

// Status filter and sort live in one menu beside the search box.
function chooseFilter(name) {
  fireEvent.click(screen.getByRole("button", { name: /change filter or sort/i }));
  fireEvent.click(screen.getByRole("menuitemradio", { name }));
}

function setup(role = "admin") {
  return render(<ProjectsPage user={{ role, id: "u-admin" }} action={vi.fn(async operation => {
    try { await operation(); return { ok: true }; } catch (error) { return { ok: false, error: error.message }; }
  })}/>);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/");
  projectsApi.list.mockResolvedValue([project(), draft]);
  projectsApi.references.mockResolvedValue({ project_managers: [], supervisors: [], internal_employees: [] });
  projectsApi.publishedTemplates.mockResolvedValue({ items: [] });
  projectsApi.summaries.mockResolvedValue([summary]);
  projectsApi.attention.mockResolvedValue([attentionItem]);
});

describe("Projects split view", () => {
  it("keeps the filter to one control that names the current status and its count", async () => {
    setup();
    await screen.findByTestId("workspace");
    const control = screen.getByRole("button", { name: /change filter or sort/i });
    expect(control).toHaveTextContent("Active1");
    expect(screen.queryByRole("menuitemradio", { name: /^draft/i })).not.toBeInTheDocument();
  });

  it("puts projects needing attention first, then sorts by name on request", async () => {
    projectsApi.list.mockResolvedValue([project(), project({ id: "p-b", code: "PRJ-B", name: "Andheri Studio" }), project({ id: "p-c", code: "PRJ-C", name: "Zenith Labs" })]);
    projectsApi.attention.mockResolvedValue([{ ...attentionItem, id: "z1", project_id: "p-c", project_code: "PRJ-C" }]);
    setup();
    await screen.findByTestId("workspace");
    const order = () => within(screen.getByRole("navigation", { name: "Project list" }))
      .getAllByText(/^(Zenith Labs|Andheri Studio|Marathon Neo)$/).map(node => node.textContent);
    await waitFor(() => expect(order()[0]).toBe("Zenith Labs"));
    chooseFilter(/^name/i);
    expect(order()).toEqual(["Andheri Studio", "Marathon Neo", "Zenith Labs"]);
  });

  it("opens straight into the first active project instead of an empty pane", async () => {
    setup();
    expect(await screen.findByTestId("workspace")).toHaveTextContent("p-active:overview");
  });

  it("filters to active projects by default and hides drafts behind a chip", async () => {
    setup();
    await screen.findByTestId("workspace");
    expect(list().getByText("Marathon Neo")).toBeInTheDocument();
    expect(list().queryByText("Lodha Amara")).not.toBeInTheDocument();

    chooseFilter(/^draft/i);
    expect(await list().findByText("Lodha Amara")).toBeInTheDocument();
    expect(list().queryByText("Marathon Neo")).not.toBeInTheDocument();
  });

  it("renders progress and relative activity from the summaries contract", async () => {
    setup();
    await screen.findByTestId("workspace");
    expect(screen.getByText("72%")).toBeInTheDocument();
    expect(screen.getByText("2h ago")).toBeInTheDocument();
  });

  it("shows a setup meter rather than a progress bar for a draft", async () => {
    setup();
    await screen.findByTestId("workspace");
    chooseFilter(/^draft/i);
    // The draft fixture has a PM and a template but no Supervisor and no
    // handover date.
    expect(await screen.findByText("2/4")).toBeInTheDocument();
  });

  it("counts attention items and jumps to the project behind one, widening the filter", async () => {
    setup();
    await screen.findByTestId("workspace");
    fireEvent.click(screen.getByRole("button", { name: /needs attention/i }));
    fireEvent.click(await screen.findByText("Tasks not generated"));

    // p-draft is not in the default Active filter; selecting it must widen
    // the filter so the highlighted row is actually on screen.
    await waitFor(() => expect(screen.getByTestId("workspace")).toHaveTextContent("p-draft:overview"));
    expect(list().getByText("Lodha Amara")).toBeInTheDocument();
  });

  it("reflects the selected project and pane in the URL so the view is linkable", async () => {
    setup();
    await screen.findByTestId("workspace");
    await waitFor(() => expect(window.location.search).toContain("project=PRJ-ACTIVE"));
  });

  it("restores the project named in the URL on load", async () => {
    window.history.replaceState({}, "", "/?tab=projects&project=PRJ-DRAFT&pane=team");
    setup();
    expect(await screen.findByTestId("workspace")).toHaveTextContent("p-draft:team");
  });

  it("renders the list without progress or attention when the read models are unavailable", async () => {
    projectsApi.summaries.mockRejectedValue(new Error("Not Found"));
    projectsApi.attention.mockRejectedValue(new Error("Not Found"));
    setup();
    await screen.findByTestId("workspace");
    expect(list().getByText("Marathon Neo")).toBeInTheDocument();
    expect(screen.queryByText("72%")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /needs attention/i })).not.toBeInTheDocument();
  });
});
