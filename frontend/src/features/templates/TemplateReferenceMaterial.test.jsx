import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDraftEditorEntry } from "./components/TemplateDraftEditorEntry";

vi.mock("../../api/templatesApi", () => ({ templatesApi: {
  getVersion: vi.fn(), listTasks: vi.fn(), listDependencies: vi.fn(), listGates: vi.fn(),
  createTask: vi.fn(), updateTask: vi.fn(), createGate: vi.fn(), updateGate: vi.fn(), configureGateMappings: vi.fn(),
  addReferenceFile: vi.fn(), removeReferenceFile: vi.fn(), downloadReferenceFile: vi.fn(),
} }));

const summary = { version_id: "draft-1", template_code: "FIT", template_name: "Fitout", version_no: 2, status: "draft", duration_days: 45, updated_at: "2026-10-07T10:00:00Z", revision_token: "rev-1" };
const spec = { id: "r1", file_id: "f1", filename: "flooring-spec.pdf", mime_type: "application/pdf", size_bytes: 2048, description: "Approved spec" };
const task = { id: "task-1", code: "T001", sequence_no: 1, title: "Floor levelling", description: null, schedule_classification: "execution", planned_start_day: 1, planned_end_day: 2, phase: "Flooring", category: "Flooring", applicability: "mandatory", task_class: null, task_kind: null, evidence_required: true, evidence_instructions: null, reference_files: [spec], duration_days: 2 };
const gate = { id: "gate-1", code: "E001", approval_name: "Fire NOC", description: null, external_party: "Government Authority", required_by_type: null, required_by_value: null, impact: null, evidence_instructions: null, reference_files: [], sequence_no: 1, mapping_classification: "unmapped", broad_mapping_text: null, requires_configuration: true, affected_tasks: [] };
const page = items => ({ items, pagination: { page: 1, page_size: 100, total: items.length, total_pages: items.length ? 1 : 0 } });
const pdf = (name = "method.pdf", size = 20) => new File([new Uint8Array(size)], name, { type: "application/pdf" });

function view() { return render(<TemplateDraftEditorEntry summary={summary} user={{ role: "admin" }} onBack={vi.fn()}/>); }
async function openTask() {
  fireEvent.click((await screen.findAllByRole("button", { name: "Edit T001" }))[0]);
  return screen.getByRole("dialog", { name: /edit task/i });
}
async function openGate() {
  await screen.findByTestId("draft-task-T001");
  fireEvent.click(screen.getByRole("button", { name: /prerequisite approvals/i }));
  fireEvent.click((await screen.findAllByRole("button", { name: "Edit approval E001" }))[0]);
  return screen.getByRole("dialog", { name: /edit prerequisite approval/i });
}

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(summary);
  templatesApi.listTasks.mockResolvedValue(page([task]));
  templatesApi.listDependencies.mockResolvedValue(page([]));
  templatesApi.listGates.mockResolvedValue(page([gate]));
  templatesApi.updateTask.mockResolvedValue({ task, revision_token: "rev-2" });
  templatesApi.updateGate.mockResolvedValue({ gate, revision_token: "rev-2" });
  templatesApi.addReferenceFile.mockResolvedValue({ reference: { id: "r2", file_id: "f2", filename: "method.pdf", mime_type: "application/pdf", size_bytes: 20, description: "Method statement" }, revision_token: "rev-3" });
  templatesApi.removeReferenceFile.mockResolvedValue({ reference_id: "r1", deleted: true, revision_token: "rev-4" });
});

