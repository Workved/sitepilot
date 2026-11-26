import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { snagsApi } from "../../api/snagsApi";
import { resetPeopleCache } from "./SnagItem";
import { SnagList } from "./SnagList";
import { TaggedToYou } from "./TaggedToYou";
import { dueLabel, filterSnags, snagSummary, sortSnags } from "./snagHelpers";

vi.mock("../../api/snagsApi", () => ({
  snagsApi: {
    list: vi.fn(), create: vi.fn(), update: vi.fn(), setStatus: vi.fn(), remove: vi.fn(), taggedToMe: vi.fn(), people: vi.fn(),
    addFile: vi.fn(), downloadFile: vi.fn(), removeFile: vi.fn(),
  },
}));

const ME = { id: "u-sup", name: "Sam Supervisor", role: "supervisor" };
const PM = { id: "u-pm", name: "Priya PM", role: "project_manager", role_label: "Project Manager" };
const person = user => ({ ...user, role_label: user.role_label || "Supervisor" });
const snag = overrides => ({
  id: overrides.id, project_id: "p1", project_name: "Tower A", project_code: "P-1", title: overrides.title, area: null, notes: null,
  due_date: null, urgent: false, status: "open", assignee: null, created_by: person(ME), created_at: "2026-11-25T10:00:00Z",
  closed_at: null, closed_by: null, closing_note: null, files: [],
  can_edit: true, can_close: true, can_attach: true, can_delete: true, can_open_project: true, ...overrides,
});
const ITEMS = [
  snag({ id: "s1", title: "Touch up paint", area: "Cabin 3", assignee: person(ME) }),
  snag({ id: "s2", title: "Replace switch plate", urgent: true, assignee: person(PM) }),
  snag({ id: "s3", title: "Clean grout", status: "done", closed_at: "2026-11-25T12:00:00Z", closed_by: person(ME) }),
];

beforeEach(() => {
  vi.clearAllMocks();
  resetPeopleCache();
  snagsApi.list.mockResolvedValue({ project_id: "p1", can_add: true, read_only: false, items: ITEMS });
  snagsApi.people.mockResolvedValue([person(ME), PM]);
});

const openList = () => within(screen.getByRole("region", { name: "Open snags" }));

