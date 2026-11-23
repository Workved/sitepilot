import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { broadcastApi } from "../../api/broadcastApi";
import { projectsApi } from "../../api/projectsApi";
import { dayLabel, groupByDay, summaryLine } from "./broadcastFormat";
import { CommunicationPage } from "./CommunicationPage";

vi.mock("../../api/broadcastApi", () => ({
  broadcastApi: {
    summary: vi.fn(), list: vi.fn(), detail: vi.fn(), create: vi.fn(), send: vi.fn(),
    recipients: vi.fn(), templates: vi.fn(), createTemplate: vi.fn(), deleteTemplate: vi.fn(),
  },
}));
vi.mock("../../api/projectsApi", () => ({ projectsApi: { list: vi.fn() } }));

const now = new Date();
const SENT = { id: "b1", project_id: "p1", project_name: "Main office interiors", title: "Hey everyone", recipient_count: 2, status: "sent", send_mode: "now", sent_at: now.toISOString(), created_at: now.toISOString() };
const FAILED = { id: "b2", project_id: "p1", project_name: "Main office interiors", title: "Weekly review", recipient_count: 3, status: "partially_failed", send_mode: "now", sent_at: new Date(now.getTime() - 86400000 * 3).toISOString(), created_at: now.toISOString() };
const SCHEDULED = { id: "b3", project_id: "p1", project_name: "Main office interiors", title: "Monday kickoff", recipient_count: 4, status: "scheduled", send_mode: "scheduled", scheduled_at: new Date(now.getTime() + 86400000).toISOString(), created_at: now.toISOString() };
const DETAIL = {
  ...SENT, created_by_name: "Ved", agenda: "Site walk", message_body: "Please be on site by 9.", meeting_date: "2026-11-24", meeting_time: "09:00", location_or_link: "Site office",
  delivery_summary: { sent: 1, pending: 0, skipped_no_contact: 1, failed: 0 },
  recipients: [
    { id: "r1", recipient_type: "project_manager", name: "Asha PM", role_label: "Project Manager", channels: ["whatsapp"], phone: "+91 90000", delivery_status: "sent" },
    { id: "r2", recipient_type: "vendor", name: "Ravi", role_label: "Main Vendor", company_name: "Ravi Electricals", channels: [], delivery_status: "skipped_no_contact" },
  ],
};
const TEMPLATE = { id: "t1", name: "Weekly site review", title: "Weekly review", agenda: "", message_body: "Review at 5pm." };

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/?tab=broadcasts");
  broadcastApi.summary.mockResolvedValue({ messages_sent: 2, total_recipients: 5, delivery_success_rate: 80, scheduled: 1, failed: 0 });
  broadcastApi.list.mockImplementation(({ status }) => Promise.resolve(status === "scheduled" ? [SCHEDULED] : [SENT, FAILED, SCHEDULED]));
  broadcastApi.detail.mockImplementation(id => Promise.resolve(id === "b3" ? { ...SCHEDULED, recipients: [], delivery_summary: {} } : DETAIL));
  broadcastApi.templates.mockResolvedValue([TEMPLATE]);
  broadcastApi.recipients.mockResolvedValue({ counts: { project_manager: 1, vendor: 1 }, recipients: DETAIL.recipients.map(item => ({ ...item, key: item.id })) });
  projectsApi.list.mockResolvedValue([{ id: "p1", name: "Main office interiors", code: "PRJ-1" }]);
});

const okAction = () => vi.fn(async operation => { await operation(); return { ok: true }; });
const list = () => within(screen.getByRole("region", { name: "Messages" }));

