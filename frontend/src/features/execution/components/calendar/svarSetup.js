// Shared settings for SVAR React Gantt (MIT, @svar-ui/react-gantt), used by
// the project Gantt and the portfolio. SVAR works in local Dates; our API
// sends plain calendar days, so they are converted to local midnight here.

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric" });
const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short" });
const DAY_MONTH = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const MONTH = new Intl.DateTimeFormat("en-GB", { month: "short" });
const MONTH_YEAR = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });
const YEAR = new Intl.DateTimeFormat("en-GB", { year: "numeric" });

/** "2026-11-18" (or an ISO instant) -> local Date at midnight. */
export function localDay(value) {
  if (!value) return null;
  const [y, m, d] = String(value).slice(0, 10).split("-").map(Number);
  return y ? new Date(y, m - 1, d) : null;
}
export const plusDays = (date, n) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + n);
export const todayLocal = () => { const now = new Date(); return new Date(now.getFullYear(), now.getMonth(), now.getDate()); };

const quarter = date => `Q${Math.floor(date.getMonth() / 3) + 1} ${date.getFullYear()}`;

// Each zoom is a fixed cell size per header unit, with a two-row header, so
// labels never run into each other. Bars always keep day precision
// (lengthUnit "day") - otherwise SVAR snaps them to the week or month.
export const ZOOMS = {
  day: { lengthUnit: "day", cellWidth: 44, scales: [
    { unit: "month", step: 1, format: date => MONTH_YEAR.format(date) },
    { unit: "day", step: 1, format: date => `${WEEKDAY.format(date).slice(0, 2)} ${DAY.format(date)}` },
  ] },
  week: { lengthUnit: "day", cellWidth: 96, scales: [
    { unit: "month", step: 1, format: date => MONTH_YEAR.format(date) },
    { unit: "week", step: 1, format: date => DAY_MONTH.format(date) },
  ] },
  month: { lengthUnit: "day", cellWidth: 120, scales: [
    { unit: "year", step: 1, format: date => YEAR.format(date) },
    { unit: "month", step: 1, format: date => MONTH.format(date) },
  ] },
  quarter: { lengthUnit: "day", cellWidth: 150, scales: [
    { unit: "year", step: 1, format: date => YEAR.format(date) },
    { unit: "quarter", step: 1, format: date => quarter(date).split(" ")[0] },
  ] },
  year: { lengthUnit: "day", cellWidth: 220, scales: [
    { unit: "year", step: 1, format: date => YEAR.format(date) },
  ] },
};

/** Weekends shaded at day zoom. */
export const highlightWeekends = (date, unit) => (unit === "day" && [0, 6].includes(date.getDay()) ? "wx-weekend" : "");

/** Chart start/end: the dates given, padded so bars don't touch the edges. */
export function chartRange(dates, zoom) {
  const valid = dates.filter(Boolean).map(Number);
  const pad = { day: 3, week: 10, month: 30, quarter: 60, year: 120 }[zoom] || 14;
  const start = plusDays(new Date(Math.min(...valid)), -pad);
  const end = plusDays(new Date(Math.max(...valid)), pad);
  return { start, end };
}

// Today is marked the same way at every zoom: the header cell that contains
// today (its day, week, month, quarter or year) gets the "siteops-now" style.
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const CONTAINS = {
  day: (cell, today) => sameDay(cell, today),
  week: (cell, today) => today >= cell && today < plusDays(cell, 7),
  month: (cell, today) => cell.getFullYear() === today.getFullYear() && cell.getMonth() === today.getMonth(),
  quarter: (cell, today) => cell.getFullYear() === today.getFullYear() && Math.floor(cell.getMonth() / 3) === Math.floor(today.getMonth() / 3),
  year: (cell, today) => cell.getFullYear() === today.getFullYear(),
};

/** The zoom's scales, with today's cell in the bottom row marked. */
export function scalesWithToday(zoom, today) {
  const scales = (ZOOMS[zoom] || ZOOMS.week).scales;
  return scales.map((scale, index) => (index === scales.length - 1
    ? { ...scale, css: date => (CONTAINS[scale.unit]?.(date, today) ? "siteops-now" : "") }
    : scale));
}
