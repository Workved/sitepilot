import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
  render(<VendorWorkHistory user={supervisor} categories={categories} savePastProject={savePastProject} deletePastProject={deletePastProject} {...props}/>);
  return { savePastProject, deletePastProject };
}

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
