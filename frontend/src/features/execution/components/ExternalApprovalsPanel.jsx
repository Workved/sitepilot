import { createPortal } from "react-dom";
import {
  AlertTriangle, ArrowRight, ClipboardCheck, ClipboardList, Edit3, Paperclip,
  Repeat, RotateCcw, Search, Send, ShieldAlert, ShieldCheck, UserPlus, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, Field, Input, LoadingSpinner, Modal, Pill, Select, Textarea } from "../../../components/ui";
import { formatDateShort, initials } from "../../../utils/format";
import { ReferenceMaterial } from "./ReferenceMaterial";

// Plan: External Approval Gate Assignment & Evidence Lifecycle (U6), redesigned
// as "External Approvals Control" - an Admin + Internal Employee workflow only
// (Admin assigns -> Internal Employee updates/submits -> Admin reviews ->
// Admin approves / sends back / reassigns). No PM or Supervisor label or
// action appears anywhere below; those roles keep only the pre-existing
// read-only visibility `ProjectGateDecisionService.list_for_project` already
// grants any active project member (a Supervisor needs to see what's holding
// up their site) - unchanged here since narrowing that is a backend/role
// decision outside this tab's scope, not a UI one.
//
// Reads the EXECUTION-layer approvals (U8 instantiates them at activation,
// U11/U5 decides them), not the planning-layer gates this tab used to show.
// The lifecycle is unassigned -> assigned -> submitted -> approved | rejected,
// with rejection looping back to assigned for the SAME assignee to resubmit
// (R4) - there is no separate "request changes" decision on the backend, and
// no terminal "rejected" state ever observably rests at rest (see the Reject
// action below). Admin exclusively assigns/reassigns/unassigns and decides
// (R1/R3/R6, no PM-fallback tier); the assignee exclusively submits evidence
// (R2).

function isPlatformAdmin(user) {
  return user?.role === "admin" || user?.role === "super_admin";
}
function isEmployee(user) {
  return user?.role === "internal_employee";
}
// Mirrors ProjectGateDecisionService._require_approver / _require_assigner
// exactly: Admin-only, no PM-fallback tier for this flow (R1/R3/R6).
function canManage(user) {
  return isPlatformAdmin(user);
}
function isAssignee(approval, user) {
  return !!user && approval.assigned_to_user_id === user.id;
}

// ---- status / coverage presentation --------------------------------------
//
// The API only ever persists status in {unassigned, assigned, submitted,
// approved} through this UI's own actions - `decide()`'s "rejected" branch
// writes it transiently and loops back to `assigned` with `rejection_reason`
// populated inside the SAME request, so a resting "rejected" row is never
// observed here. "Changes Requested" below is that real, persisted signal
// (assigned + a rejection_reason left over from the bounce), not a fabricated
// state.
function statusMeta(approval) {
  if (approval.status === "unassigned") return { label: "Unassigned", tone: "gray" };
  if (approval.status === "assigned") {
    return approval.rejection_reason
      ? { label: "Changes Requested", tone: "orange" }
      : { label: "Assigned", tone: "blue" };
  }
  if (approval.status === "submitted") return { label: "Submitted for Review", tone: "yellow" };
  if (approval.status === "approved") return { label: "Approved", tone: "green" };
  if (approval.status === "rejected") return { label: "Rejected", tone: "red" };
  return { label: approval.status, tone: "gray" };
}

// A blocking approval that has already been approved no longer blocks
// anything - task_readiness.py treats `status == "approved"` as satisfied
// regardless of the `blocking` flag - so "still blocking" excludes it.
function stillBlocking(approval) {
  return approval.blocking && approval.status !== "approved";
}

// Local calendar date as YYYY-MM-DD - what a date input's `min` expects.
function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

// The gate's deadline (set when it was assigned), flagged once it has passed
// without the approval being granted. Older gates without one show "—".
function DueDate({ approval }) {
  if (!approval.due_at) return <span className="text-sm font-medium text-slate-400">—</span>;
  const overdue = approval.status !== "approved" && approval.due_at < todayIso();
  return <span className="flex flex-wrap items-center gap-1.5">
    <span className={`text-sm font-bold ${overdue ? "text-rose-700" : "text-slate-800"}`}>{formatDateShort(approval.due_at)}</span>
    {overdue && <Pill tone="red">Overdue</Pill>}
  </span>;
}

const STATUS_SORT_RANK = { submitted: 0, unassigned: 1, assigned: 2, rejected: 2, approved: 3 };
function sortApprovals(approvals) {
  return [...approvals].sort((a, b) => {
    const rank = (STATUS_SORT_RANK[a.status] ?? 9) - (STATUS_SORT_RANK[b.status] ?? 9);
    return rank !== 0 ? rank : a.gate_code.localeCompare(b.gate_code);
  });
}

const STATUS_FILTERS = [
  ["all", "All", () => true],
  ["unassigned", "Unassigned", a => a.status === "unassigned"],
  ["assigned", "Assigned", a => a.status === "assigned"],
  ["in_progress", "In Progress", a => a.status === "assigned" && !a.rejection_reason],
  ["submitted", "Submitted", a => a.status === "submitted"],
  ["approved", "Approved", a => a.status === "approved"],
  ["changes_requested", "Request Changes", a => a.status === "assigned" && !!a.rejection_reason],
  ["blocking", "Blocking", stillBlocking],
  ["coverage_unresolved", "Coverage Unresolved", a => a.coverage_state === "unresolved"],
];

