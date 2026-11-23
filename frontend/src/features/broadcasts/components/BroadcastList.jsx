import { Calendar, Clock, Filter, Search, Send, Users2 } from "lucide-react";
import { useState } from "react";
import { EmptyState, LoadingSpinner } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { formatDateShort } from "../../../utils/format";
import { StatusChip } from "./StatusChip";

const STATUS_FILTERS = [
  ["", "All statuses"],
  ["sent", "Sent"],
  ["scheduled", "Scheduled"],
  ["partially_failed", "Partially Failed"],
  ["failed", "Failed"],
];

export function BroadcastCard({ broadcast, onOpen, onSendNow }) {
  return <article onClick={onOpen} className="grid cursor-pointer gap-2 rounded-2xl border border-slate-200 bg-white p-4 transition hover:border-blue-200">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <span className="text-xs font-medium text-slate-500">{broadcast.project_name}</span>
        <h3 className="mt-0.5 truncate font-black text-slate-950">{broadcast.title}</h3>
      </div>
      <StatusChip status={broadcast.status} />
    </div>
    <div className="flex flex-wrap items-center gap-3 text-xs font-semibold text-slate-500">
      <span className="flex items-center gap-1"><Users2 size={13} /> {broadcast.recipient_count} recipient{broadcast.recipient_count === 1 ? "" : "s"}</span>
      {broadcast.meeting_date && <span className="flex items-center gap-1"><Calendar size={13} /> {formatDateShort(broadcast.meeting_date)}{broadcast.meeting_time ? ` · ${broadcast.meeting_time}` : ""}</span>}
      <span className="flex items-center gap-1"><Clock size={13} /> {broadcast.send_mode === "scheduled" ? `Scheduled ${new Date(broadcast.scheduled_at).toLocaleString()}` : `Sent ${broadcast.sent_at ? new Date(broadcast.sent_at).toLocaleString() : "-"}`}</span>
    </div>
    {broadcast.status === "scheduled" && onSendNow && <button type="button" onClick={event => { event.stopPropagation(); onSendNow(broadcast); }}
      className="mt-1 flex w-fit items-center gap-1.5 rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-black text-white transition hover:bg-slate-800"><Send size={12} /> Send now</button>}
  </article>;
}

export function BroadcastList({ broadcasts, loading, search, onSearchChange, status, onStatusChange, showStatusFilter = true, onOpen, onSendNow, onLoadMore, hasMore, emptyTitle = "No broadcasts yet", emptyDescription = "Create a broadcast to see it appear here." }) {
  const [filtersOpen, setFiltersOpen] = useState(false);

  return <div className="grid gap-3">
    <div className="flex items-center gap-2">
      <div className="relative flex-1">
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input value={search} onChange={event => onSearchChange(event.target.value)} placeholder="Search messages…"
          className="min-h-11 w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm font-medium text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" />
      </div>
      {showStatusFilter && <div className="relative">
        <button type="button" onClick={() => setFiltersOpen(v => !v)}
          className={cn("flex min-h-11 items-center gap-2 rounded-xl border px-3.5 text-sm font-bold transition", status ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50")}>
          <Filter size={16} /> Filter
        </button>
        {filtersOpen && <div className="absolute right-0 top-[calc(100%+8px)] z-20 grid w-48 gap-0.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-[0_18px_50px_rgba(15,23,42,.14)]">
          {STATUS_FILTERS.map(([value, label]) => <button key={value || "all"} type="button" onClick={() => { onStatusChange(value); setFiltersOpen(false); }}
            className={cn("rounded-lg px-3 py-2 text-left text-sm font-bold transition", status === value ? "bg-blue-700 text-white" : "text-slate-700 hover:bg-slate-50")}>{label}</button>)}
        </div>}
      </div>}
    </div>

    {loading
      ? <div className="grid min-h-40 place-items-center"><LoadingSpinner label="Loading broadcasts…" /></div>
      : broadcasts.length === 0
        ? <EmptyState title={emptyTitle} description={emptyDescription} />
        : <div className="grid gap-3">{broadcasts.map(broadcast => <BroadcastCard key={broadcast.id} broadcast={broadcast} onOpen={() => onOpen(broadcast)} onSendNow={onSendNow} />)}</div>}

    {hasMore && !loading && <button type="button" onClick={onLoadMore} className="rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-bold text-blue-700 hover:bg-blue-50">Load more</button>}
  </div>;
}
