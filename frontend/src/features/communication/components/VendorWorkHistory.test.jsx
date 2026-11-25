import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { summarizeFeedback } from "../vendorFeedback";
import { VendorWorkHistory, canEditWorkHistory, periodLabel, valueLabel } from "./VendorWorkHistory";

const categories = [{ id: "cat-1", name: "Electrical" }];
const supervisor = { id: "u-sup", role: "supervisor" };
const otherSupervisor = { id: "u-sup-2", role: "supervisor" };
const admin = { id: "u-admin", role: "admin" };
const employee = { id: "u-emp", role: "internal_employee" };

const entry = {
  id: "pp-1", vendor_id: "v1", project_name: "Skyline Towers", client_name: "Infra Ltd", location: "Pune",
  category_id: "cat-1", category_name: "Electrical", work_description: "Full wiring", start_month: "2023-02",
  end_month: "2023-09", approx_value: 1250000, notes: null, created_by: "u-sup", created_by_name: "Supervisor",
};

function renderHistory(props = {}) {
  const savePastProject = vi.fn(async () => ({ ok: true }));
  const deletePastProject = vi.fn(async () => ({ ok: true }));
  const saveFeedback = vi.fn(async () => ({ ok: true }));
  const deleteFeedback = vi.fn(async () => ({ ok: true }));
  render(<VendorWorkHistory user={supervisor} vendorName="Acme Electric" categories={categories} savePastProject={savePastProject} deletePastProject={deletePastProject}
    saveFeedback={saveFeedback} deleteFeedback={deleteFeedback} {...props}/>);
  return { savePastProject, deletePastProject, saveFeedback, deleteFeedback };
}

const finished = { id: "pv-9", vendor_id: "v1", project_id: "p-done", project_name: "Tower A", project_code: "P-1", project_status: "completed",
  started_at: "2026-01-10T00:00:00Z", ended_at: "2026-06-30T00:00:00Z", removed: false, can_review: true };
const review = { id: "f1", vendor_id: "v1", project_id: "p-done", project_name: "Tower A", author_user_id: "u-pm", author_name: "Priya", author_role_label: "Project manager",
  rating: 4, quality: 5, timeliness: 3, conduct: null, would_rehire: "yes", comment: "Neat wiring.", created_at: "2026-07-02T00:00:00Z" };

