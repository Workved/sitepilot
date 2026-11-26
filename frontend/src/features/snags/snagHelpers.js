/* Pure helpers for the snag list, kept out of components so they can be tested. */

export function todayIso(now = new Date()) {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

// "Overdue" only for open snags with a due date before today.
export function dueState(snag, today = todayIso()) {
  if (!snag.due_date || snag.status === "done") return null;
  if (snag.due_date < today) return "overdue";
  if (snag.due_date === today) return "today";
  return "later";
}

export function dueLabel(snag, today = todayIso()) {
  if (!snag.due_date) return "";
  const state = dueState(snag, today);
  if (state === "today") return "Due today";
  const label = new Date(`${snag.due_date}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return state === "overdue" ? `Overdue · ${label}` : `Due ${label}`;
}

// Open first: urgent, then overdue, then by due date, then newest. Done: most recently closed first.
export function sortSnags(items, today = todayIso()) {
  const rank = snag => (snag.urgent ? 0 : 2) + (dueState(snag, today) === "overdue" ? 0 : 1);
  const open = items.filter(item => item.status === "open").sort((a, b) =>
    rank(a) - rank(b)
    || (a.due_date || "9999").localeCompare(b.due_date || "9999")
    || (b.created_at || "").localeCompare(a.created_at || ""));
  const done = items.filter(item => item.status === "done").sort((a, b) => (b.closed_at || "").localeCompare(a.closed_at || ""));
  return { open, done };
}

export function filterSnags(items, { query = "", mine = false, userId } = {}) {
  const needle = query.trim().toLowerCase();
  return items.filter(item => {
    if (mine && item.assignee?.id !== userId) return false;
    if (!needle) return true;
    return [item.title, item.area, item.notes, item.assignee?.name].some(value => String(value || "").toLowerCase().includes(needle));
  });
}

export function snagSummary(items, today = todayIso()) {
  const open = items.filter(item => item.status === "open");
  return {
    open: open.length,
    urgent: open.filter(item => item.urgent).length,
    overdue: open.filter(item => dueState(item, today) === "overdue").length,
    done: items.length - open.length,
  };
}
