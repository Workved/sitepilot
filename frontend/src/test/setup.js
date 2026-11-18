import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { createElement, useEffect, useRef } from "react";
import { afterEach, vi } from "vitest";

afterEach(() => cleanup());

// jsdom can't lay out SVAR Gantt or FullCalendar (no real sizes or canvas).
// Light stand-ins render the same data - one row per task / event, the
// app's own cell and bar templates, and the click hooks - so tests can
// check what the calendar shows and what clicking does.
vi.mock("@svar-ui/react-gantt", () => {
  const Gantt = ({ tasks = [], links = [], columns = [], taskTemplate: Bar, init }) => {
    // Like the real one: init runs once, with an api that keeps handlers.
    const handlers = useRef({}).current;
    useEffect(() => { init?.({ on: (name, fn) => { handlers[name] = fn; }, exec: () => {} }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return createElement("div", { "data-testid": "gantt-stub", "data-links": links.length },
      tasks.map(task => createElement("div", { key: task.id, role: "row", "data-testid": `gantt-row-${task.code || task.id}`, onClick: () => handlers["select-task"]?.({ id: task.id }) },
        columns.map(column => createElement("span", { key: column.id }, column.cell ? createElement(column.cell, { row: task }) : column.template ? column.template(task[column.id], task) : String(task[column.id] ?? ""))),
        Bar ? createElement(Bar, { data: task }) : null,
      )));
  };
  const Pass = ({ children }) => children;
  return { Gantt, Tooltip: Pass, Willow: Pass, WillowDark: Pass };
});
vi.mock("@svar-ui/react-gantt/all.css", () => ({}));
vi.mock("@fullcalendar/react", () => ({
  default: ({ events = [], eventClick }) => createElement("div", { "data-testid": "calendar-stub" },
    events.map(event => createElement("button", { key: event.id, type: "button", onClick: () => eventClick?.({ event: { title: event.title, extendedProps: event.extendedProps || {} }, jsEvent: { preventDefault: () => {} } }) }, event.title))),
}));
vi.mock("@fullcalendar/daygrid", () => ({ default: {} }));
vi.mock("@fullcalendar/list", () => ({ default: {} }));
