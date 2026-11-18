import "@svar-ui/react-gantt/all.css";
import { Gantt, Tooltip, Willow } from "@svar-ui/react-gantt";
import { useEffect, useMemo, useState } from "react";
import { formatDay, HEALTH } from "./calendarModel";
import { chartRange, highlightWeekends, localDay, plusDays, scalesWithToday, todayLocal, ZOOMS } from "./svarSetup";

// Portfolio on SVAR React Gantt (MIT), read-only. One row per project from
// start to handover (or to the forecast finish when late): coloured by
// health, filled by % done, with the late part striped. External approvals
// with a due date sit under each project as milestones. A Today milestone
// sits at the top (date markers are a SVAR PRO feature).

const RUNNING = ["active", "on_hold"];

export function toPortfolioData(projects) {
  const rows = [];
  for (const project of projects) {
    const start = localDay(project.start_date);
    if (!start) continue;
    const handover = localDay(project.target_handover_date) || localDay(project.forecast_finish_date) || start;
    const forecast = localDay(project.forecast_finish_date);
    const finish = project.days_late > 0 && forecast && forecast > handover ? forecast : handover;
    const end = plusDays(finish < start ? start : finish, 1);
    const total = (end - start) / 86400000;
    const lateShare = project.days_late > 0 && total > 0 ? Math.min(100, Math.round((100 * project.days_late) / total)) : 0;
    const approvals = (project.approvals || []).filter(a => localDay(a.due_date));
    rows.push({
      id: project.project_id, text: project.name, type: "task", start, end, open: false, progress: project.progress_pct,
      health: project.status === "draft" ? "draft" : project.health, lateShare, source: project, isProject: true,
    });
    approvals.forEach((approval, index) => {
      const due = localDay(approval.due_date);
      rows.push({ id: `${project.project_id}:a${index}`, parent: project.project_id, text: approval.name, type: "task", start: due, end: plusDays(due, 1), approval, isApproval: true });
    });
  }
  return rows;
}

// Google-Calendar-style: soft tint by health, a coloured left edge, the
// project name and % done inside, the late part striped at the end.
const PROJECT_CHIP = {
  on_track: { chip: "bg-emerald-50 border-emerald-500 text-emerald-900", fill: "bg-emerald-200/70" },
  at_risk: { chip: "bg-amber-50 border-amber-500 text-amber-900", fill: "bg-amber-200/70" },
  delayed: { chip: "bg-rose-50 border-rose-500 text-rose-900", fill: "bg-rose-200/70" },
  completed: { chip: "bg-slate-100 border-slate-400 text-slate-600", fill: "bg-slate-200" },
};

function ProjectBar({ data }) {
  if (data.isApproval) {
    // Same pin marker as tasks on the Gantt, with the approval's name after it.
    const pin = data.approval.overdue ? "bg-rose-600" : data.approval.status === "approved" ? "bg-emerald-600" : "bg-amber-500";
    return <div className="relative flex h-full w-full items-center">
      <span className={`size-3.5 shrink-0 rounded-full ring-2 ring-white ${pin}`}/>
      <span className="pointer-events-none absolute left-full top-1/2 ml-1 -translate-y-1/2 whitespace-nowrap text-xs font-bold text-slate-800">{data.text}</span>
    </div>;
  }
  if (!data.isProject) return null;
  if (data.health === "draft") return <div className="flex h-full w-full items-center overflow-hidden rounded-md border-l-4 border-slate-300 bg-white px-2 text-[11px] font-bold text-slate-500 outline-1 outline-dashed outline-slate-300">{data.text} · not started</div>;
  const tone = PROJECT_CHIP[data.health] || PROJECT_CHIP.on_track;
  return <div className={`relative flex h-full w-full items-center overflow-hidden rounded-md border-l-4 shadow-sm ${tone.chip}`}>
    <div className={`absolute inset-y-0 left-0 ${tone.fill}`} style={{ width: `${data.health === "completed" ? 100 : data.progress}%` }}/>
    {data.lateShare > 0 && <div className="absolute inset-y-0 right-0 bg-[repeating-linear-gradient(45deg,#fecdd3,#fecdd3_4px,transparent_4px,transparent_8px)]" style={{ width: `${data.lateShare}%` }}/>}
    <span className="relative truncate px-2 text-[11px] font-bold">{data.text} · {data.progress}%</span>
  </div>;
}

function makeTooltip(rowsById) {
  return function TooltipContent({ data }) { return <ProjectTooltip row={rowsById.get(data?.task?.id)}/>; };
}

