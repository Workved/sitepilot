import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import listPlugin from "@fullcalendar/list";
import { useMemo } from "react";
import { taskState } from "./calendarModel";
import { TARGET_STYLE, targetLabel, taskSchedule } from "./scheduleModel";
import { localDay, plusDays, todayLocal } from "./svarSetup";

// Month view on FullCalendar (MIT standard plugins: day grid + list). Each
// task is a bar across its planned days, coloured by its state, with days
// late in the title; project start and handover are all-day milestones.
// Clicking a task opens it.

// Google-Calendar-style: soft tint, coloured left edge (border), dark text.
const EVENT_COLORS = {
  done: { bg: "#ecfdf5", border: "#10b981", text: "#064e3b" },
  active: { bg: "#eff6ff", border: "#3b82f6", text: "#1e3a8a" },
  review: { bg: "#f5f3ff", border: "#8b5cf6", text: "#4c1d95" },
  blocked: { bg: "#fff1f2", border: "#f43f5e", text: "#881337" },
  planned: { bg: "#f8fafc", border: "#94a3b8", text: "#334155" },
  cancelled: { bg: "#f1f5f9", border: "#cbd5e1", text: "#94a3b8" },
};

export function toCalendarEvents(tasks, project, today, targets = []) {
  const events = [];
  for (const task of tasks) {
    const start = localDay(task.planned_start_date);
    if (!start || task.lifecycle_status === "cancelled") continue;
    const end = plusDays(localDay(task.planned_end_date) || start, 1);
    const state = taskState(task, today);
    const color = EVENT_COLORS[state.late > 0 && state.tone !== "done" ? "blocked" : state.tone] || EVENT_COLORS.planned;
    // The first schedule tag (early/late/moved) rides along in the title.
    // The server's lateness wins; otherwise an early tag ("Done 3 days early").
    const tag = taskSchedule(task, today).tags.find(item => item.tone === "early" || item.tone === "started");
    const suffix = state.late > 0 ? ` · ${state.late}d late` : tag ? ` · ${tag.text}` : "";
    events.push({
      id: task.id, title: `${task.title}${suffix}`,
      start, end, allDay: true, backgroundColor: color.bg, borderColor: color.border, textColor: color.text,
      extendedProps: { taskId: task.id, label: state.label },
    });
  }
  // Same chip style as tasks, with a dark edge, so the calendar stays consistent.
  const milestone = (id, title, value) => { const day = localDay(value); if (day) events.push({ id, title, start: day, allDay: true, display: "block", backgroundColor: "#f1f5f9", borderColor: "#0f172a", textColor: "#0f172a" }); };
  milestone("key:start", "⚑ Project start", project?.start_date);
  milestone("key:handover", "⚑ Handover", project?.target_handover_date);
  const titleById = new Map(tasks.map(task => [task.id, task.title]));
  for (const target of targets.filter(item => item.status === "active")) {
    const day = localDay(target.target_date);
    if (!day) continue;
    const style = TARGET_STYLE[target.outcome?.state || "open"];
    const name = target.kind === "project" ? target.title : titleById.get(target.task_id) || target.task_label;
    events.push({
      id: `target:${target.id}`, title: `◆ ${name}`, start: day, allDay: true, display: "block",
      backgroundColor: "#ffffff", borderColor: style.color, textColor: "#0f172a",
      extendedProps: { taskId: target.task_id || null, label: targetLabel(target) },
    });
  }
  return events;
}

export function MonthCalendar({ tasks, project, onOpenTask, targets = [] }) {
  const today = todayLocal();
  const events = useMemo(() => toCalendarEvents(tasks, project, today, targets), [tasks, project, targets]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div className="grid gap-3">
    <div className="siteops-calendar rounded-2xl border border-slate-200 bg-white p-3" data-testid="fullcalendar-month">
      <FullCalendar
        plugins={[dayGridPlugin, listPlugin]}
        initialView="dayGridMonth"
        headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth,listMonth" }}
        buttonText={{ today: "Today", dayGridMonth: "Month", listMonth: "List" }}
        firstDay={1}
        height="auto"
        dayMaxEvents={3}
        events={events}
        eventClick={info => { const id = info.event.extendedProps.taskId; if (id) { info.jsEvent.preventDefault(); onOpenTask(id); } }}
        eventDidMount={info => { info.el.title = info.event.extendedProps.label ? `${info.event.title} - ${info.event.extendedProps.label}` : info.event.title; }}
      />
    </div>
    <p className="text-xs font-semibold text-slate-500">Each task runs across its planned days · blue = in progress · green = done · violet = needs review · red = blocked or late · grey = not started · ⚑ = project start and handover · ◆ = target</p>
  </div>;
}
