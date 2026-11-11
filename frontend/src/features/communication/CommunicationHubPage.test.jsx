import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/communicationApi", () => ({
  communicationApi: { get: vi.fn(), updateContractor: vi.fn(), addContact: vi.fn() },
}));
vi.mock("../../api/vendorsApi", () => ({ vendorsApi: { create: vi.fn(), remove: vi.fn() } }));
vi.mock("../../api/vendorAssignmentApi", () => ({ vendorAssignmentApi: { mapVendor: vi.fn() } }));

import { communicationApi } from "../../api/communicationApi";
import { vendorsApi } from "../../api/vendorsApi";
import { CommunicationHubPage } from "./CommunicationHubPage";

const hub = { vendors: [], contacts: [], categories: [{ id: "cat-1", name: "Electrical", parent_id: null, active: true }], projects: [], project_vendors: [], relationships: [] };

// Mirrors Dashboard's `action`: run, then a (possibly slow) dashboard refresh.
async function action(operation) {
  try { await operation(); return { ok: true }; }
  catch (error) { return { ok: false, error: error.message }; }
}

async function openMainVendorForm() {
  render(<CommunicationHubPage user={{ role: "admin" }} action={action}/>);
  fireEvent.click((await screen.findAllByRole("button", { name: /Add vendor/ }))[0]);
  fireEvent.click(screen.getByRole("button", { name: "Add main vendor" }));
  const form = document.getElementById("vendor-company-form");
  fireEvent.change(form.querySelector("input[name=name]"), { target: { value: "Acme Electric" } });
  fireEvent.change(form.querySelector("input[name=contact_person]"), { target: { value: "Ravi" } });
  fireEvent.change(form.querySelector("input[name=phone]"), { target: { value: "9876543210" } });
  fireEvent.click(form.querySelector("input[type=checkbox]"));
  return screen.getByRole("button", { name: "Create main vendor" });
}

describe("Vendor Hub create main vendor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    communicationApi.get.mockResolvedValue(hub);
    communicationApi.updateContractor.mockResolvedValue({});
    communicationApi.addContact.mockResolvedValue({});
  });

  it("creates the vendor once when Create is clicked again while the save is still running", async () => {
    let finishCreate;
    vendorsApi.create.mockReturnValue(new Promise(resolve => { finishCreate = resolve; }));
    const submit = await openMainVendorForm();

    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();

    await act(async () => { finishCreate({ id: "v1" }); });
    await waitFor(() => expect(document.getElementById("vendor-company-form")).toBeNull());
    expect(vendorsApi.create).toHaveBeenCalledTimes(1);
    expect(communicationApi.addContact).toHaveBeenCalledTimes(1);
  });

  it("reuses the already-created vendor when retrying after a later step failed", async () => {
    vendorsApi.create.mockResolvedValue({ id: "v1" });
    communicationApi.updateContractor.mockRejectedValueOnce(new Error("Network error"));
    const submit = await openMainVendorForm();

    fireEvent.click(submit);
    await waitFor(() => expect(screen.getByRole("button", { name: "Create main vendor" })).not.toBeDisabled());
    expect(document.getElementById("vendor-company-form")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Create main vendor" }));
    await waitFor(() => expect(document.getElementById("vendor-company-form")).toBeNull());
    expect(vendorsApi.create).toHaveBeenCalledTimes(1);
    expect(communicationApi.updateContractor).toHaveBeenCalledTimes(2);
    expect(communicationApi.addContact).toHaveBeenCalledWith(expect.objectContaining({ vendor_id: "v1", is_primary: true }));
  });
});