describe("Communication", () => {
  it("summarises the activity in one line and counts each section", async () => {
    render(<CommunicationPage action={okAction()}/>);
    expect(await screen.findByText("2 messages sent, reached 5 people, 80% delivered, 1 scheduled")).toBeInTheDocument();
    const nav = within(screen.getByRole("navigation", { name: "Communication sections" }));
    expect(nav.getByRole("button", { name: "Sent 2" })).toHaveAttribute("aria-current", "page");
    expect(await nav.findByRole("button", { name: "Templates 1" })).toBeInTheDocument();
  });

  it("lists sent messages by day, without the scheduled ones", async () => {
    render(<CommunicationPage action={okAction()}/>);
    expect(await list().findByRole("button", { name: "Open Hey everyone" })).toBeInTheDocument();
    expect(list().getByText("Today")).toBeInTheDocument();
    expect(list().queryByRole("button", { name: "Open Monday kickoff" })).toBeNull();
  });

  it("opens a message to read it, with delivery and recipients by group", async () => {
    render(<CommunicationPage action={okAction()}/>);
    fireEvent.click(await list().findByRole("button", { name: "Open Hey everyone" }));
    const message = within(await screen.findByRole("article", { name: "Message - Hey everyone" }));
    expect(message.getByText("Please be on site by 9.")).toBeInTheDocument();
    expect(message.getByText("Site walk")).toBeInTheDocument();
    expect(message.getByText("Site office")).toBeInTheDocument();
    expect(message.getByRole("img", { name: "1 delivered, 1 no contact" })).toBeInTheDocument();
    expect(message.getByRole("region", { name: "Project managers" })).toBeInTheDocument();
    expect(window.location.search).toContain("broadcast=b1");

    fireEvent.click(message.getByLabelText(/Not delivered only/));
    expect(message.queryByText("Asha PM")).toBeNull();
    expect(message.getByText("Ravi")).toBeInTheDocument();
  });

  it("filters sent messages by outcome with chips that only exist when needed", async () => {
    render(<CommunicationPage action={okAction()}/>);
    const chips = within(await list().findByRole("group", { name: "Delivery status" }));
    expect(chips.queryByRole("button", { name: /^Failed/ })).toBeNull();
    fireEvent.click(chips.getByRole("button", { name: "Partly failed 1" }));
    expect(list().queryByRole("button", { name: "Open Hey everyone" })).toBeNull();
    expect(list().getByRole("button", { name: "Open Weekly review" })).toBeInTheDocument();
  });

  it("sends a scheduled message early from its reading pane", async () => {
    const action = okAction();
    render(<CommunicationPage action={action}/>);
    fireEvent.click(await screen.findByRole("button", { name: /^Scheduled/ }));
    fireEvent.click(await list().findByRole("button", { name: "Open Monday kickoff" }));
    const message = within(await screen.findByRole("article", { name: "Message - Monday kickoff" }));
    fireEvent.click(message.getByRole("button", { name: "Send now" }));
    await waitFor(() => expect(broadcastApi.send).toHaveBeenCalledWith("b3"));
  });

  it("starts a broadcast from a template and previews it live", async () => {
    render(<CommunicationPage action={okAction()}/>);
    fireEvent.click(await screen.findByRole("button", { name: /^Templates/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Use template" }));
    const dialog = within(screen.getByRole("dialog", { name: "New broadcast" }));
    expect(dialog.getByLabelText("Title")).toHaveValue("Weekly review");
    const preview = within(dialog.getByLabelText("Message preview"));
    expect(preview.getByText("Review at 5pm.")).toBeInTheDocument();
    fireEvent.change(dialog.getByLabelText("Message body"), { target: { value: "Moved to 6pm." } });
    expect(preview.getByText("Moved to 6pm.")).toBeInTheDocument();
  });

  it("sends to the selected groups and names the audience on the button", async () => {
    const action = okAction();
    broadcastApi.create.mockResolvedValue({});
    render(<CommunicationPage action={action}/>);
    fireEvent.click(screen.getByRole("button", { name: "New broadcast" }));
    const dialog = within(screen.getByRole("dialog", { name: "New broadcast" }));
    fireEvent.click(dialog.getByRole("button", { name: /^Send to/ }));
    expect(dialog.getByRole("alert")).toHaveTextContent("Select a project to message.");

    await waitFor(() => expect(dialog.getByRole("option", { name: "Main office interiors" })).toBeInTheDocument());
    fireEvent.change(dialog.getByLabelText("Which project team?"), { target: { value: "p1" } });
    expect(await dialog.findByRole("button", { name: "Send to 2 people" })).toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: /^Vendors/ }));
    fireEvent.change(dialog.getByLabelText("Title"), { target: { value: "Hello" } });
    fireEvent.change(dialog.getByLabelText("Message body"), { target: { value: "Body" } });
    fireEvent.click(dialog.getByRole("button", { name: "Send to 1 person" }));
    await waitFor(() => expect(broadcastApi.create).toHaveBeenCalled());
    expect(broadcastApi.create.mock.calls[0][0].recipient_groups).not.toContain("vendor");
  });

  it("asks before deleting a template", async () => {
    broadcastApi.deleteTemplate.mockResolvedValue({ ok: true });
    render(<CommunicationPage action={okAction()}/>);
    fireEvent.click(await screen.findByRole("button", { name: /^Templates/ }));
    fireEvent.click(await screen.findByRole("button", { name: "More actions for Weekly site review" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete template" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Delete template?" })).getByRole("button", { name: "Delete template" }));
    await waitFor(() => expect(broadcastApi.deleteTemplate).toHaveBeenCalledWith("t1"));
  });
});

describe("broadcast helpers", () => {
  it("labels days relative to now", () => {
    const base = new Date("2026-11-23T12:00:00").getTime();
    expect(dayLabel("2026-11-23T08:00:00", base)).toBe("Today");
    expect(dayLabel("2026-11-22T23:00:00", base)).toBe("Yesterday");
    expect(dayLabel("2026-11-24T09:00:00", base)).toBe("Tomorrow");
  });

  it("groups newest first, or soonest first for scheduled", () => {
    const base = new Date("2026-11-23T12:00:00").getTime();
    const items = [{ id: "a", sent_at: "2026-11-22T10:00:00" }, { id: "b", sent_at: "2026-11-23T10:00:00" }, { id: "c", sent_at: "2026-11-23T11:00:00" }];
    expect(groupByDay(items, { now: base }).map(group => [group.label, group.items.map(item => item.id)])).toEqual([["Today", ["c", "b"]], ["Yesterday", ["a"]]]);
    expect(groupByDay(items, { now: base, ascending: true })[0].items[0].id).toBe("a");
  });

  it("writes the header line and invites a first send when empty", () => {
    expect(summaryLine({ messages_sent: 1, failed: 0, total_recipients: 1, delivery_success_rate: 100, scheduled: 0 })).toBe("1 message sent, reached 1 person, 100% delivered");
    expect(summaryLine({ messages_sent: 0, failed: 0, scheduled: 0 })).toMatch(/Nothing sent yet/);
  });
});
