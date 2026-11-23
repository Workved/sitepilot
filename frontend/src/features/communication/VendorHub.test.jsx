import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/communicationApi", () => ({ communicationApi: { get: vi.fn() } }));
vi.mock("../../api/vendorsApi", () => ({ vendorsApi: {} }));
vi.mock("../../api/vendorAssignmentApi", () => ({ vendorAssignmentApi: {} }));

import { communicationApi } from "../../api/communicationApi";
import { CommunicationHubPage } from "./CommunicationHubPage";

const hub = {
  vendors: [
    { id: "v-main", name: "TEST Company", engagement_type: "main", categories: ["IT & ELV", "Ceiling", "Civil"], category_ids: ["c1"], gst_number: "27ABC" },
    { id: "v-sub", name: "Piyush", engagement_type: "sub_vendor", parent_vendor_id: "v-main", categories: ["IT & ELV"], category_ids: ["c1"] },
    { id: "v-other", name: "Alpha Glass", engagement_type: "main", categories: ["Glass"], category_ids: ["c2"], blacklisted: true },
  ],
  contacts: [
    { id: "k1", vendor_id: "v-main", name: "Shikhar", designation: "Owner", phone: "+919956496552", is_primary: true },
    { id: "k2", vendor_id: "v-main", name: "Ravi", designation: "Site lead", phone: "+919000000000", is_primary: false },
  ],
  categories: [{ id: "c1", name: "IT & ELV", active: true, vendor_count: 2 }, { id: "c2", name: "Glass", active: true, vendor_count: 1 }, { id: "c3", name: "Civil", active: true, vendor_count: 0 }],
  projects: [{ id: "p1", name: "Head Office", status: "active" }],
  project_vendors: [{ project_id: "p1", vendor_id: "v-main" }],
  relationships: [], past_projects: [], project_history: [], contact_projects: [], contact_tasks: [],
};

const action = async operation => { await operation(); return { ok: true }; };
const list = () => within(screen.getByRole("region", { name: "Vendors" }));

beforeEach(() => {
  window.history.replaceState({}, "", "/?tab=communication");
  communicationApi.get.mockResolvedValue(hub);
});

describe("Vendor Hub list", () => {
  it("summarises the directory in one line instead of stat tiles", async () => {
    render(<CommunicationHubPage user={{ role: "admin" }} action={action}/>);
    expect(await screen.findByText("3 vendors, 2 contacts, 1 on live projects, 1 blacklisted")).toBeInTheDocument();
  });

  it("nests a sub-vendor directly under its main vendor", async () => {
    render(<CommunicationHubPage user={{ role: "admin" }} action={action}/>);
    await screen.findByText("TEST Company");
    const names = list().getAllByRole("heading", { level: 3 }).map(node => node.textContent);
    expect(names).toEqual(["Alpha Glass", "TEST Company", "Piyush"]);
    expect(list().getByText("Sub-vendor of TEST Company")).toBeInTheDocument();
  });

  it("filters by trade from one menu and by type from one segmented control", async () => {
    render(<CommunicationHubPage user={{ role: "admin" }} action={action}/>);
    await screen.findByText("TEST Company");
    fireEvent.change(screen.getByLabelText("Trade"), { target: { value: "c2" } });
    expect(list().getAllByRole("heading", { level: 3 }).map(node => node.textContent)).toEqual(["Alpha Glass"]);
    fireEvent.change(screen.getByLabelText("Trade"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Sub-vendors" }));
    expect(list().getAllByRole("heading", { level: 3 }).map(node => node.textContent)).toEqual(["Piyush"]);
  });
});

describe("Vendor profile page", () => {
  it("opens as a full page linked by ?vendor=, with live work, contacts and details", async () => {
    render(<CommunicationHubPage user={{ role: "admin" }} action={action}/>);
    fireEvent.click(await screen.findByText("TEST Company"));
    expect(window.location.search).toContain("vendor=v-main");
    const profile = screen.getByLabelText("Vendor profile - TEST Company");
    expect(within(profile).getByRole("heading", { name: "TEST Company" })).toBeInTheDocument();
    expect(within(profile).getByText("Head Office")).toBeInTheDocument();
    expect(within(profile).getByText("Shikhar")).toBeInTheDocument();
    expect(within(profile).getByText("Ravi")).toBeInTheDocument();
    expect(within(profile).getByText("27ABC")).toBeInTheDocument();
    // Missing details collapse into one prompt rather than empty boxes.
    expect(within(profile).getByRole("button", { name: "Add email, address" })).toBeInTheDocument();
  });

  it("reopens the profile from the URL after a dashboard reload", async () => {
    window.history.replaceState({}, "", "/?tab=communication&vendor=v-sub");
    render(<CommunicationHubPage user={{ role: "admin" }} action={action}/>);
    const profile = await screen.findByLabelText("Vendor profile - Piyush");
    fireEvent.click(within(profile).getByRole("button", { name: "TEST Company" }));
    expect(await screen.findByLabelText("Vendor profile - TEST Company")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Vendors/ }));
    expect(await screen.findByRole("region", { name: "Vendors" })).toBeInTheDocument();
  });
});