const COVERAGE_FILTERS = [
  ["all", "All coverage", () => true],
  ["has", "Has covered tasks", a => a.coverage_state === "exact" && a.covered_task_ids.length > 0],
  ["none", "No covered tasks", a => a.coverage_state === "exact" && a.covered_task_ids.length === 0],
  ["unresolved", "Coverage unresolved", a => a.coverage_state === "unresolved"],
];

const PAGE_SIZE = 6;

const WORKFLOW_STEPS = [
  { title: "Admin Assigns", desc: "Admin assigns approval to an internal employee.", Icon: UserPlus },
  { title: "Employee Updates", desc: "Internal employee follows up and uploads evidence.", Icon: Edit3 },
  { title: "Submitted to Admin", desc: "Employee submits update for admin review.", Icon: Send },
  { title: "Admin Review", desc: "Admin approves, requests changes, rejects, or reassigns.", Icon: ShieldCheck },
];

function EmployeeAvatar({ name, className = "" }) {
  return <span className={`grid size-7 shrink-0 place-items-center rounded-full bg-blue-100 text-xs font-medium text-blue-700 ${className}`}>{initials(name)}</span>;
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ---- workflow strip -------------------------------------------------------

// The four-step process, folded away: useful the first time, noise after.
function WorkflowStrip() {
  return <details className="group rounded-[20px] border border-line bg-white">
    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 text-sm text-slate-700">
      How external approvals work
      <ArrowRight size={15} className="text-slate-400 transition group-open:rotate-90" aria-hidden="true"/>
    </summary>
    <ol className="grid gap-3 border-t border-line p-5 sm:grid-cols-2 lg:grid-cols-4">
      {WORKFLOW_STEPS.map(({ title, desc }, index) => <li key={title} className="flex gap-3">
        <span className="grid size-6 shrink-0 place-items-center rounded-full bg-slate-100 text-xs tabular-nums text-slate-600">{index + 1}</span>
        <span className="min-w-0">
          <span className="block text-sm text-slate-950">{title}</span>
          <span className="mt-0.5 block text-xs leading-5 text-slate-500">{desc}</span>
        </span>
      </li>)}
    </ol>
  </details>;
}

// ---- KPI cards --------------------------------------------------------

const KPI_EDGE = { blue: "var(--color-blue-600)", gray: "var(--color-slate-300)", orange: "var(--color-behind)", red: "#d9483b", green: "var(--color-ok)" };

// Coloured edge, label and a big light number - the same tile as StatStrip.
// A zero greys out so the eye goes to what is actually non-zero.
function KpiCard({ tone, label, value, helper }) {
  return <article title={helper} className="flex items-center gap-3 rounded-2xl border border-line bg-white px-4 py-3.5">
    <span className="h-8 w-1.5 shrink-0 rounded" style={{ background: value ? KPI_EDGE[tone] : "var(--color-slate-200)" }} aria-hidden="true"/>
    <p className="min-w-0 flex-1 truncate text-sm text-slate-950">{label}</p>
    <strong className={`text-2xl font-light tabular-nums leading-none ${value ? "text-slate-950" : "text-slate-400"}`}>{value ?? "—"}</strong>
  </article>;
}

function KpiCards({ approvals }) {
  const counts = useMemo(() => ({
    total: approvals.length,
    unassigned: approvals.filter(a => a.status === "unassigned").length,
    assigned: approvals.filter(a => a.status === "assigned").length,
    submitted: approvals.filter(a => a.status === "submitted").length,
    blocking: approvals.filter(stillBlocking).length,
    approved: approvals.filter(a => a.status === "approved").length,
  }), [approvals]);

  const cards = [
    ["total", "Total Approvals", "blue", "All external approvals on this project", counts.total],
    ["unassigned", "Unassigned", "gray", "Not yet given to an employee", counts.unassigned],
    ["assigned", "Assigned / In Progress", "blue", "With an internal employee", counts.assigned],
    ["submitted", "Submitted for Review", "orange", "Waiting on Admin", counts.submitted],
    ["blocking", "Blocking", "red", "Still holding up covered tasks", counts.blocking],
    ["approved", "Approved", "green", "Granted by Admin", counts.approved],
  ];

  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" role="group" aria-label="External approvals summary">
    {cards.map(([key, label, tone, helper, value]) => <KpiCard key={key} tone={tone} label={label} helper={helper} value={value}/>)}
  </div>;
}

// ---- filter bar -------------------------------------------------------

const SELECT_CLASS = "h-9 rounded-lg border bg-white px-2.5 text-sm outline-none focus:border-blue-600";
const selectTone = active => active ? "border-slate-950 text-slate-950" : "border-slate-200 text-slate-700";

function FilterBar({ search, setSearch, statusFilter, setStatusFilter, employeeFilter, setEmployeeFilter, coverageFilter, setCoverageFilter, employees, showEmployeeFilter, onReset, filtersActive }) {
  return <div className="flex flex-wrap items-center gap-2 rounded-[20px] border border-line bg-white p-2">
    <label className="relative min-w-[220px] flex-1">
      <span className="sr-only">Search approvals</span>
      <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
      <input value={search} onChange={event => setSearch(event.target.value)} autoComplete="off" placeholder="Search by approval code or title"
        className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-950 outline-none placeholder:text-slate-400 focus:border-blue-600 focus:bg-white"/>
    </label>
    <select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} aria-label="Filter by status" className={`${SELECT_CLASS} ${selectTone(statusFilter !== "all")}`}>
      {STATUS_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select>
    {showEmployeeFilter && <select value={employeeFilter} onChange={event => setEmployeeFilter(event.target.value)} aria-label="Filter by internal employee" className={`${SELECT_CLASS} ${selectTone(employeeFilter !== "all")}`}>
      <option value="all">All employees</option>
      {employees.map(candidate => <option key={candidate.user_id} value={candidate.user_id}>{candidate.name}</option>)}
    </select>}
    <select value={coverageFilter} onChange={event => setCoverageFilter(event.target.value)} aria-label="Filter by coverage" className={`${SELECT_CLASS} ${selectTone(coverageFilter !== "all")}`}>
      {COVERAGE_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select>
    {filtersActive && <button type="button" onClick={onReset} className="inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-950">
      <RotateCcw size={14}/> Reset
    </button>}
  </div>;
}

// ---- table --------------------------------------------------------------

function CoverageCell({ approval }) {
  if (approval.coverage_state === "unresolved") {
    return <div className="grid gap-1">
      <Pill tone="violet"><AlertTriangle size={12}/> Coverage unresolved</Pill>
      {approval.coverage_text && <p className="max-w-[220px] truncate text-xs text-slate-400" title={approval.coverage_text}>{approval.coverage_text}</p>}
    </div>;
  }
  const count = approval.covered_task_ids.length;
  return <div className="grid gap-1">
    <span className="text-sm font-bold text-slate-700">{count} task{count === 1 ? "" : "s"} covered</span>
    {count === 0 && <Pill tone="orange"><AlertTriangle size={12}/> No tasks mapped</Pill>}
  </div>;
}

function actionFor(approval, { mayManage, mine }) {
  if (mayManage) {
    if (approval.status === "unassigned") return { label: "Assign", kind: "assign" };
    if (approval.status === "submitted") return { label: "Review", kind: "select" };
    return { label: "View", kind: "select" };
  }
  if (mine) {
    if (approval.status === "assigned") return { label: "Update", kind: "select" };
    return { label: "View", kind: "select" };
  }
  return { label: "View", kind: "select" };
}

function ApprovalsTable({ approvals, mayManage, user, selectedId, onSelect, onAssign, hasMore, canShowLess, onLoadMore, onShowLess }) {
  if (!approvals.length) return <EmptyState icon={<ClipboardList size={21}/>} title="No approvals match" description="Try a different search or filter."/>;

  return <div className="overflow-hidden rounded-[20px] border border-line bg-white shadow-sm">
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50/80 text-xs font-medium text-slate-500">
          <tr>
            <th className="px-4 py-3">Approval</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Assigned Internal Employee</th>
            <th className="px-4 py-3">Coverage</th>
            <th className="px-4 py-3">Due Date</th>
            <th className="px-4 py-3">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {approvals.map(approval => {
            const meta = statusMeta(approval);
            const mine = isAssignee(approval, user);
            const action = actionFor(approval, { mayManage, mine });
            const active = approval.id === selectedId;
            return <tr
              key={approval.id}
              onClick={() => onSelect(approval.id)}
              className={`cursor-pointer transition ${active ? "bg-blue-50/70" : "hover:bg-slate-50"}`}
            >
              <td className="px-4 py-3 align-top">
                <span className="tabular-nums text-xs font-medium text-slate-600">{approval.gate_code}</span>
                <div className="mt-0.5 max-w-[260px] truncate text-sm font-bold text-slate-900">{approval.gate_name}</div>
              </td>
              <td className="px-4 py-3 align-top">
                <div className="flex flex-wrap gap-1">
                  <Pill tone={meta.tone}>{meta.label}</Pill>
                  {stillBlocking(approval) && <Pill tone="red"><ShieldAlert size={12}/> Blocking</Pill>}
                </div>
              </td>
              <td className="px-4 py-3 align-top">
                {approval.assigned_to_name ? <span className="flex items-center gap-2"><EmployeeAvatar name={approval.assigned_to_name}/><span className="text-sm font-bold text-slate-800">{approval.assigned_to_name}</span></span>
                  : <span className="text-sm font-medium text-slate-400">Not assigned</span>}
              </td>
              <td className="px-4 py-3 align-top"><CoverageCell approval={approval}/></td>
              <td className="px-4 py-3 align-top"><DueDate approval={approval}/></td>
              <td className="px-4 py-3 align-top">
                <Button size="sm" variant={action.kind === "assign" ? "primary" : "secondary"} onClick={event => { event.stopPropagation(); if (action.kind === "assign") onAssign(approval); else onSelect(approval.id); }}>
                  {action.label}
                </Button>
              </td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
    {(hasMore || canShowLess) && <div className="flex items-center justify-center gap-3 border-t border-slate-100 px-4 py-3">
      {hasMore && <Button size="sm" variant="secondary" onClick={onLoadMore}>Load More</Button>}
      {canShowLess && <Button size="sm" variant="ghost" onClick={onShowLess}>Show Less</Button>}
    </div>}
  </div>;
}

// ---- assign / reassign modal ----------------------------------------------

function AssignModal({ approval, candidates, title, confirmLabel, onConfirm, onClose }) {
  const [employeeId, setEmployeeId] = useState("");
  // Pre-filled with the gate's current deadline, if any, so a reassign keeps it by default.
  const [dueDate, setDueDate] = useState(approval.due_at || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    if (dueDate && dueDate < todayIso()) {
      setError("The due date cannot be before today.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await onConfirm(employeeId, dueDate || null);
    } catch (caught) {
      // A 409 here specifically means someone else assigned/decided this
      // gate in the interim (single-writer) - surfaced the same as any
      // other refusal, with the message the backend already gives.
      setError(caught?.message || "This assignment could not be recorded.");
      setSubmitting(false);
    }
  }

  return <Modal title={title} subtitle={`${approval.gate_code} - ${approval.gate_name}`} onClose={() => { if (!submitting) onClose(); }} className="sm:max-w-xl">
    <form className="grid gap-4" onSubmit={submit}>
      <Field label="Internal Employee">
        <Select value={employeeId} onChange={event => setEmployeeId(event.target.value)} required>
          <option value="">{candidates.length ? "Select employee" : "No eligible employees on this project"}</option>
          {candidates.map(candidate => <option key={candidate.user_id} value={candidate.user_id}>{candidate.name}</option>)}
        </Select>
      </Field>
      <Field label="Due date" hint="When this approval should be obtained by. Cannot be before today.">
        <Input type="date" value={dueDate} min={todayIso()} onChange={event => setDueDate(event.target.value)}/>
      </Field>
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
      <div className="grid gap-2 sm:grid-cols-2">
        <Button type="button" variant="secondary" disabled={submitting} onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={!employeeId} loading={submitting}>{confirmLabel}</Button>
      </div>
    </form>
  </Modal>;
}

// ---- employee submission form ----------------------------------------------

function SubmissionForm({ projectId, approval, onSubmitted }) {
  const [note, setNote] = useState("");
  const [files, setFiles] = useState([]);
  const [fileError, setFileError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  function pickFiles(event) {
    const chosen = Array.from(event.target.files || []);
    setFiles(chosen);
    // Mirrors the backend allowlist (task_progress.py/project_gate_submission.py)
    // so a disallowed type is caught before the round trip, not just after.
    const disallowed = chosen.find(file => !["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(file.type));
    setFileError(disallowed ? `${disallowed.name} must be JPG, PNG, WebP, or PDF.` : "");
  }

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const formData = new FormData();
      if (note.trim()) formData.append("note", note.trim());
      files.forEach(file => formData.append("evidence", file));
      await taskExecutionApi.submitExternalApprovalEvidence(projectId, approval.id, formData);
      setNote("");
      setFiles([]);
      await onSubmitted();
    } catch (caught) {
      setError(caught?.message || "This submission could not be recorded.");
    } finally {
      setSubmitting(false);
    }
  }

  return <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
    {approval.rejection_reason && <p className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-800">
      Sent back for resubmission: {approval.rejection_reason}
    </p>}
    <h4 className="text-xs font-medium text-emerald-800">Update / submit evidence</h4>
    <form className="mt-3 grid gap-3" onSubmit={submit}>
      <Field label="Update note"><Textarea className="min-h-20" value={note} onChange={event => setNote(event.target.value)} placeholder="Describe what's attached, or any context for Admin"/></Field>
      {/* capture="environment" biases the mobile OS picker to the rear
          camera - PDFs/multi-select still reachable via the same picker's
          "Files" option. */}
      <label className="grid gap-2 text-sm font-bold text-slate-700">Documents or photos (optional)
        <input className="w-full cursor-pointer rounded-xl border border-slate-200 bg-white text-sm font-normal text-slate-600 file:mr-4 file:border-0 file:bg-emerald-700 file:px-3 file:py-2 file:font-bold file:text-white hover:file:bg-emerald-800" type="file" multiple accept="image/jpeg,image/png,image/webp,application/pdf" capture="environment" onChange={pickFiles}/>
      </label>
      {fileError && <p className="text-xs font-bold text-rose-700">{fileError}</p>}
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-bold text-rose-700">{error}</div>}
      <Button type="submit" size="sm" loading={submitting} disabled={!!fileError || (!note.trim() && !files.length)}>Submit for Admin review</Button>
    </form>
  </section>;
}

// ---- submission history (Admin's review context, and everyone's audit trail) --

function SubmissionList({ projectId, approval }) {
  const [error, setError] = useState("");
  const submissions = approval.submissions || [];

  async function download(fileId, filename) {
    setError("");
    try {
      const { blob } = await taskExecutionApi.downloadExternalApprovalEvidence(projectId, approval.id, fileId);
      triggerDownload(blob, filename);
    } catch (caught) {
      setError(caught?.message || "This evidence file could not be downloaded.");
    }
  }

  if (!submissions.length) return <p className="text-sm font-medium text-slate-500">No submission received yet.</p>;

  return <div className="grid gap-2">
    {submissions.map(submission => <article key={submission.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-bold text-slate-500">
        <span>{submission.submitted_by_name || "Unknown"}</span>
        <span>{formatDateShort(submission.submitted_at.slice(0, 10))}</span>
      </div>
      {submission.note && <p className="mt-1 text-slate-700">{submission.note}</p>}
      {submission.evidence.length > 0 && <div className="mt-2 flex flex-wrap gap-2">
        {submission.evidence.map(file => <button key={file.id} type="button" onClick={() => download(file.file_id, file.original_filename)} className="flex items-center gap-1 rounded-md bg-blue-100 px-2 py-1 text-xs font-bold text-blue-700 hover:bg-blue-200">
          <Paperclip size={12}/>{file.original_filename}
        </button>)}
      </div>}
    </article>)}
    {error && <p className="text-xs font-bold text-rose-700">{error}</p>}
  </div>;
}

// ---- Admin decision modal (Approve / Reject-send-back) ---------------------

function DecisionModal({ approval, decision, onConfirm, onClose }) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const rejecting = decision === "rejected";

  async function submit(event) {
    event.preventDefault();
    const cleanReason = reason.trim();
    if (rejecting && !cleanReason) {
      setError("A reason is required to send this back for changes.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await onConfirm(cleanReason || null);
    } catch (caught) {
      setError(caught?.message || "This decision could not be recorded.");
      setSubmitting(false);
    }
  }

  return <Modal
    title={rejecting ? "Reject / request changes" : "Approve external approval"}
    subtitle={`${approval.gate_code} - ${approval.gate_name}`}
    onClose={() => { if (!submitting) onClose(); }}
    className="sm:max-w-xl"
  >
    <form className="grid gap-4" onSubmit={submit}>
      {stillBlocking(approval) && !rejecting && <p className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm font-bold text-blue-800">
        This approval blocks {approval.covered_task_ids.length} task{approval.covered_task_ids.length === 1 ? "" : "s"}. Approving it releases them.
      </p>}
      {rejecting && <p className="rounded-xl border border-orange-200 bg-orange-50 px-4 py-3 text-sm font-bold text-orange-900">
        This sends the approval back to {approval.assigned_to_name || "the assignee"} to fix and resubmit - it is not a permanent close.
      </p>}
      <Field label={rejecting ? "Reason for rejection (required)" : "Remarks (optional)"}>
        <Textarea
          value={reason}
          onChange={event => setReason(event.target.value)}
          required={rejecting}
          placeholder={rejecting ? "Explain why this approval is being refused" : "Optional remarks for the record"}
        />
      </Field>
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
      <div className="grid gap-2 sm:grid-cols-2">
        <Button type="button" variant="secondary" disabled={submitting} onClick={onClose}>Cancel</Button>
        <Button type="submit" variant={rejecting ? "danger" : "primary"} disabled={rejecting && !reason.trim()} loading={submitting}>
          {rejecting ? "Confirm rejection" : "Confirm approval"}
        </Button>
      </div>
    </form>
  </Modal>;
}

// ---- covered task labels (never raw UUIDs) ---------------------------------

function CoveredTasks({ approval, tasksById }) {
  if (approval.coverage_state === "unresolved") {
    return <p className="text-sm text-slate-600">
      Scope was described in prose and could not be mapped to tasks automatically{approval.coverage_text ? `: "${approval.coverage_text}"` : "."}
    </p>;
  }
  if (!approval.covered_task_ids.length) return <p className="text-sm font-medium text-slate-500">0 tasks covered.</p>;
  const resolved = approval.covered_task_ids.map(id => tasksById?.get(id)).filter(Boolean);
  return <div className="grid gap-1.5">
    <p className="text-sm font-bold text-slate-700">{approval.covered_task_ids.length} task{approval.covered_task_ids.length === 1 ? "" : "s"} covered</p>
    {resolved.length > 0 && <div className="flex flex-wrap gap-1.5">
      {resolved.map(task => <span key={task.code} title={task.title} className="rounded-md bg-slate-100 px-2 py-1 tabular-nums text-xs font-medium text-slate-600">{task.code}</span>)}
    </div>}
  </div>;
}

// ---- Approval Review overlay drawer ---------------------------------
//
// Same large right-side drawer chrome as TaskDetailDrawer (backdrop, fixed
// w-[820px] aside, body scroll lock) - mounted with `key={approval.id}` by
// the caller, so switching approvals remounts fresh (checklist/pending
// decision reset for free, the same convention TaskDetailDrawer relies on).
// Section visibility is unchanged from the old sidebar: Admin decision
// controls stay behind `canDecide`/`mayManage`, the submit form stays
// behind `mine` - a PM or Supervisor viewing this drawer only ever sees the
// read-only sections and the "Only an Admin can..." notice at the bottom.

function ReviewPanel({ projectId, approval, mayManage, user, candidates, tasksById, onClose, onAssign, onReassign, onUnassign, onDecide, onChanged }) {
  const [checklist, setChecklist] = useState({ documents: false, evidenceClear: false, matchesRequirement: false, coveredTasksConfirmed: false });
  const [pendingDecision, setPendingDecision] = useState(null); // "approved" | "rejected"
  const [unassignError, setUnassignError] = useState("");

  // The page behind the drawer must not scroll while it's open.
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, []);

  const meta = statusMeta(approval);
  const mine = isAssignee(approval, user);
  const canDecide = mayManage && approval.status === "submitted";
  const canAssign = mayManage && approval.status === "unassigned";
  const canReassignOrUnassign = mayManage && (approval.status === "assigned" || approval.status === "submitted");

  async function unassign() {
    setUnassignError("");
    try {
      await onUnassign(approval);
    } catch (caught) {
      setUnassignError(caught?.message || "This gate could not be unassigned.");
    }
  }

  return createPortal(<>
    <div className="fixed inset-0 z-40 bg-slate-950/40" onClick={onClose} aria-hidden="true"/>
    <aside
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[90vw] flex-col rounded-l-2xl bg-white shadow-[-16px_0_50px_rgba(15,23,42,.18)] sm:w-[820px]"
      aria-label={`External approval detail - ${approval.gate_code}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-6 py-5">
        <div className="min-w-0">
          <span className="tabular-nums text-xs font-medium text-slate-600">{approval.gate_code}</span>
          <h2 className="mt-0.5 text-lg font-medium leading-snug text-slate-950">{approval.gate_name}</h2>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Pill tone={meta.tone}>{meta.label}</Pill>
            {stillBlocking(approval) && <Pill tone="red"><ShieldAlert size={12}/> Blocking</Pill>}
            {approval.coverage_state === "unresolved" && <Pill tone="violet"><AlertTriangle size={12}/> Coverage Unresolved</Pill>}
          </div>
        </div>
        <button type="button" aria-label="Close approval detail" onClick={onClose} className="shrink-0 rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">
          <X size={20}/>
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/60 px-6 py-5">
        <div className="grid gap-4">

    {/* A. Assignment Summary */}
    <section className="grid gap-2">
      <h4 className="text-xs font-medium text-slate-500">Assignment summary</h4>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold text-slate-500">Assigned Internal Employee</span>
        {approval.assigned_to_name
          ? <span className="flex items-center gap-2"><EmployeeAvatar name={approval.assigned_to_name}/><span className="text-sm font-bold text-slate-800">{approval.assigned_to_name}</span></span>
          : <span className="text-sm font-medium text-slate-400">Not assigned</span>}
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold text-slate-500">Due date</span>
        <DueDate approval={approval}/>
      </div>
      <CoveredTasks approval={approval} tasksById={tasksById}/>
      <ReferenceMaterial className="border-t border-slate-100 pt-3" instructions={approval.evidence_instructions} files={approval.reference_files}
        onDownload={file => taskExecutionApi.downloadApprovalReference(projectId, approval.id, file.id)}/>

      {mayManage && <div className="mt-1 flex flex-wrap gap-2">
        {canAssign && <Button size="sm" onClick={() => onAssign(approval)}>Assign</Button>}
        {canReassignOrUnassign && <>
          <Button size="sm" variant="secondary" onClick={() => onReassign(approval)}><Repeat size={13}/> Reassign</Button>
          <Button size="sm" variant="secondary" onClick={unassign}>Unassign</Button>
        </>}
      </div>}
      {unassignError && <p className="text-xs font-bold text-rose-700">{unassignError}</p>}
    </section>

    {/* B. Submission Summary */}
    <section className="grid gap-2 border-t border-slate-100 pt-3">
      <h4 className="text-xs font-medium text-slate-500">Submission summary</h4>
      <SubmissionList projectId={projectId} approval={approval}/>
    </section>

    {/* Employee update/submit flow - assignee-exclusive, matching
        ProjectGateSubmissionService._require_submitter (no Admin/PM
        fallback). No admin review controls are ever rendered here. */}
    {mine && approval.status === "assigned" && <SubmissionForm projectId={projectId} approval={approval} onSubmitted={onChanged}/>}
    {mine && approval.status === "submitted" && <p className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm font-bold text-blue-800">Waiting on Admin review.</p>}
    {mine && approval.status === "approved" && <p className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-bold text-emerald-800">Approved{approval.decided_at ? ` on ${formatDateShort(approval.decided_at.slice(0, 10))}` : ""}.</p>}

    {/* C. Admin Review Checklist - UI-only. There is no backend field to
        persist this against; it exists purely to help Admin structure their
        own review before deciding, and is reset per approval above. */}
    {canDecide && <section className="grid gap-2 border-t border-slate-100 pt-3">
      <h4 className="text-xs font-medium text-slate-500">Admin review checklist</h4>
      <div className="grid gap-1.5">
        {[
          ["documents", "Documents received"],
          ["evidenceClear", "Evidence is clear"],
          ["matchesRequirement", "Approval matches project requirement"],
          ["coveredTasksConfirmed", "Covered tasks confirmed"],
        ].map(([key, label]) => <label key={key} className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <input type="checkbox" checked={checklist[key]} onChange={event => setChecklist(prev => ({ ...prev, [key]: event.target.checked }))} className="size-4 rounded border-slate-300 text-blue-600 focus:ring-blue-600"/>
          {label}
        </label>)}
      </div>
      <p className="text-xs text-slate-400">For your own review only - not saved to the system.</p>
    </section>}

    {/* D. Admin Decision Actions - Approve / Reject (which is also the only
        "send back for changes" mechanism the backend has) / Reassign. There
        is no separate "Request Changes" endpoint distinct from Reject: both
        would call the identical `decide(decision="rejected")` action, so
        rather than show two buttons that do the same thing, Reject is
        labelled to say what it actually does. */}
    {canDecide && <section className="grid gap-2 border-t border-slate-100 pt-3">
      <h4 className="text-xs font-medium text-slate-500">Admin decision</h4>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => setPendingDecision("approved")}>Approve</Button>
        <Button size="sm" variant="danger" onClick={() => setPendingDecision("rejected")}>Reject / Request Changes</Button>
        <Button size="sm" variant="secondary" onClick={() => onReassign(approval)}><Repeat size={13}/> Reassign</Button>
      </div>
    </section>}

    {approval.status === "approved" && approval.decided_by_name && <p className="border-t border-slate-100 pt-3 text-xs font-bold text-slate-500">
      Approved by {approval.decided_by_name}{approval.decided_at ? ` on ${formatDateShort(approval.decided_at.slice(0, 10))}` : ""}.
    </p>}

    {!mayManage && !mine && <p className="border-t border-slate-100 pt-3 text-xs font-bold text-slate-500">Only an Admin can assign or decide this external approval.</p>}

        </div>
      </div>
    </aside>

    {pendingDecision && <DecisionModal
      approval={approval}
      decision={pendingDecision}
      onConfirm={reason => onDecide(approval, pendingDecision, reason).then(() => setPendingDecision(null))}
      onClose={() => setPendingDecision(null)}
    />}
  </>, document.body);
}

// ---- root ------------------------------------------------------------

export function ExternalApprovalsPanel({ projectId, project, user }) {
  const [approvals, setApprovals] = useState([]);
  // The PLANNING-layer gates, read only to explain an empty list. An approval
  // is instantiated at activation from a gate a PM marked applicable, so a
  // project whose gates are all still awaiting that decision has none here -
  // and saying only "none were instantiated" describes our mechanism while
  // leaving the user believing the project has no external approvals at all,
  // when it may have dozens sitting undecided in setup.
  const [awaitingReview, setAwaitingReview] = useState(0);
  const [tasksById, setTasksById] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [assigning, setAssigning] = useState(null); // { approval, mode: "assign" | "reassign" }
  const [selectedId, setSelectedId] = useState(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [employeeFilter, setEmployeeFilter] = useState("all");
  const [coverageFilter, setCoverageFilter] = useState("all");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const mayManage = canManage(user);
  const employeeViewer = isEmployee(user);
  const candidates = (project?.memberships || [])
    .filter(membership => membership.project_role === "internal_employee" && !membership.ends_at);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setApprovals(await taskExecutionApi.listExternalApprovals(projectId));
    } catch (caught) {
      setError(caught?.message || "This project's external approvals could not be loaded.");
    } finally {
      setLoading(false);
    }
    // Deliberately after, and deliberately swallowed: this read only enriches
    // an explanation. Failing it must never blank the approvals a user can
    // actually act on.
    try {
      const gates = await projectsApi.externalGates(projectId);
      const items = gates?.items || gates || [];
      setAwaitingReview(items.filter(gate => (gate.applicability_state || "pending_review") === "pending_review").length);
    } catch {
      setAwaitingReview(0);
    }
  }

  useEffect(() => { load(); }, [projectId]);
  useEffect(() => { setSelectedId(null); setSearch(""); setStatusFilter("all"); setEmployeeFilter("all"); setCoverageFilter("all"); }, [projectId]);
  useEffect(() => { setVisibleCount(PAGE_SIZE); }, [search, statusFilter, employeeFilter, coverageFilter, projectId]);

  // Covered-task ids arrive as raw UUIDs (ProjectExternalApprovalOut has no
  // task code/title) - resolved here, best-effort, from the same task list
  // the Execution Calendar already fetches, so the UI never has to print a
  // bare id. Only fetched for a manager: an Internal Employee's own task list
  // is scoped to tasks they execute (list_project_tasks), which would often
  // NOT include every task their external approval covers, so a partial map
  // there would silently resolve some codes and not others.
  useEffect(() => {
    if (!mayManage) { setTasksById(null); return; }
    let active = true;
    taskExecutionApi.list(projectId)
      .then(tasks => { if (active) setTasksById(new Map(tasks.map(task => [task.id, { code: task.original_code, title: task.title }]))); })
      .catch(() => { if (active) setTasksById(null); });
    return () => { active = false; };
  }, [projectId, mayManage]);

  async function decide(approval, decision, reason) {
    await taskExecutionApi.decideExternalApproval(projectId, approval.id, { decision, reason });
    await load();
  }

  async function assign(approval, mode, assigneeUserId, dueDate) {
    const call = mode === "reassign" ? taskExecutionApi.reassignExternalApproval : taskExecutionApi.assignExternalApproval;
    await call(projectId, approval.id, { assignee_user_id: assigneeUserId, ...(dueDate ? { due_date: dueDate } : {}) });
    setAssigning(null);
    await load();
  }

  async function unassign(approval) {
    await taskExecutionApi.unassignExternalApproval(projectId, approval.id);
    await load();
  }

  if (loading) return <div className="rounded-[20px] border border-line bg-white p-8"><LoadingSpinner label="Loading external approvals..."/></div>;

  const filtered = sortApprovals(approvals).filter(approval => {
    const statusMatch = STATUS_FILTERS.find(([key]) => key === statusFilter)?.[2] ?? (() => true);
    const coverageMatch = COVERAGE_FILTERS.find(([key]) => key === coverageFilter)?.[2] ?? (() => true);
    if (!statusMatch(approval)) return false;
    if (!coverageMatch(approval)) return false;
    if (employeeFilter !== "all" && approval.assigned_to_user_id !== employeeFilter) return false;
    const term = search.trim().toLowerCase();
    if (term && ![approval.gate_code, approval.gate_name].some(value => value.toLowerCase().includes(term))) return false;
    return true;
  });
  const selected = approvals.find(approval => approval.id === selectedId) || null;
  const visibleApprovals = filtered.slice(0, visibleCount);
  const hasMore = filtered.length > visibleApprovals.length;
  const canShowLess = visibleCount > PAGE_SIZE;
  const filtersActive = Boolean(search.trim()) || statusFilter !== "all" || employeeFilter !== "all" || coverageFilter !== "all";

  function resetFilters() {
    setSearch(""); setStatusFilter("all"); setEmployeeFilter("all"); setCoverageFilter("all");
  }

  return <div className="grid gap-4">
    <header>
      <h2 className="text-[17px] font-medium text-slate-950">External Approvals Control</h2>
      <p className="mt-0.5 max-w-2xl text-sm text-slate-500">
        {mayManage
          ? "Assign approvals to internal employees, track submissions, and complete admin review."
          : employeeViewer
            ? "Your assigned external approvals: follow up, attach evidence and submit for Admin review."
            : "The external approvals this project's tasks are waiting on. Only an Admin can assign or decide them."}
      </p>
    </header>

    <WorkflowStrip/>

    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}

    {/* Shown whenever gates are still undecided, not only when the list is
        empty: a project can have three approvals here and twenty more nobody
        has ruled on, and the three would otherwise read as the whole set. */}
    {awaitingReview > 0 && <div className="flex items-start gap-2 rounded-xl border border-orange-200 bg-orange-50 px-4 py-3">
      <ClipboardCheck size={16} className="mt-0.5 shrink-0 text-orange-700"/>
      <p className="text-sm font-bold leading-6 text-orange-900">
        {awaitingReview} external approval{awaitingReview === 1 ? " is" : "s are"} awaiting applicability review.
        <span className="block font-medium">
          {awaitingReview === 1 ? "It becomes" : "They become"} assignable here once someone decides, in this project's setup, whether {awaitingReview === 1 ? "it applies" : "they apply"} to this project. Until then {awaitingReview === 1 ? "it holds" : "they hold"} nothing up.
        </span>
      </p>
    </div>}

    {!approvals.length && !error && awaitingReview === 0 ? (
      <EmptyState icon={<ClipboardCheck size={21}/>} title="Nothing to review" description="No external approvals apply to this project."/>
    ) : approvals.length === 0 ? null : <>
      <KpiCards approvals={approvals}/>

      <FilterBar
        search={search} setSearch={setSearch}
        statusFilter={statusFilter} setStatusFilter={setStatusFilter}
        employeeFilter={employeeFilter} setEmployeeFilter={setEmployeeFilter}
        coverageFilter={coverageFilter} setCoverageFilter={setCoverageFilter}
        employees={candidates} showEmployeeFilter={mayManage}
        onReset={resetFilters} filtersActive={filtersActive}
      />

      <ApprovalsTable
        approvals={visibleApprovals}
        mayManage={mayManage}
        user={user}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onAssign={approval => setAssigning({ approval, mode: "assign" })}
        hasMore={hasMore}
        canShowLess={canShowLess}
        onLoadMore={() => setVisibleCount(count => count + PAGE_SIZE)}
        onShowLess={() => setVisibleCount(PAGE_SIZE)}
      />

      {selected && <ReviewPanel
        key={selected.id}
        projectId={projectId}
        approval={selected}
        mayManage={mayManage}
        user={user}
        candidates={candidates}
        tasksById={tasksById}
        onClose={() => setSelectedId(null)}
        onAssign={approval => setAssigning({ approval, mode: "assign" })}
        onReassign={approval => setAssigning({ approval, mode: "reassign" })}
        onUnassign={unassign}
        onDecide={decide}
        onChanged={load}
      />}
    </>}

    {assigning && <AssignModal
      approval={assigning.approval}
      candidates={candidates}
      title={assigning.mode === "reassign" ? "Reassign external approval" : "Assign external approval"}
      confirmLabel={assigning.mode === "reassign" ? "Reassign" : "Assign"}
      onConfirm={(assigneeUserId, dueDate) => assign(assigning.approval, assigning.mode, assigneeUserId, dueDate)}
      onClose={() => setAssigning(null)}
    />}
  </div>;
}
