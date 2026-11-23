import { AlertTriangle, CalendarClock, Check, Search, Users2 } from "lucide-react";
import { cn } from "../../../utils/cn";
import { broadcastTime, groupByDay, timeLabel } from "../broadcastFormat";

function StatusMark({ status }) {
  if (status === "sent") return <Check size={14} className="text-ok" aria-label="Sent"/>;
  if (status === "scheduled") return <CalendarClock size={14} className="text-blue-600" aria-label="Scheduled"/>;
  if (status === "failed") return <span className="inline-flex items-center gap-1 text-xs text-rose-700"><AlertTriangle size={12} aria-hidden="true"/>Failed</span>;
  if (status === "partially_failed") return <span className="inline-flex items-center gap-1 text-xs text-orange-700"><AlertTriangle size={12} aria-hidden="true"/>Partly failed</span>;
  return null;
}

// One compact row: title, project and audience size, with the time and a
// status mark on the right. Selected row gets a dark edge, like the project list.
export function BroadcastRow({ broadcast, selected, onOpen }) {
  return <li>
    <button type="button" onClick={onOpen} aria-current={selected ? "true" : undefined} aria-label={`Open ${broadcast.title}`}
      className={cn("relative grid w-full gap-0.5 rounded-xl px-3 py-2.5 text-left transition",
        selected ? "bg-slate-100" : "hover:bg-slate-50")}>
      {selected && <span className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-slate-950" aria-hidden="true"/>}
      <span className="flex items-baseline justify-between gap-3">
        <span className="truncate text-sm text-slate-950">{broadcast.title}</span>
        <span className="shrink-0 text-xs tabular-nums text-slate-500">{timeLabel(broadcastTime(broadcast))}</span>
      </span>
      <span className="flex items-center justify-between gap-3 text-xs text-slate-500">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate">{broadcast.project_name}</span>
          <span className="inline-flex shrink-0 items-center gap-1"><Users2 size={12} aria-hidden="true"/>{broadcast.recipient_count}</span>
        </span>
        <StatusMark status={broadcast.status}/>
      </span>
    </button>
  </li>;
}

export const STATUS_FILTERS = [
  ["", "All"],
  ["sent", "Delivered"],
  ["partially_failed", "Partly failed"],
  ["failed", "Failed"],
];

export function BroadcastList({ broadcasts, allBroadcasts = broadcasts, loading, search, onSearchChange, status, onStatusChange, showStatusFilter, ascending,
  selectedId, onOpen, onLoadMore, hasMore, emptyTitle, emptyDescription, emptyAction }) {
  const groups = groupByDay(broadcasts, { ascending });
  const counts = Object.fromEntries(STATUS_FILTERS.map(([value]) => [value, value ? allBroadcasts.filter(item => item.status === value).length : allBroadcasts.length]));
  // Chips appear only when there is more than one kind of outcome to pick from.
  const chips = STATUS_FILTERS.filter(([value]) => !value || counts[value] > 0 || status === value);

  return <section aria-label="Messages" className="flex min-h-0 flex-col overflow-hidden rounded-[20px] border border-line bg-white">
    <div className="grid shrink-0 gap-2 border-b border-line p-3">
      <label className="relative">
        <span className="sr-only">Search messages</span>
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
        <input value={search} onChange={event => onSearchChange(event.target.value)} placeholder="Search title or project" autoComplete="off"
          className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-950 outline-none placeholder:text-slate-400 focus:border-blue-600 focus:bg-white"/>
      </label>
      {showStatusFilter && chips.length > 2 && <div role="group" aria-label="Delivery status" className="flex flex-wrap gap-1">
        {chips.map(([value, label]) => <button key={value || "all"} type="button" aria-pressed={status === value} onClick={() => onStatusChange(value)}
          className={cn("h-7 rounded-full px-2.5 text-xs transition", status === value ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-600 hover:text-slate-950")}>
          {label} <span className={cn("tabular-nums", status === value ? "text-white/70" : "text-slate-400")}>{counts[value]}</span>
        </button>)}
      </div>}
    </div>

    <div className="so-scroll min-h-0 flex-1 overflow-y-auto p-2">
      {loading && !broadcasts.length
        ? <p className="p-6 text-center text-sm text-slate-500">Loading messages…</p>
        : !broadcasts.length
          ? <div className="grid justify-items-center gap-2 px-4 py-10 text-center">
              <p className="text-sm text-slate-950">{search ? "No messages match your search" : emptyTitle}</p>
              <p className="max-w-xs text-sm text-slate-500">{search ? "Try a different title or project name." : emptyDescription}</p>
              {!search && emptyAction}
            </div>
          : groups.map(group => <div key={group.label} className="mb-2 last:mb-0">
              <h3 className="px-3 pb-1 pt-2 text-xs text-slate-500">{group.label}</h3>
              <ul className="grid gap-0.5">
                {group.items.map(broadcast => <BroadcastRow key={broadcast.id} broadcast={broadcast} selected={broadcast.id === selectedId} onOpen={() => onOpen(broadcast)}/>)}
              </ul>
            </div>)}
      {hasMore && !loading && <button type="button" onClick={onLoadMore} className="mt-1 w-full rounded-xl py-2 text-sm text-blue-700 hover:bg-blue-50">Load older messages</button>}
    </div>
  </section>;
}
