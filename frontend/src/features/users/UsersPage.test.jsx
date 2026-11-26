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
const SUPER_MANAGES = ["admin", ...ADMIN_MANAGES, "super_admin"];
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
    fireEvent.click(list().getByRole("button", { name: /Open Dev Super/ }));
    const panel = within(screen.getByRole("dialog", { name: "Person - Dev Super" }));
    expect(window.location.search).toContain("person=u-super");
    expect(panel.queryByRole("button", { name: "Save changes" })).toBeNull();
    expect(panel.queryByRole("button", { name: "More account actions" })).toBeNull();
  });

  it("lets an admin edit only their own name and mobile from My profile", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "My profile" }));
    const panel = within(screen.getByRole("dialog", { name: "Person - Joy Admin" }));
    expect(panel.getByText("You")).toBeInTheDocument();
    expect(panel.queryByLabelText("Employee code")).toBeNull();
    expect(panel.queryByLabelText("Role")).toBeNull();
    expect(panel.queryByRole("button", { name: "More account actions" })).toBeNull();
    fireEvent.change(panel.getByLabelText(/Mobile number/), { target: { value: "+919822222222" } });
    fireEvent.click(panel.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(usersApi.updateMe).toHaveBeenCalledWith({ name: "Joy Admin", phone: "+919822222222" }));
    expect(usersApi.update).not.toHaveBeenCalled();
  });

  it("lets a super admin set their own employee details", async () => {
    renderPage({ actor: PEOPLE[0], manageable: SUPER_MANAGES });
    fireEvent.click(screen.getByRole("button", { name: "My profile" }));
    const panel = within(screen.getByRole("dialog", { name: "Person - Dev Super" }));
    fireEvent.change(panel.getByLabelText("Employee code"), { target: { value: "SA-1" } });
    fireEvent.change(panel.getByLabelText("Designation"), { target: { value: "Founder" } });
    fireEvent.change(panel.getByLabelText("Department"), { target: { value: "Leadership" } });
    fireEvent.click(panel.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(usersApi.updateMe).toHaveBeenCalledWith(expect.objectContaining({ employee_code: "SA-1", designation: "Founder", department: "Leadership" })));
  });

  it("lets a super admin manage another super admin and warns when granting the role", async () => {
    const other = person({ id: "u-super2", name: "Ria Super", email: "ria@x.com", role: "super_admin" });
    render(<UsersPage user={PEOPLE[0]} action={okAction()} data={{ users: [...PEOPLE, other], access_catalog: CATALOG, manageable_roles: SUPER_MANAGES }}/>);
    fireEvent.click(list().getByRole("button", { name: "Open Ria Super" }));
    const panel = within(screen.getByRole("dialog", { name: "Person - Ria Super" }));
    expect(panel.getByRole("button", { name: "More account actions" })).toBeInTheDocument();
    expect(panel.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
    fireEvent.click(panel.getByRole("button", { name: "Close" }));

    fireEvent.click(list().getByRole("button", { name: "Open Joy Admin" }));
    const admin = within(screen.getByRole("dialog", { name: "Person - Joy Admin" }));
    expect(admin.queryByRole("note")).toBeNull();
    fireEvent.change(admin.getByLabelText("Role"), { target: { value: "super_admin" } });
    expect(admin.getByRole("note")).toHaveTextContent(/full control of SiteOps/);
  });

  it("offers super admin last when adding a team member, with a warning", () => {
    renderPage({ actor: PEOPLE[0], manageable: SUPER_MANAGES });
    fireEvent.click(screen.getByRole("button", { name: /Add team member/ }));
    const modal = within(screen.getByRole("dialog", { name: "Add team member" }));
    const role = modal.getByRole("combobox", { name: "Role" });
    expect(role).toHaveValue("admin");
    expect(modal.queryByRole("note")).toBeNull();
    fireEvent.change(role, { target: { value: "super_admin" } });
    expect(modal.getByRole("note")).toHaveTextContent(/full control of SiteOps/);
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