function ProjectTooltip({ row }) {
  if (!row) return null;
  if (row.isApproval) return <div className="rounded-lg border border-slate-200 bg-white p-2 text-xs shadow"><b>{row.text}</b><br/>Due {formatDay(row.approval.due_date)} · {row.approval.status}{row.approval.overdue ? " · overdue" : ""}</div>;
  const project = row.source;
  return <div className="w-72 rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-lg">
    <p className="font-black text-slate-900">{project.name}</p>
    <p className="mt-1 font-bold text-slate-600">{project.status === "draft" ? "Not started" : (HEALTH[project.health] || HEALTH.on_track).label}{project.days_late > 0 ? ` · ${project.days_late} days late` : ""}</p>
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-slate-600">
      <dt className="font-bold">Start</dt><dd>{formatDay(project.start_date)}</dd>
      <dt className="font-bold">Handover</dt><dd>{formatDay(project.target_handover_date)}</dd>
      {project.forecast_finish_date && <><dt className="font-bold">Forecast</dt><dd>{formatDay(project.forecast_finish_date)}</dd></>}
      <dt className="font-bold">Progress</dt><dd>{project.completed_count}/{project.task_count} tasks · {project.progress_pct}%</dd>
      {project.pm_name && <><dt className="font-bold">PM</dt><dd>{project.pm_name}</dd></>}
      {project.blocked_count > 0 && <><dt className="font-bold">Blocked</dt><dd className="text-rose-700">{project.blocked_count} tasks</dd></>}
    </dl>
  </div>;
}

function HealthCell({ row }) {
  if (row.isApproval) return <span className={`text-[11px] font-bold ${row.approval.overdue ? "text-rose-700" : "text-slate-500"}`}>Due {formatDay(row.approval.due_date)}</span>;
  const project = row.source;
  if (project.status === "draft") return <span className="text-[11px] font-black text-slate-500">Not started</span>;
  const tone = HEALTH[project.health] || HEALTH.on_track;
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-black ${tone.pill}`}>{project.days_late > 0 ? `${project.days_late}d late` : tone.label}</span>;
}

const COLUMNS = [
  { id: "text", header: "Project", flexgrow: 1 },
  { id: "health", header: "Health", width: 120, cell: HealthCell },
  { id: "handover", header: "Handover", width: 100, align: "center", template: (_value, row) => (row?.source?.target_handover_date ? formatDay(row.source.target_handover_date) : "") },
];

export function PortfolioTimeline({ rows: projects, zoom = "quarter", todaySignal = 0, onOpenProject }) {
  const [api, setApi] = useState(null);
  const today = todayLocal();
  const rows = useMemo(() => toPortfolioData(projects), [projects]);
  const tooltip = useMemo(() => makeTooltip(new Map(rows.map(row => [row.id, row]))), [rows]);
  const range = useMemo(() => chartRange(rows.flatMap(row => [row.start, row.end]), zoom), [rows, zoom]);
  const config = ZOOMS[zoom] || ZOOMS.quarter;
  const counts = projects.reduce((acc, project) => ({ ...acc, [project.health]: (acc[project.health] || 0) + 1 }), {});

  // Open on today, and the Today button scrolls back to it.
  useEffect(() => { api?.exec?.("scroll-chart", { date: plusDays(today, -30) }); }, [api, todaySignal]); // eslint-disable-line react-hooks/exhaustive-deps

  function init(ganttApi) {
    setApi(ganttApi);
    ganttApi.on("select-task", ev => {
      const project = projects.find(item => item.project_id === ev.id);
      if (project && RUNNING.includes(project.status)) onOpenProject?.(project.project_id);
    });
  }

  return <div className="grid gap-3">
    <div className="flex flex-wrap gap-2">
      {["on_track", "at_risk", "delayed", "completed"].map(key => <span key={key} className={`rounded-full border px-3 py-1 text-xs font-black ${HEALTH[key].pill}`}>{counts[key] || 0} {HEALTH[key].label.toLowerCase()}</span>)}
    </div>
    <div className="siteops-gantt overflow-hidden rounded-2xl border border-slate-200 bg-white" style={{ height: Math.min(Math.max(rows.length * 44 + 90, 300), 680) }} data-testid="svar-portfolio">
      <Willow>
        <Tooltip api={api} content={tooltip}>
          <Gantt key={zoom} init={init} readonly tasks={rows} links={[]} columns={COLUMNS} scales={scalesWithToday(zoom, today)} lengthUnit={config.lengthUnit}
            cellWidth={config.cellWidth} cellHeight={44} scaleHeight={30} start={range.start} end={range.end} gridWidth={460}
            highlightTime={highlightWeekends} taskTemplate={ProjectBar}/>
        </Tooltip>
      </Willow>
    </div>
    <p className="text-xs font-semibold text-slate-500">Bar = start to handover · dark fill = % done · striped red = forecast past handover · dots = external approvals (open a project's row) · today is marked in the date header · click a running project to open its Gantt</p>
  </div>;
}