describe("Snag list", () => {
  it("summarises and lists open snags, urgent first", async () => {
    render(<SnagList projectId="p1" user={ME}/>);
    expect(await screen.findByText("2 open · 1 urgent · 1 done")).toBeInTheDocument();
    const titles = openList().getAllByRole("button", { name: /^Mark .* done$/ }).map(button => button.getAttribute("aria-label"));
    expect(titles).toEqual(["Mark Replace switch plate done", "Mark Touch up paint done"]);
  });

  it("adds a snag with just a title and Enter", async () => {
    snagsApi.create.mockResolvedValue(snag({ id: "s9", title: "Fix door closer" }));
    render(<SnagList projectId="p1" user={ME}/>);
    const input = await screen.findByLabelText("New snag");
    fireEvent.change(input, { target: { value: "Fix door closer" } });
    fireEvent.submit(input.closest("form"));
    await waitFor(() => expect(snagsApi.create).toHaveBeenCalledWith("p1", expect.objectContaining({ title: "Fix door closer", urgent: false, assignee_user_id: null })));
    expect(await openList().findByText("Fix door closer")).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("ticks a snag off into Done", async () => {
    snagsApi.setStatus.mockResolvedValue({ ...ITEMS[0], status: "done", closed_at: "2026-11-26T09:00:00Z", closed_by: person(ME) });
    render(<SnagList projectId="p1" user={ME}/>);
    fireEvent.click(await screen.findByRole("button", { name: "Mark Touch up paint done" }));
    await waitFor(() => expect(snagsApi.setStatus).toHaveBeenCalledWith("s1", "done", undefined));
    expect(await screen.findByRole("button", { name: "Done 2" })).toBeInTheDocument();
  });

  it("tags someone from the people picker", async () => {
    snagsApi.update.mockResolvedValue({ ...ITEMS[0], assignee: PM });
    render(<SnagList projectId="p1" user={ME}/>);
    fireEvent.click(await screen.findByText("Touch up paint"));
    fireEvent.click(screen.getByRole("button", { name: /Sam Supervisor/ }));
    fireEvent.click(await screen.findByRole("option", { name: /Priya PM/ }));
    await waitFor(() => expect(snagsApi.update).toHaveBeenCalledWith("s1", { assignee_user_id: "u-pm" }));
  });

  it("filters to snags tagged to me", async () => {
    render(<SnagList projectId="p1" user={ME}/>);
    fireEvent.click(await screen.findByRole("button", { name: "Tagged to me 1" }));
    expect(openList().queryByText("Replace switch plate")).toBeNull();
    expect(openList().getByText("Touch up paint")).toBeInTheDocument();
  });

  it("locks the fields someone may not edit but still lets them attach", async () => {
    snagsApi.list.mockResolvedValue({ project_id: "p1", can_add: true, read_only: false, items: [snag({ id: "s1", title: "Touch up paint", notes: "Use the store paint", can_edit: false, can_delete: false })] });
    render(<SnagList projectId="p1" user={ME}/>);
    fireEvent.click(await screen.findByText("Touch up paint"));
    expect(screen.getByLabelText("Notes")).toBeDisabled();
    expect(screen.getAllByText("Not set").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Title")).toBeNull();
    expect(screen.getByRole("button", { name: /Attach a photo or file/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull();
  });

  it("is read-only on archived projects", async () => {
    snagsApi.list.mockResolvedValue({ project_id: "p1", can_add: false, read_only: true, items: [] });
    render(<SnagList projectId="p1" user={ME}/>);
    expect(await screen.findByText(/archived/)).toBeInTheDocument();
    expect(screen.queryByLabelText("New snag")).toBeNull();
  });
});

describe("Tagged to you", () => {
  it("lists my open snags across projects and ticks them off", async () => {
    const onChange = vi.fn();
    snagsApi.setStatus.mockResolvedValue({ ...ITEMS[0], status: "done" });
    render(<TaggedToYou snags={[ITEMS[0]]} onChange={onChange}/>);
    const card = within(screen.getByRole("region", { name: "Tagged to you" }));
    expect(card.getByText("Tower A · Cabin 3")).toBeInTheDocument();
    fireEvent.click(card.getByRole("button", { name: "Mark Touch up paint done" }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ status: "done" })));
  });

  it("opens the full snag even when the project can't be opened", () => {
    render(<TaggedToYou snags={[{ ...ITEMS[0], can_open_project: false, notes: "Use the leftover paint in store." }]} onChange={vi.fn()}/>);
    fireEvent.click(screen.getByText("Touch up paint"));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByDisplayValue("Use the leftover paint in store.")).toBeInTheDocument();
    expect(dialog.queryByRole("button", { name: "Tower A" })).toBeNull();
  });

  it("renders nothing when nothing is tagged", () => {
    const { container } = render(<TaggedToYou snags={[]} onChange={vi.fn()}/>);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("snag helpers", () => {
  const today = "2026-11-26";
  it("orders urgent, then overdue, then by due date", () => {
    const items = [
      snag({ id: "a", title: "later", due_date: "2026-12-10" }),
      snag({ id: "b", title: "overdue", due_date: "2026-11-20" }),
      snag({ id: "c", title: "urgent", urgent: true }),
    ];
    expect(sortSnags(items, today).open.map(item => item.id)).toEqual(["c", "b", "a"]);
  });

  it("labels due dates and counts the summary", () => {
    expect(dueLabel(snag({ id: "x", title: "x", due_date: "2026-11-20" }), today)).toBe("Overdue · 20 Nov");
    expect(dueLabel(snag({ id: "x", title: "x", due_date: today }), today)).toBe("Due today");
    expect(snagSummary([snag({ id: "x", title: "x", due_date: "2026-11-20" })], today)).toMatchObject({ open: 1, overdue: 1 });
    expect(filterSnags(ITEMS, { query: "cabin" }).map(item => item.id)).toEqual(["s1"]);
  });
});

describe("Tagged to you dialog", () => {
  it("stays open after closing the last open snag", async () => {
    let snags = [ITEMS[0]];
    snagsApi.setStatus.mockResolvedValue({ ...ITEMS[0], status: "done", closed_at: "2026-11-26T09:00:00Z", closed_by: person(ME) });
    const { rerender } = render(<TaggedToYou snags={snags} onChange={updated => { snags = [updated]; }}/>);
    fireEvent.click(screen.getByText("Touch up paint"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Mark Touch up paint done" }));
    await waitFor(() => expect(snagsApi.setStatus).toHaveBeenCalled());
    rerender(<TaggedToYou snags={snags} onChange={vi.fn()}/>);
    expect(within(screen.getByRole("dialog")).getAllByText(/Done by Sam Supervisor/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("region", { name: "Tagged to you" })).toBeNull();
  });
});