describe("task reference material", () => {
  it("saves 'What proof is needed?' with the task", async () => {
    view();
    const dialog = await openTask();
    fireEvent.change(within(dialog).getByLabelText("What proof is needed?"), { target: { value: "Photos from two corners" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /save task/i }));
    await waitFor(() => expect(templatesApi.updateTask).toHaveBeenCalledWith("draft-1", "task-1", expect.objectContaining({ evidence_instructions: "Photos from two corners" })));
  });

  it("lists, uploads and removes reference files on a saved task", async () => {
    view();
    const dialog = await openTask();
    const section = within(dialog).getByRole("group", { name: "Reference material" });
    expect(within(section).getByText("flooring-spec.pdf")).toBeInTheDocument();
    expect(within(section).getByText("Approved spec")).toBeInTheDocument();

    fireEvent.change(within(section).getByLabelText("Reference file"), { target: { files: [pdf()] } });
    fireEvent.change(within(section).getByLabelText("File description (optional)"), { target: { value: "Method statement" } });
    fireEvent.click(within(section).getByRole("button", { name: /upload/i }));
    await waitFor(() => expect(templatesApi.addReferenceFile).toHaveBeenCalledWith("draft-1", "tasks", "task-1",
      expect.objectContaining({ description: "Method statement", revisionToken: "rev-1" })));
    expect(await within(section).findByText("method.pdf")).toBeInTheDocument();

    fireEvent.click(within(section).getByRole("button", { name: "Remove flooring-spec.pdf" }));
    // The upload moved the draft on, so removal sends the newer revision.
    await waitFor(() => expect(templatesApi.removeReferenceFile).toHaveBeenCalledWith("draft-1", "tasks", "task-1", "r1", "rev-3"));
    await waitFor(() => expect(within(section).queryByText("flooring-spec.pdf")).not.toBeInTheDocument());
  });

  it("refuses unsupported or oversized files before uploading", async () => {
    view();
    const section = within(await openTask()).getByRole("group", { name: "Reference material" });
    fireEvent.change(within(section).getByLabelText("Reference file"), { target: { files: [new File(["x"], "tool.exe")] } });
    expect(await within(section).findByRole("alert")).toHaveTextContent(/must be PDF, JPG, PNG, WebP, DOCX or XLSX/);
    fireEvent.change(within(section).getByLabelText("Reference file"), { target: { files: [pdf("huge.pdf", 10 * 1024 * 1024 + 1)] } });
    expect(within(section).getByRole("alert")).toHaveTextContent(/10 MB or smaller/);
    expect(within(section).getByRole("button", { name: /upload/i })).toBeDisabled();
    expect(templatesApi.addReferenceFile).not.toHaveBeenCalled();
  });

  it("attaches files while creating a task and uploads them as part of Save", async () => {
    const created = { ...task, id: "task-2", code: "T002", title: "Ceiling grid", reference_files: [] };
    templatesApi.createTask.mockResolvedValue({ task: created, revision_token: "rev-2" });
    view();
    await screen.findByTestId("draft-task-T001");
    fireEvent.click(screen.getByRole("button", { name: /add task/i }));
    const dialog = screen.getByRole("dialog", { name: /add task/i });
    expect(within(dialog).queryByText(/save the task first/i)).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Task name"), { target: { value: "Ceiling grid" } });
    fireEvent.change(within(dialog).getByLabelText("Starts on day"), { target: { value: "3" } });
    fireEvent.change(within(dialog).getByLabelText("Ends on day"), { target: { value: "4" } });
    fireEvent.change(within(dialog).getByLabelText(/attach reference files/i), { target: { files: [pdf("grid-layout.pdf")] } });
    fireEvent.change(within(dialog).getByLabelText("Note for grid-layout.pdf"), { target: { value: "Approved layout" } });
    const buttons = within(dialog).getAllByRole("button", { name: /^add task$/i });
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(templatesApi.createTask).toHaveBeenCalled());
    // Uploaded to the new task, with the revision the create returned.
    await waitFor(() => expect(templatesApi.addReferenceFile).toHaveBeenCalledWith("draft-1", "tasks", "task-2",
      expect.objectContaining({ description: "Approved layout", revisionToken: "rev-2" })));
  });

  it("won't take an unsupported file in the new-task picker", async () => {
    view();
    await screen.findByTestId("draft-task-T001");
    fireEvent.click(screen.getByRole("button", { name: /add task/i }));
    const dialog = screen.getByRole("dialog", { name: /add task/i });
    fireEvent.change(within(dialog).getByLabelText(/attach reference files/i), { target: { files: [new File(["x"], "tool.exe")] } });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/tool.exe: Reference files must be PDF/);
    expect(within(dialog).queryByLabelText("Note for tool.exe")).not.toBeInTheDocument();
  });
});

describe("prerequisite approval reference material", () => {
  it("saves 'What proof is needed?' and uploads files for the approval", async () => {
    view();
    const dialog = await openGate();
    fireEvent.change(within(dialog).getByLabelText("What proof is needed?"), { target: { value: "Stamped NOC copy" } });
    const section = within(dialog).getByRole("group", { name: "Reference material" });
    fireEvent.change(within(section).getByLabelText("Reference file"), { target: { files: [pdf("noc-form.pdf")] } });
    fireEvent.click(within(section).getByRole("button", { name: /upload/i }));
    await waitFor(() => expect(templatesApi.addReferenceFile).toHaveBeenCalledWith("draft-1", "gates", "gate-1", expect.objectContaining({ revisionToken: "rev-1" })));
    fireEvent.click(within(dialog).getByRole("button", { name: /save approval/i }));
    await waitFor(() => expect(templatesApi.updateGate).toHaveBeenCalledWith("draft-1", "gate-1", { revision_token: "rev-3", evidence_instructions: "Stamped NOC copy" }));
  });
});
