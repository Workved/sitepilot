import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { vendorAssignmentApi } from "../../api/vendorAssignmentApi";
import { VendorProjectPeople } from "./components/VendorProjectPeople";
import { TaskVendorDelegationForm, pointPersonOptions } from "../execution/components/TaskVendorDelegationForm";

vi.mock("../../api/vendorAssignmentApi", () => ({ vendorAssignmentApi: {
  attachContact: vi.fn(), endContactAttachment: vi.fn(), listProjectVendors: vi.fn(),
  listTaskVendorAssignments: vi.fn(), delegateTask: vi.fn(), setTaskPointPerson: vi.fn(),
} }));

const project = { id: "p1" };
const categories = [{ id: "cat-ceiling", name: "Ceiling" }, { id: "cat-flooring", name: "Flooring" }, { id: "cat-glass", name: "Glass" }];
const vendor = { id: "v1", capability_category_ids: ["cat-ceiling", "cat-flooring"] };
const ravi = { id: "c-ravi", name: "Ravi", designation: "Owner", phone: "+919000000001", whatsapp: null, is_primary: true, attachments: [] };
const ramesh = { id: "c-ramesh", name: "Ramesh", designation: "Ceiling lead", phone: "+919000000011", whatsapp: null, is_primary: false, attachments: [{ id: "att-1", category_id: "cat-ceiling", category_name: "Ceiling", note: "2nd floor" }] };

beforeEach(() => vi.clearAllMocks());

describe("VendorProjectPeople", () => {
  it("lists assigned people with their trades and call links", () => {
    render(<VendorProjectPeople project={project} mapping={{ contacts: [ramesh, ravi] }} vendor={vendor} categories={categories} canManage onChanged={vi.fn()}/>);
    expect(screen.getByText("Ramesh")).toBeInTheDocument();
    expect(screen.getByText("Ceiling")).toBeInTheDocument();
    expect(screen.getByText("2nd floor")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Call Ramesh" })).toHaveAttribute("href", "tel:+919000000011");
    expect(screen.queryByText("Ravi")).toBeNull();
  });

  it("says messages go to the primary contact when no one is assigned", () => {
    render(<VendorProjectPeople project={project} mapping={{ contacts: [ravi] }} vendor={vendor} categories={categories} canManage={false} onChanged={vi.fn()}/>);
    expect(screen.getByText(/Task messages go to the primary contact \(Ravi\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Assign person/ })).toBeNull();
  });

  it("assigns a person for chosen trades, offering only the vendor's trades", async () => {
    vendorAssignmentApi.attachContact.mockResolvedValue([]);
    const onChanged = vi.fn();
    render(<VendorProjectPeople project={project} mapping={{ contacts: [ravi, ramesh] }} vendor={vendor} categories={categories} canManage onChanged={onChanged}/>);
    fireEvent.click(screen.getByRole("button", { name: /Assign person/ }));
    expect(screen.queryByLabelText("Glass")).toBeNull();
    fireEvent.change(screen.getByLabelText("Person"), { target: { value: "c-ravi" } });
    fireEvent.click(screen.getByLabelText("Flooring"));
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "Lobby" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(vendorAssignmentApi.attachContact).toHaveBeenCalledWith("p1", { contact_id: "c-ravi", category_ids: ["cat-flooring"], note: "Lobby" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("removes one trade assignment", async () => {
    vendorAssignmentApi.endContactAttachment.mockResolvedValue({});
    render(<VendorProjectPeople project={project} mapping={{ contacts: [ramesh] }} vendor={vendor} categories={categories} canManage onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "Remove Ramesh from Ceiling" }));
    await waitFor(() => expect(vendorAssignmentApi.endContactAttachment).toHaveBeenCalledWith("p1", "att-1"));
  });
});

describe("pointPersonOptions", () => {
  it("puts people on this project's matching trade first and marks the primary", () => {
    const other = { id: "c-other", name: "Anil", is_primary: false, attachments: [{ id: "a2", category_name: "Flooring" }] };
    const options = pointPersonOptions([ravi, other, ramesh], "Ceiling");
    expect(options.map(o => o.id)).toEqual(["c-ramesh", "c-other", "c-ravi"]);
    expect(options[0].label).toBe("Ramesh · Ceiling lead - on this project (Ceiling)");
    expect(options[2].label).toBe("Ravi · Owner · primary");
  });
});

describe("TaskVendorDelegationForm point person", () => {
  const task = { id: "t1", phase: "Ceiling" };
  const mapped = [{ vendor_id: "v1", vendor_name: "Big Interiors", contacts: [ravi, ramesh] }];

  it("delegates with a chosen point person", async () => {
    vendorAssignmentApi.listProjectVendors.mockResolvedValue(mapped);
    vendorAssignmentApi.listTaskVendorAssignments.mockResolvedValue([]);
    vendorAssignmentApi.delegateTask.mockResolvedValue({});
    render(<TaskVendorDelegationForm projectId="p1" task={task} user={{ role: "project_manager" }} onChanged={vi.fn()}/>);
    fireEvent.change(await screen.findByLabelText("Delegate a mapped vendor"), { target: { value: "v1" } });
    fireEvent.change(screen.getByLabelText("Point person (optional)"), { target: { value: "c-ramesh" } });
    fireEvent.click(screen.getByRole("button", { name: "Delegate" }));
    await waitFor(() => expect(vendorAssignmentApi.delegateTask).toHaveBeenCalledWith("p1", "t1", { vendor_id: "v1", contact_id: "c-ramesh" }));
  });

  it("shows the point person and lets a supervisor change it", async () => {
    vendorAssignmentApi.listProjectVendors.mockResolvedValue(mapped);
    vendorAssignmentApi.listTaskVendorAssignments.mockResolvedValue([{
      id: "as1", vendor_id: "v1", vendor_name: "Big Interiors", status: "pending_ack", ends_at: null,
      contact_id: "c-ramesh", contact_name: "Ramesh", contact_phone: "+919000000011", contact_whatsapp: null, acknowledgements: [],
    }]);
    vendorAssignmentApi.setTaskPointPerson.mockResolvedValue({});
    render(<TaskVendorDelegationForm projectId="p1" task={task} user={{ role: "supervisor" }} onChanged={vi.fn()}/>);
    expect(await screen.findByRole("link", { name: "Call Ramesh" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Delegate a mapped vendor")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Change/ }));
    fireEvent.change(screen.getByLabelText("Point person"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(vendorAssignmentApi.setTaskPointPerson).toHaveBeenCalledWith("p1", "t1", "as1", null));
  });
});
