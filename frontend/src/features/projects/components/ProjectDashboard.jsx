import { useEffect, useState } from "react";
import { CheckCircle2, UserX } from "lucide-react";
import { projectsApi } from "../../../api/projectsApi";
import { Alert, EmptyState, LoadingSpinner } from "../../../components/ui";
import { PaneCard, PaneHeader, StatStrip } from "../../../components/layout/PaneKit";

// Phase 3 U2: read-only summary view over U1's ProjectVisibilityService.
// Renders whatever the dashboard endpoint returns - it does not derive any
// of its own counts, per the plan's "single source of truth" decision.

const STATUS_LABEL = { planned: "Planned", in_progress: "In progress", submitted: "Submitted", completed: "Completed", blocked: "Blocked", delayed: "Delayed", rejected: "Rejected" };

// Planned / active / completed as one proportional bar - the shape of the
// whole schedule at a glance, instead of four equal tiles.
function TaskMix({ summary }) {
  const parts = [
    ["Completed", summary.completed_count, "var(--color-blue-600)"],
    ["Active", summary.active_count, "var(--color-blue-200)"],
    ["Planned", summary.planned_count, "var(--color-slate-200)"],
  ];
  const total = summary.total_count || 1;
  return <PaneCard title="Task mix" description={`${summary.total_count} tasks on the frozen schedule`}>
    <div className="flex h-3 overflow-hidden rounded-full bg-slate-100" role="img" aria-label={parts.map(([label, value]) => `${label} ${value}`).join(", ")}>
      {parts.map(([label, value, color]) => value > 0 && <span key={label} style={{ width: `${value / total * 100}%`, background: color }}/>)}
    </div>
    <dl className="mt-4 grid grid-cols-3 gap-3">
      {parts.map(([label, value, color]) => <div key={label}>
        <dt className="flex items-center gap-1.5 text-xs text-slate-500"><span className="size-2.5 rounded-[3px] border border-slate-200" style={{ background: color }}/>{label}</dt>
        <dd className="mt-1 text-2xl font-light tabular-nums text-slate-950">{value}</dd>
      </div>)}
    </dl>
  </PaneCard>;
}

const DOT = { red: "bg-rose-600", orange: "bg-behind", violet: "bg-gate", yellow: "bg-yellow-400" };

function TaskListCard({ title, tone, items, renderMeta }) {
  if (!items.length) return null;
  return <PaneCard
    title={<span className="flex items-center gap-2"><span className={`size-2 rounded-full ${DOT[tone] || "bg-slate-400"}`}/>{title}<span className="text-slate-400">{items.length}</span></span>}
    bodyClassName="p-0"
  >
    <ul className="divide-y divide-slate-100">
      {items.map(item => <li key={item.id} className="flex items-start gap-3 px-5 py-3">
        {item.original_code && <span className="mt-0.5 shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-xs tabular-nums text-slate-600">{item.original_code}</span>}
        <div className="min-w-0 flex-1">
          <p className="text-sm text-slate-950">{item.title}</p>
          {renderMeta && renderMeta(item) && <p className="mt-0.5 text-xs text-slate-500">{renderMeta(item)}</p>}
        </div>
        {item.lifecycle_status && <span className="shrink-0 text-xs text-slate-500">{STATUS_LABEL[item.lifecycle_status] || item.lifecycle_status.replace("_", " ")}</span>}
      </li>)}
    </ul>
  </PaneCard>;
}

const shortDate = value => new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });

export function ProjectDashboard({ project }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await projectsApi.dashboard(project.id));
    } catch (caught) {
      setError(caught?.message || "The dashboard could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [project.id]);

  if (loading) return <div className="grid min-h-32 place-items-center"><LoadingSpinner label="Loading dashboard..."/></div>;
  if (error) return <Alert tone="danger">{error}</Alert>;
  if (!data) return null;

  const { summary } = data;
  const variance = summary.schedule_variance;

  return <div className="grid gap-5">
    <PaneHeader title="Dashboard" description="Live counts from the execution board for this project."/>

    {summary.reassignment_required.length > 0 && <div className="flex items-start gap-3 rounded-2xl border border-orange-100 bg-orange-50 px-4 py-3 text-sm text-orange-900">
      <UserX size={17} className="mt-0.5 shrink-0 text-orange-600"/>
      <div>
        <p className="font-medium">Reassignment required</p>
        {summary.reassignment_required.map(item => <p key={item.membership_id}>The active {item.role_type.replace("_", " ")} is marked unavailable.</p>)}
      </div>
    </div>}

    {summary.total_count === 0
      ? <EmptyState icon={<CheckCircle2 size={20}/>} title="No execution tasks yet" description="This project has not generated execution tasks - counts will populate once it is activated."/>
      : <>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <TaskMix summary={summary}/>
          <PaneCard title="Problems on site" description="Open tasks that need someone to act">
            <StatStrip className="sm:grid-cols-2 xl:grid-cols-2" items={[
              { label: "Overdue", value: summary.overdue_tasks.length, tone: "red" },
              { label: "Blocked", value: summary.blocked_tasks.length, tone: "red" },
              { label: "Delayed", value: summary.delayed_tasks.length, tone: "orange" },
              { label: "No update", value: summary.no_update_tasks.length, tone: "yellow" },
            ]}/>
          </PaneCard>
        </div>

        {/* U17: how finished work landed against the frozen baseline. Early is
            shown rather than folded into "not late" - a task delivered ahead of
            plan is a schedule saving, and hiding it would lose every gain the
            project made. */}
        {variance && <PaneCard title="Finished work against the baseline">
          <StatStrip items={[
            { label: "Finished early", value: variance.early_count, tone: "green" },
            { label: "On time", value: variance.on_time_count, tone: "blue" },
            { label: "Finished late", value: variance.late_count, tone: "orange" },
            { label: "Worst overrun", value: variance.worst_late_days ? `${variance.worst_late_days}d` : 0, tone: "red" },
          ]}/>
        </PaneCard>}

        <div className="grid items-start gap-4 xl:grid-cols-2">
          <TaskListCard title="Overdue tasks" tone="red" items={summary.overdue_tasks} renderMeta={item => `Planned finish ${shortDate(item.due_on)}`}/>
          <TaskListCard title="Approval gates at risk" tone="red" items={summary.approval_gates_at_risk} renderMeta={item => item.due_at ? `Due ${shortDate(item.due_at)}` : null}/>
          <TaskListCard title="Pending approvals" tone="violet" items={summary.pending_approvals}/>
          <TaskListCard title="Pending verifications" tone="violet" items={summary.pending_verifications}/>
          <TaskListCard title="No recent update" tone="yellow" items={summary.no_update_tasks} renderMeta={item => `Last activity ${shortDate(item.last_activity_at)}, update due every ${item.update_sla_hours}h`}/>
        </div>
      </>}
  </div>;
}
