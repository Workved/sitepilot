/*
 * Small, pure helpers shared by the Communication list, reading pane and
 * composer. Kept out of the components so they can be tested directly.
 */

// The moment a broadcast "happened" for sorting and grouping: when it went
// out, when it is due to go out, or when it was written.
export function broadcastTime(broadcast) {
  return broadcast.sent_at || broadcast.scheduled_at || broadcast.created_at || null;
}

function startOfDay(date) {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy.getTime();
}

const DAY = 86400000;

export function dayLabel(value, now = Date.now()) {
  if (!value) return "Undated";
  const diff = Math.round((startOfDay(value) - startOfDay(now)) / DAY);
  if (diff === 0) return "Today";
  if (diff === -1) return "Yesterday";
  if (diff === 1) return "Tomorrow";
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function timeLabel(value) {
  if (!value) return "";
  return new Date(value).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function dateTimeLabel(value) {
  if (!value) return "";
  return `${new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}, ${timeLabel(value)}`;
}

// Consecutive rows that share a day label, in the order given. `ascending`
// is for the Scheduled list, where the soonest send comes first.
export function groupByDay(broadcasts, { ascending = false, now = Date.now() } = {}) {
  const sorted = [...broadcasts].sort((a, b) => {
    const left = new Date(broadcastTime(a) || 0).getTime();
    const right = new Date(broadcastTime(b) || 0).getTime();
    return ascending ? left - right : right - left;
  });
  const groups = [];
  sorted.forEach(broadcast => {
    const label = dayLabel(broadcastTime(broadcast), now);
    const last = groups[groups.length - 1];
    if (last?.label === label) last.items.push(broadcast);
    else groups.push({ label, items: [broadcast] });
  });
  return groups;
}

export function plural(count, one, many = `${one}s`) {
  return `${count} ${count === 1 ? one : many}`;
}

// One line for the page header, e.g. "3 sent, reached 12 people, 92% delivered".
export function summaryLine(summary) {
  const sent = (summary.messages_sent || 0) + (summary.failed || 0);
  if (!sent && !summary.scheduled) return "Nothing sent yet. Send your first broadcast to a project team.";
  const parts = [`${plural(sent, "message")} sent`];
  if (summary.total_recipients) parts.push(`reached ${plural(summary.total_recipients, "person", "people")}`);
  if (sent) parts.push(`${summary.delivery_success_rate}% delivered`);
  if (summary.scheduled) parts.push(`${summary.scheduled} scheduled`);
  return parts.join(", ");
}
