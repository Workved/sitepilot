import { ArrowLeft, CalendarDays, Clock, Inbox, MapPin, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { broadcastApi } from "../../../api/broadcastApi";
import { Button } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { formatDateShort } from "../../../utils/format";
import { dateTimeLabel, plural } from "../broadcastFormat";
import { RecipientGroups } from "./RecipientPreviewDrawer";
import { StatusChip } from "./StatusChip";

const DELIVERY_PARTS = [
  ["sent", "Delivered", "var(--color-ok)"],
  ["pending", "Pending", "var(--color-slate-300)"],
  ["skipped_no_contact", "No contact", "var(--color-behind)"],
  ["failed", "Failed", "#d9483b"],
];

// A stacked bar of where every recipient ended up, with a legend that only
// lists the outcomes that actually happened.
export function DeliveryBar({ summary }) {
  const total = DELIVERY_PARTS.reduce((sum, [key]) => sum + (summary?.[key] || 0), 0);
  if (!total) return null;
  const parts = DELIVERY_PARTS.filter(([key]) => summary[key]);
  return <div className="grid gap-2">
    <div className="flex h-2 overflow-hidden rounded-full bg-slate-100" role="img" aria-label={parts.map(([key, label]) => `${summary[key]} ${label.toLowerCase()}`).join(", ")}>
      {parts.map(([key, , color]) => <span key={key} style={{ width: `${(summary[key] / total) * 100}%`, background: color }}/>)}
    </div>
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {parts.map(([key, label, color]) => <li key={key} className="inline-flex items-center gap-1.5">
        <span className="size-2 rounded-full" style={{ background: color }} aria-hidden="true"/>{summary[key]} {label.toLowerCase()}
      </li>)}
    </ul>
  </div>;
}

function MeetingFacts({ broadcast }) {
  const facts = [
    broadcast.meeting_date && [CalendarDays, formatDateShort(broadcast.meeting_date)],
    broadcast.meeting_time && [Clock, broadcast.meeting_time],
    broadcast.location_or_link && [MapPin, broadcast.location_or_link],
  ].filter(Boolean);
  if (!facts.length) return null;
  return <ul aria-label="Meeting details" className="flex flex-wrap gap-2">
    {facts.map(([Icon, text]) => <li key={text} className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1.5 text-[13px] text-slate-700">
      <Icon size={14} className="shrink-0 text-slate-500" aria-hidden="true"/>
      {/^https?:\/\//.test(text) ? <a href={text} target="_blank" rel="noreferrer" className="truncate text-blue-700 hover:underline">{text}</a> : <span className="truncate">{text}</span>}
    </li>)}
  </ul>;
}

export function EmptyReader() {
  return <section className="hidden min-h-0 place-items-center rounded-[20px] border border-line bg-white p-10 text-center lg:grid">
    <div className="grid justify-items-center gap-2">
      <Inbox size={28} className="text-slate-300" aria-hidden="true"/>
      <p className="text-sm text-slate-950">Pick a message to read it</p>
      <p className="max-w-xs text-sm text-slate-500">You'll see what was sent, who it went to and whether it reached them.</p>
    </div>
  </section>;
}

export function BroadcastDetail({ broadcastId, onBack, onSendNow }) {
  const [state, setState] = useState({ id: null, data: null, error: "" });
  const [undeliveredOnly, setUndeliveredOnly] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setUndeliveredOnly(false);
    broadcastApi.detail(broadcastId)
      .then(data => { if (!cancelled) setState({ id: broadcastId, data, error: "" }); })
      .catch(error => { if (!cancelled) setState({ id: broadcastId, data: null, error: error.message || "This message could not be loaded." }); });
    return () => { cancelled = true; };
  }, [broadcastId]);

  const loading = state.id !== broadcastId;
  const broadcast = state.data;
  const shell = "flex min-h-0 flex-col overflow-hidden rounded-[20px] border border-line bg-white";
  const back = <button type="button" onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-950 lg:hidden"><ArrowLeft size={16}/> All messages</button>;

  if (loading) return <section className={cn(shell, "p-5")} aria-busy="true">{back}<p className="m-auto text-sm text-slate-500">Loading message…</p></section>;
  if (!broadcast) return <section className={cn(shell, "p-5")}>{back}<p className="m-auto text-sm text-rose-700">{state.error}</p></section>;

  const recipients = broadcast.recipients || [];
  const scheduled = broadcast.status === "scheduled";
  const notDelivered = recipients.filter(item => item.delivery_status !== "sent");
  const shown = undeliveredOnly ? notDelivered : recipients;

  async function sendNow() {
    setSending(true);
    try { await onSendNow(broadcast); } finally { setSending(false); }
  }

  return <article aria-label={`Message - ${broadcast.title}`} className={shell}>
    <div className="so-scroll min-h-0 flex-1 overflow-y-auto">
      <header className="grid gap-3 border-b border-line p-5 sm:p-6">
        {back}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm text-slate-500">{broadcast.project_name}{broadcast.created_by_name ? ` · sent by ${broadcast.created_by_name}` : ""}</p>
            <h3 className="mt-1 text-2xl font-light tracking-[-0.01em] text-slate-950">{broadcast.title}</h3>
            <p className="mt-1 text-sm text-slate-500">
              {scheduled ? `Goes out ${dateTimeLabel(broadcast.scheduled_at)}` : broadcast.sent_at ? `Sent ${dateTimeLabel(broadcast.sent_at)}` : `Created ${dateTimeLabel(broadcast.created_at)}`}
              {" · "}{plural(broadcast.recipient_count, "person", "people")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <StatusChip status={broadcast.status}/>
            {scheduled && onSendNow && <Button size="sm" loading={sending} onClick={sendNow}><Send size={14}/> Send now</Button>}
          </div>
        </div>
        <MeetingFacts broadcast={broadcast}/>
      </header>

      <div className="grid gap-6 p-5 sm:p-6">
        <section aria-label="Message" className="grid gap-4">
          {broadcast.agenda && <div>
            <h4 className="text-xs text-slate-500">Agenda</h4>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-800">{broadcast.agenda}</p>
          </div>}
          <div>
            <h4 className="text-xs text-slate-500">Message</h4>
            <p className="mt-1 max-w-[68ch] whitespace-pre-wrap rounded-2xl rounded-tl-md bg-canvas px-4 py-3 text-[15px] leading-6 text-slate-900">{broadcast.message_body || "No message body."}</p>
          </div>
        </section>

        {!scheduled && <section aria-label="Delivery" className="grid gap-2">
          <h4 className="text-[15px] font-medium text-slate-950">Delivery</h4>
          <DeliveryBar summary={broadcast.delivery_summary}/>
        </section>}

        <section aria-label="Recipients" className="grid gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-[15px] font-medium text-slate-950">Recipients</h4>
            {!scheduled && notDelivered.length > 0 && notDelivered.length < recipients.length && <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={undeliveredOnly} onChange={event => setUndeliveredOnly(event.target.checked)} className="size-4 rounded border-slate-300 accent-slate-950"/>
              Not delivered only ({notDelivered.length})
            </label>}
          </div>
          {shown.length
            ? <RecipientGroups recipients={shown} renderTrailing={recipient => scheduled ? null : <StatusChip status={recipient.delivery_status}/>}/>
            : <p className="rounded-2xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">No recipients on this message.</p>}
        </section>
      </div>
    </div>
  </article>;
}
