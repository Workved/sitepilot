import { ChevronDown, FileCheck2, History, XCircle } from "lucide-react";

function formatDate(value) {
  return new Date(value).toLocaleString("en-GB");
}

function AuditHistory({ events }) {
  if (!events.length) return null;
  return <details className="group mt-3">
    <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-slate-500">
      <History size={13}/> Audit history <ChevronDown size={13} className="transition group-open:rotate-180"/>
    </summary>
    <div className="mt-2 grid gap-1.5">
      {events.map(event => <div key={event.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-xs">
        <span className="tabular-nums font-medium text-slate-500">{event.before_status || "-"} &rarr; {event.after_status || "-"}</span>
        <span className="text-slate-400">{formatDate(event.occurred_at)}</span>
        {event.actor_name && <span className="font-bold text-slate-600">{event.actor_name}</span>}
        {event.reason && <span className="text-slate-500">- {event.reason}</span>}
      </div>)}
    </div>
  </details>;
}

// Terminal-state (completed/cancelled) read-only summary. Once a task
// reaches one of these two states it has no further outgoing transitions
// (task_lifecycle.py's ALLOWED_TRANSITIONS has an empty set for both), so
// none of the execution controls (start/submit/verify/approve/reject,
// report delay/blocker, support assignment changes, cancel) apply anymore -
// this replaces them with a compact history view instead. `rejected` is
// deliberately NOT terminal here: the backend always bounces it straight
// back to `in_progress`, so it never persists as a state to summarize.
export function TaskTerminalSummary({ task, onDownloadEvidence }) {
  if (task.lifecycle_status === "cancelled") {
    const cancellation = task.audit_events.find(event => event.after_status === "cancelled");
    return <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h4 className="flex items-center gap-2 text-xs font-medium text-slate-500"><XCircle size={14} className="text-rose-600"/> Cancelled</h4>
      <dl className="mt-2 grid gap-1.5 text-sm">
        <div className="flex flex-wrap gap-2"><dt className="font-bold text-slate-500">Reason:</dt><dd className="text-slate-700">{cancellation?.reason || "Not recorded."}</dd></div>
        <div className="flex flex-wrap gap-2"><dt className="font-bold text-slate-500">Cancelled by:</dt><dd className="text-slate-700">{cancellation?.actor_name || "Unknown"}</dd></div>
        <div className="flex flex-wrap gap-2"><dt className="font-bold text-slate-500">Cancelled at:</dt><dd className="text-slate-700">{cancellation ? formatDate(cancellation.occurred_at) : formatDate(task.updated_at)}</dd></div>
      </dl>
      <AuditHistory events={task.audit_events}/>
    </section>;
  }

  if (task.lifecycle_status === "completed") {
    const reviewer = task.approvals[0] || task.verifications[0] || null;
    const reviewerName = task.approvals[0]?.decided_by_name || task.verifications[0]?.verified_by_name;
    const reviewerLabel = task.approvals[0] ? "Approved by" : task.verifications[0] ? "Verified by" : null;
    const evidence = task.progress_updates.flatMap(update => update.evidence);

    return <section className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
      <h4 className="flex items-center gap-2 text-xs font-medium text-emerald-800"><FileCheck2 size={14}/> Completed</h4>
      <dl className="mt-2 grid gap-1.5 text-sm">
        <div className="flex flex-wrap gap-2"><dt className="font-bold text-slate-500">Completed at:</dt><dd className="text-slate-700">{formatDate(task.updated_at)}</dd></div>
        {reviewerLabel && <div className="flex flex-wrap gap-2"><dt className="font-bold text-slate-500">{reviewerLabel}:</dt><dd className="text-slate-700">{reviewerName || "Unknown"}{reviewer?.remarks ? ` - ${reviewer.remarks}` : ""}</dd></div>}
        {!reviewerLabel && <div className="flex flex-wrap gap-2"><dt className="font-bold text-slate-500">Approval:</dt><dd className="text-slate-700">Not required for this task.</dd></div>}
      </dl>
      {evidence.length > 0 && <div className="mt-2">
        <span className="text-xs font-bold text-slate-500">Completion evidence:</span>
        <div className="mt-1 flex flex-wrap gap-2">
          {evidence.map(file => <button key={file.id} type="button" onClick={() => onDownloadEvidence(file.file_id)} className="rounded-md bg-white px-2 py-1 text-xs font-bold text-blue-700 ring-1 ring-inset ring-blue-200 hover:bg-blue-50">{file.original_filename}</button>)}
        </div>
      </div>}
      <AuditHistory events={task.audit_events}/>
    </section>;
  }

  return null;
}
