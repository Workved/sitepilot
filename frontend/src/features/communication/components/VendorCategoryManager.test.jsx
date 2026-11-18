import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { VendorCategoryManager, canManageCategories } from "./VendorCategoryManager";

vi.mock("../../../api/vendorAssignmentApi", () => ({ vendorAssignmentApi: {
  listCapabilityCategories: vi.fn(), addCapabilityCategory: vi.fn(), updateCapabilityCategory: vi.fn(), removeCapabilityCategory: vi.fn(),
} }));

const list = [
  { id: "c1", name: "Ceiling", active: true, vendor_count: 2 },
  { id: "c2", name: "Signage", active: true, vendor_count: 0 },
  { id: "c3", name: "Old Trade", active: false, vendor_count: 1 },
];

beforeEach(() => {
  vi.clearAllMocks();
  vendorAssignmentApi.listCapabilityCategories.mockResolvedValue(list);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("VendorCategoryManager", () => {
  it("only admins manage categories", () => {
    expect(canManageCategories({ role: "admin" })).toBe(true);
    expect(canManageCategories({ role: "super_admin" })).toBe(true);
    expect(canManageCategories({ role: "project_manager" })).toBe(false);
    expect(canManageCategories({ role: "supervisor" })).toBe(false);
  });

  it("lists categories with vendor counts and keeps hidden ones behind a toggle", async () => {
    render(<VendorCategoryManager onClose={vi.fn()}/>);
    expect(await screen.findByText("Ceiling")).toBeInTheDocument();
    expect(screen.getByText("2 vendors")).toBeInTheDocument();
    expect(screen.queryByText("Old Trade")).toBeNull();
    fireEvent.click(screen.getByLabelText(/Show 1 hidden category/));
    expect(screen.getByText("Old Trade")).toBeInTheDocument();
    expect(vendorAssignmentApi.listCapabilityCategories).toHaveBeenCalledWith({ includeHidden: true });
  });

  it("adds a category", async () => {
    vendorAssignmentApi.addCapabilityCategory.mockResolvedValue({ id: "c9", name: "Glass Works", active: true });
    const onChanged = vi.fn();
    render(<VendorCategoryManager onClose={vi.fn()} onChanged={onChanged}/>);
    await screen.findByText("Ceiling");
    fireEvent.change(screen.getByLabelText("New category name"), { target: { value: "Glass Works" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(vendorAssignmentApi.addCapabilityCategory).toHaveBeenCalledWith("Glass Works"));
    expect(await screen.findByText(/"Glass Works" is ready to use/)).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("renames, and shows the server's reason when a rename is refused", async () => {
    vendorAssignmentApi.updateCapabilityCategory.mockRejectedValue(new Error("\"Ceiling\" is the phase of 4 tasks"));
    render(<VendorCategoryManager onClose={vi.fn()}/>);
    await screen.findByText("Ceiling");
    fireEvent.click(screen.getByRole("button", { name: "Rename Ceiling" }));
    fireEvent.change(screen.getByLabelText("New name for Ceiling"), { target: { value: "False Ceiling" } });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(vendorAssignmentApi.updateCapabilityCategory).toHaveBeenCalledWith("c1", { name: "False Ceiling" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/phase of 4 tasks/);
  });

  it("removes (or hides) and can show a hidden one again", async () => {
    vendorAssignmentApi.removeCapabilityCategory.mockResolvedValue({ deleted: false, hidden: true, message: "\"Ceiling\" was hidden, not deleted, because 2 vendors have it." });
    vendorAssignmentApi.updateCapabilityCategory.mockResolvedValue({ id: "c3", name: "Old Trade", active: true });
    render(<VendorCategoryManager onClose={vi.fn()}/>);
    await screen.findByText("Ceiling");
    fireEvent.click(screen.getByRole("button", { name: "Remove Ceiling" }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/2 vendors have "Ceiling"\. It will be hidden/));
    expect(await screen.findByText(/hidden, not deleted/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/hidden categor/));
    fireEvent.click(screen.getByRole("button", { name: "Show Old Trade again" }));
    await waitFor(() => expect(vendorAssignmentApi.updateCapabilityCategory).toHaveBeenCalledWith("c3", { active: true }));
  });
});