describe("VendorWorkHistory", () => {
  it("shows hand-entered and SiteOps past projects", () => {
    renderHistory({
      pastProjects: [entry],
      projectHistory: [{ id: "pv-1", vendor_id: "v1", project_name: "Tower A", started_at: "2025-01-10T00:00:00Z", ended_at: "2025-06-30T00:00:00Z" }],
    });
    expect(screen.getByText("Skyline Towers")).toBeInTheDocument();
    expect(screen.getByText("Tower A")).toBeInTheDocument();
    expect(screen.getByText("Added by Supervisor")).toBeInTheDocument();
    expect(screen.getByText("₹12,50,000")).toBeInTheDocument();
  });

  it("lets a supervisor add a past project", async () => {
    const { savePastProject } = renderHistory();
    fireEvent.click(screen.getByRole("button", { name: /Add past project/ }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Mall fit-out" } });
    fireEvent.change(screen.getByLabelText("Start month"), { target: { value: "2022-01" } });
    fireEvent.change(screen.getByLabelText("End month"), { target: { value: "2022-06" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Add past project" }).at(-1));
    await waitFor(() => expect(savePastProject).toHaveBeenCalledTimes(1));
    expect(savePastProject).toHaveBeenCalledWith(null, expect.objectContaining({ project_name: "Mall fit-out", start_month: "2022-01", end_month: "2022-06" }));
    await waitFor(() => expect(screen.queryByLabelText("Project name")).toBeNull());
  });

  it("blocks an end month before the start month", () => {
    const { savePastProject } = renderHistory();
    fireEvent.click(screen.getByRole("button", { name: /Add past project/ }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Bad dates" } });
    fireEvent.change(screen.getByLabelText("Start month"), { target: { value: "2024-05" } });
    fireEvent.change(screen.getByLabelText("End month"), { target: { value: "2024-01" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Add past project" }).at(-1));
    expect(screen.getByRole("alert")).toHaveTextContent("End month cannot be before the start month.");
    expect(savePastProject).not.toHaveBeenCalled();
  });

  it("edits an existing entry by id", async () => {
    const { savePastProject } = renderHistory({ pastProjects: [entry] });
    fireEvent.click(screen.getByRole("button", { name: "Edit Skyline Towers" }));
    expect(screen.getByLabelText("Project name")).toHaveValue("Skyline Towers");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(savePastProject).toHaveBeenCalledWith("pp-1", expect.objectContaining({ project_name: "Skyline Towers", category_id: "cat-1" })));
  });

  it("asks before deleting", async () => {
    const { deletePastProject } = renderHistory({ pastProjects: [entry] });
    fireEvent.click(screen.getByRole("button", { name: "Delete Skyline Towers" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(deletePastProject).toHaveBeenCalledWith("pp-1"));
  });

  it("hides add for roles without access, and edit for other people's entries", () => {
    renderHistory({ user: employee, pastProjects: [entry] });
    expect(screen.queryByRole("button", { name: /Add past project/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit Skyline Towers" })).toBeNull();
  });

  it("permission rule: creator or admin", () => {
    expect(canEditWorkHistory(supervisor, entry)).toBe(true);
    expect(canEditWorkHistory(admin, entry)).toBe(true);
    expect(canEditWorkHistory(otherSupervisor, entry)).toBe(false);
    expect(canEditWorkHistory(otherSupervisor, { ...entry, created_by: null })).toBe(false);
  });

  it("formats periods and values", () => {
    expect(periodLabel("2023-02", "2023-03")).toBe("Feb 2023 - Mar 2023");
    expect(periodLabel("2023-02", null)).toBe("From Feb 2023");
    expect(periodLabel(null, null)).toBe("");
    expect(valueLabel(null)).toBe("");
    expect(valueLabel(0)).toBe("₹0");
  });

});

describe("vendor feedback", () => {
  it("shows reviews on a finished SiteOps project", () => {
    renderHistory({ projectHistory: [finished], feedback: [review] });
    const project = within(screen.getByRole("article", { name: "Tower A" }));
    expect(project.getByText("Completed")).toBeInTheDocument();
    expect(project.getByText("Would hire again")).toBeInTheDocument();
    expect(project.getByText("Neat wiring.")).toBeInTheDocument();
    expect(project.getByText(/Priya, Project manager/)).toBeInTheDocument();
    expect(project.getByRole("img", { name: "4 out of 5 stars" })).toBeInTheDocument();
  });

  it("lets someone who worked on it leave feedback, and requires a reason for a low score", async () => {
    const { saveFeedback } = renderHistory({ projectHistory: [finished] });
    fireEvent.click(screen.getByRole("button", { name: /Leave feedback/ }));
    const dialog = within(screen.getByRole("dialog", { name: "Leave feedback" }));
    fireEvent.click(within(dialog.getByRole("radiogroup", { name: "Overall rating" })).getByRole("radio", { name: "2 of 5" }));
    fireEvent.click(dialog.getByRole("radio", { name: "No" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit feedback" }));
    expect(dialog.getByRole("alert")).toHaveTextContent("Add a comment");
    expect(saveFeedback).not.toHaveBeenCalled();

    fireEvent.change(dialog.getByRole("textbox"), { target: { value: "Left the site dirty." } });
    fireEvent.click(screen.getByRole("button", { name: "Submit feedback" }));
    await waitFor(() => expect(saveFeedback).toHaveBeenCalledWith("p-done", null, expect.objectContaining({ rating: 2, would_rehire: "no", comment: "Left the site dirty." })));
  });

  it("offers edit on your own review instead of a second one", async () => {
    const { saveFeedback } = renderHistory({ user: { id: "u-pm", role: "project_manager" }, projectHistory: [finished], feedback: [review] });
    expect(screen.queryByRole("button", { name: /Leave feedback/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit feedback by Priya" }));
    fireEvent.click(screen.getByRole("button", { name: "Save feedback" }));
    await waitFor(() => expect(saveFeedback).toHaveBeenCalledWith("p-done", "f1", expect.objectContaining({ rating: 4, quality: 5 })));
  });

  it("lets admins remove but not edit other people's reviews, and hides the button from outsiders", async () => {
    const { deleteFeedback } = renderHistory({ user: admin, projectHistory: [{ ...finished, can_review: true }], feedback: [review] });
    expect(screen.queryByRole("button", { name: "Edit feedback by Priya" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Delete feedback by Priya" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete feedback" }));
    await waitFor(() => expect(deleteFeedback).toHaveBeenCalledWith("f1"));
  });

  it("hides Leave feedback when the user did not work on the project", () => {
    renderHistory({ user: otherSupervisor, projectHistory: [{ ...finished, can_review: false }] });
    expect(screen.queryByRole("button", { name: /Leave feedback/ })).toBeNull();
    expect(screen.getByText("No feedback yet.")).toBeInTheDocument();
  });

  it("summarises ratings and who would rehire", () => {
    const summary = summarizeFeedback([review, { ...review, id: "f2", rating: 2, quality: null, would_rehire: "no" }]);
    expect(summary).toMatchObject({ count: 2, average: 3, rehire: { yes: 1, conditional: 0, no: 1 } });
    expect(summary.scores.quality).toBe(5);
    expect(summarizeFeedback([]).average).toBeNull();
  });
});
