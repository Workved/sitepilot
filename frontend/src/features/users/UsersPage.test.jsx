import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usersApi } from "../../api/usersApi";
import { attentionFor, filterPeople, sortPeople, summaryLine } from "./teamHelpers";
import { UsersPage } from "./UsersPage";

vi.mock("../../api/usersApi", () => ({
  usersApi: { events: vi.fn(), invite: vi.fn(), update: vi.fn(), setPassword: vi.fn(), offboard: vi.fn(), restore: vi.fn(), remove: vi.fn(), updateMe: vi.fn() },
}));
vi.mock("../../api/projectsApi", () => ({ projectsApi: { list: vi.fn(async () => []) } }));

const profile = (code, designation) => ({ employee_code: code, designation, department: null });
const person = overrides => ({
  active: true, activation_status: "active", phone: "+919800000000", last_login_at: new Date().toISOString(),
  created_at: "2026-11-01T00:00:00Z", employee_profile: profile("E-1", "Staff"), ...overrides,
});
const PEOPLE = [
  person({ id: "u-super", name: "Dev Super", email: "super@x.com", role: "super_admin", employee_profile: null }),
  person({ id: "u-admin", name: "Joy Admin", email: "joy@x.com", role: "admin" }),
  person({ id: "u-pm", name: "Ved PM", email: "ved@x.com", role: "project_manager", employee_profile: profile("EMP-0124", "Project Manager") }),
  person({ id: "u-sup", name: "Sam Sup", email: "sam@x.com", role: "supervisor", phone: null, activation_status: "setup_pending", last_login_at: null }),
  person({ id: "u-new", name: "Nina New", email: "nina@x.com", role: "supervisor", employee_profile: null, activation_status: "setup_pending", last_login_at: null }),
  person({ id: "u-gone", name: "Old Timer", email: "old@x.com", role: "supervisor", active: false, activation_status: "offboarded" }),
];
const CATALOG = [
  { role: "super_admin", label: "Super Admin", summary: "Technical governance.", capabilities: ["Manage all"] },
  { role: "admin", label: "Admin", summary: "People administration.", capabilities: ["Create projects"] },
  { role: "project_manager", label: "Project Manager", summary: "Project control.", capabilities: ["Manage vendors"] },
  { role: "supervisor", label: "Supervisor", summary: "Site execution.", capabilities: ["Verify submitted work"] },
  { role: "internal_employee", label: "Internal Employee", summary: "Delegated support.", capabilities: [] },
];
const ADMIN_MANAGES = ["project_manager", "supervisor", "internal_employee"];
const okAction = () => vi.fn(async operation => { await operation(); return { ok: true }; });

function renderPage({ actor = PEOPLE[1], manageable = ADMIN_MANAGES, action = okAction() } = {}) {
  render(<UsersPage user={actor} action={action} data={{ users: PEOPLE, access_catalog: CATALOG, manageable_roles: manageable }}/>);
  return { action };
}
const list = () => within(screen.getByRole("region", { name: "People" }));

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/?tab=users");
  usersApi.events.mockResolvedValue([{ id: "e1", event_type: "ACCOUNT_INVITED", reason: "Pre-registered", created_at: "2026-11-01T10:00:00Z" }]);
});

