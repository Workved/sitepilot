import { Activity } from "lucide-react";
import { EmptyState } from "../../../components/ui";
import { PaneHeader } from "../../../components/layout/PaneKit";

const actionLabel = value => value.toLowerCase().replaceAll("_", " ").replace(/^\S/, match => match.toUpperCase());
const dayKey = value => new Date(value).toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
const timeOf = value => new Date(value).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

// Audit trail grouped by day: one quiet line per event, the reason under it.
export function ProjectActivityPane({ activity }) {
  if (!activity.length) {
    return <EmptyState icon={<Activity size={20}/>} title="No recorded activity" description="Project changes will appear here automatically."/>;
  }
  const days = activity.reduce((groups, event) => {
    const key = dayKey(event.occurred_at);
    (groups[key] ||= []).push(event);
    return groups;
  }, {});
  return <div className="grid gap-5">
    <PaneHeader title="Activity" description="Every change to this project, newest first, with who made it and why."/>
    {Object.entries(days).map(([day, events]) => <section key={day} className="rounded-[20px] border border-line bg-white">
      <h4 className="border-b border-line px-5 py-3 text-[13px] text-slate-500">{day}</h4>
      <ol className="divide-y divide-slate-100">
        {events.map(event => <li key={event.id} className="grid grid-cols-[3.25rem_minmax(0,1fr)] gap-3 px-5 py-3.5">
          <time className="pt-0.5 text-xs tabular-nums text-slate-500">{timeOf(event.occurred_at)}</time>
          <div className="min-w-0">
            <p className="text-sm text-slate-950">{actionLabel(event.action)} <span className="text-slate-500">by {event.actor_name}</span></p>
            {event.reason && <p className="mt-0.5 text-[13px] leading-6 text-slate-600">{event.reason}</p>}
          </div>
        </li>)}
      </ol>
    </section>)}
  </div>;
}
