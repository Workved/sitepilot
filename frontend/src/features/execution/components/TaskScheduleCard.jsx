import { useState } from "react";
import { CalendarClock, Diamond } from "lucide-react";
import { targetsApi } from "../../../api/targetsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Input, Textarea } from "../../../components/ui";
import { formatDateShort } from "../../../utils/format";
import { TARGET_STYLE, targetLabel } from "./calendar/scheduleModel";

const isAdmin = user => user?.role === "admin" || user?.role === "super_admin";

// The task's dates in one place: plan (and the original plan if it moved),
// its target with history, and - for the PM, Supervisor and admins - a way to
// formally change the planned dates with a reason.
export function TaskScheduleCard({ projectId, detail, user, roles, targets = [], change = null, onChanged }) {
  const [mode, setMode] = useState(""); // "" | "target" | "dates"
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [start, setStart] = useState(detail.planned_start_date || "");
  const [end, setEnd] = useState(detail.planned_end_date || "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const finished = ["completed", "cancelled"].includes(detail.lifecycle_status);
  const mine = targets.filter(target => target.task_id === detail.id);
  const active = mine.find(target => target.status === "active");
  const history = mine.filter(target => target.status !== "active").sort((a, b) => (b.ended_at || "").localeCompare(a.ended_at || ""));
  const canSet = !finished && (isAdmin(user) || roles.length > 0);
  const canReschedule = !finished && (isAdmin(user) || roles.includes("project_manager") || roles.includes("site_supervisor"));

  async function run(operation) {
    setBusy(true);
    setError("");
    try { await operation(); setMode(""); await onChanged(); } catch (caught) { setError(caught?.message || "That didn't save."); } finally { setBusy(false); }
  }

  const saveTarget = event => { event.preventDefault(); if (date) run(() => targetsApi.create(projectId, { kind: "task", task_id: detail.id, target_date: date, note: note.trim() || null })); };
  const saveDates = event => {
    event.preventDefault();
    if (!reason.trim()) return setError("Say why the dates are changing.");
    run(() => taskExecutionApi.reschedule(projectId, detail.id, { new_planned_start_date: start, new_planned_end_date: end, reason: reason.trim() }));
  };

  const style = active ? TARGET_STYLE[active.outcome?.state || "open"] : null;

  return <section className="rounded-[20px] border border-line bg-white p-5" id="action-schedule">
    <h4 className="text-[15px] font-medium text-slate-950">Schedule and target</h4>

    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
      <div><dt className="text-xs text-slate-500">Plan</dt><dd className="text-slate-950">{formatDateShort(detail.planned_start_date)} - {formatDateShort(detail.planned_end_date)}</dd></div>
      {change && <div><dt className="text-xs text-slate-500">Original plan</dt><dd className="text-slate-700">{formatDateShort(change.original_start)} - {formatDateShort(change.original_end)}</dd></div>}
      {change && <div className="col-span-2"><dt className="text-xs text-slate-500">Moved {change.times_moved} {change.times_moved === 1 ? "time" : "times"}</dt>
        <dd className="text-slate-700">{change.last_by ? `Last by ${change.last_by}` : ""}{change.last_reason ? `: ${change.last_reason}` : ""}</dd></div>}
    </dl>

    <div className="mt-4 rounded-2xl bg-canvas p-3">
      {active
        ? <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className={`flex items-center gap-1.5 text-sm ${style.text}`}><Diamond size={14} aria-hidden="true"/>{targetLabel(active)}</p>
              {active.note && <p className="mt-1 text-[13px] text-slate-700">{active.note}</p>}
              <p className="mt-1 text-xs text-slate-500">Set by {active.created_by_name}</p>
            </div>
            <div className="flex gap-1.5">
              {canSet && <Button size="sm" variant="secondary" onClick={() => { setDate(""); setNote(""); setMode("target"); }}>Change target</Button>}
              {active.can_manage && <Button size="sm" variant="ghost" loading={busy && mode === ""} onClick={() => run(() => targetsApi.clear(active.id))}>Clear</Button>}
            </div>
          </div>
        : <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-slate-500">No target. A target is a date the team commits to; it doesn't change the plan.</p>
            {canSet && <Button size="sm" variant="secondary" onClick={() => { setDate(""); setNote(""); setMode("target"); }}><Diamond size={14}/> Set target</Button>}
          </div>}
      {history.length > 0 && <details className="mt-2 text-xs text-slate-500">
        <summary className="cursor-pointer">Earlier targets ({history.length})</summary>
        <ul className="mt-1 grid gap-0.5">{history.map(item => <li key={item.id}>{formatDateShort(item.target_date)}, set by {item.created_by_name} · {item.status === "replaced" ? "replaced" : "cleared"}{item.ended_by_name ? ` by ${item.ended_by_name}` : ""}</li>)}</ul>
      </details>}
    </div>

    {mode === "target" && <form onSubmit={saveTarget} className="mt-3 grid gap-3 sm:grid-cols-[11rem_minmax(0,1fr)_auto] sm:items-end">
      <Field label="Finish by"><Input type="date" value={date} onChange={event => setDate(event.target.value)} required/></Field>
      <Field label="Note (optional)"><Input value={note} onChange={event => setNote(event.target.value)} placeholder="e.g. Client visit on the 29th"/></Field>
      <div className="flex gap-1.5 sm:pb-0.5"><Button type="submit" size="sm" loading={busy}>Save target</Button><Button size="sm" variant="ghost" onClick={() => setMode("")}>Cancel</Button></div>
    </form>}

    {canReschedule && mode !== "dates" && <Button size="sm" variant="ghost" className="mt-3 w-fit" onClick={() => { setStart(detail.planned_start_date || ""); setEnd(detail.planned_end_date || ""); setReason(""); setMode("dates"); }}>
      <CalendarClock size={14}/> Change planned dates
    </Button>}
    {mode === "dates" && <form onSubmit={saveDates} className="mt-3 grid gap-3 rounded-2xl border border-line p-3">
      <p className="text-[13px] text-slate-600">This moves the plan itself. Delays are then measured against the new dates, and the calendar shows where it was originally planned.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="New start"><Input type="date" value={start} onChange={event => setStart(event.target.value)} required/></Field>
        <Field label="New end"><Input type="date" value={end} onChange={event => setEnd(event.target.value)} required/></Field>
      </div>
      <Field label="Why the dates are changing"><Textarea value={reason} onChange={event => setReason(event.target.value)} required placeholder="e.g. Client changed the flooring material; delivery moved"/></Field>
      <div className="flex gap-1.5"><Button type="submit" size="sm" loading={busy}>Change dates</Button><Button size="sm" variant="ghost" onClick={() => setMode("")}>Cancel</Button></div>
    </form>}

    {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
  </section>;
}