describe("Team directory", () => {
  it("summarises the team and hides offboarded people by default", () => {
    renderPage();
    expect(screen.getByText("6 people, 3 active, 2 haven't signed in yet, 1 offboarded")).toBeInTheDocument();
    expect(list().queryByRole("button", { name: "Open Old Timer" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Offboarded" }));
    expect(list().getByRole("button", { name: "Open Old Timer" })).toBeInTheDocument();
  });

  it("surfaces what needs fixing and filters to it", () => {
    renderPage();
    const attention = within(screen.getByRole("region", { name: "Needs attention" }));
    expect(attention.getByRole("button", { name: "2 haven't signed in" })).toBeInTheDocument();
    expect(attention.getByRole("button", { name: "1 no mobile number" })).toBeInTheDocument();
    fireEvent.click(attention.getByRole("button", { name: "1 can't be put on a project" }));
    expect(list().getAllByRole("button", { name: /^Open / }).map(button => button.getAttribute("aria-label"))).toEqual(["Open Nina New"]);
  });

  it("filters by role chips that carry counts", () => {
    renderPage();
    fireEvent.click(within(screen.getByRole("group", { name: "Role" })).getByRole("button", { name: "Supervisor 2" }));
    expect(list().getAllByRole("button", { name: /^Open / })).toHaveLength(2);
  });

  it("opens a person in a side panel kept in the URL, read-only outside your authority", async () => {
    renderPage();
    fireEvent.click(list().getByRole("button", { name: /Open Joy Admin/ }));
    const panel = within(screen.getByRole("dialog", { name: "Person - Joy Admin" }));
    expect(window.location.search).toContain("person=u-admin");
    expect(panel.getByText("You")).toBeInTheDocument();
    expect(panel.queryByRole("button", { name: "Save changes" })).toBeNull();
    expect(panel.queryByRole("button", { name: "More account actions" })).toBeNull();
  });

  it("saves a managed person's details without closing the panel", async () => {
    const { action } = renderPage();
    fireEvent.click(list().getByRole("button", { name: "Open Ved PM" }));
    const panel = within(screen.getByRole("dialog", { name: "Person - Ved PM" }));
    fireEvent.change(panel.getByLabelText(/Mobile number/), { target: { value: "+919811111111" } });
    fireEvent.click(panel.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(usersApi.update).toHaveBeenCalledWith("u-pm", expect.objectContaining({ phone: "+919811111111", employee_code: "EMP-0124" })));
    expect(action).toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Person - Ved PM" })).toBeInTheDocument();
  });

  it("asks for a reason when the role changes", () => {
    renderPage();
    fireEvent.click(list().getByRole("button", { name: "Open Ved PM" }));
    const panel = within(screen.getByRole("dialog", { name: "Person - Ved PM" }));
    fireEvent.change(panel.getByLabelText("Role"), { target: { value: "supervisor" } });
    expect(panel.getByLabelText(/Reason for the role change/)).toBeRequired();
  });

  it("explains what is missing and offboards from the menu with a reason", async () => {
    renderPage();
    fireEvent.click(list().getByRole("button", { name: "Open Sam Sup" }));
    const panel = within(screen.getByRole("dialog", { name: "Person - Sam Sup" }));
    expect(within(panel.getByRole("list", { name: "Needs attention" })).getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(panel.getByRole("button", { name: "More account actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Offboard" }));
    const dialog = within(screen.getByRole("dialog", { name: "Offboard Sam Sup?" }));
    fireEvent.change(dialog.getByLabelText(/Reason/), { target: { value: "Left the company" } });
    fireEvent.click(dialog.getByRole("button", { name: /Offboard/ }));
    await waitFor(() => expect(usersApi.offboard).toHaveBeenCalledWith("u-sup", "Left the company"));
  });

  it("shows account history", async () => {
    renderPage();
    fireEvent.click(list().getByRole("button", { name: "Open Ved PM" }));
    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(await screen.findByText("Account invited")).toBeInTheDocument();
  });
});

describe("team helpers", () => {
  it("flags only active people, and profiles only for project roles", () => {
    expect(attentionFor(PEOPLE[3])).toEqual(["not_signed_in", "no_phone"]);
    expect(attentionFor(PEOPLE[0])).toEqual([]);
    expect(attentionFor({ ...PEOPLE[3], active: false })).toEqual([]);
  });

  it("searches across code and phone, and sorts never-signed-in last when newest first", () => {
    expect(filterPeople(PEOPLE, { query: "emp-0124" }).map(item => item.id)).toEqual(["u-pm"]);
    const sorted = sortPeople(filterPeople(PEOPLE), "last_active", "desc").map(item => item.id);
    expect(sorted.slice(-2).sort()).toEqual(["u-new", "u-sup"]);
  });

  it("writes the header line", () => {
    expect(summaryLine([])).toMatch(/Add your first team member/);
  });
});
