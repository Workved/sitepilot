import { Star } from "lucide-react";
import { cn } from "../../utils/cn";

/*
 * Shared pieces for vendor feedback: labels, the summary maths and the star
 * display, used by the work history, the profile header and the vendor list.
 */

export const SCORE_FIELDS = [
  ["quality", "Quality of work"],
  ["timeliness", "Timeliness"],
  ["conduct", "Site conduct and safety"],
];

export const REHIRE_OPTIONS = [
  ["yes", "Yes"],
  ["conditional", "With conditions"],
  ["no", "No"],
];
export const REHIRE_LABEL = { yes: "Would hire again", conditional: "Would hire again, with conditions", no: "Would not hire again" };
export const REHIRE_TONE = { yes: "green", conditional: "orange", no: "red" };

// A poor review is only useful with the reason - mirrors the API rule.
export const needsComment = form => Number(form.rating) <= 2 || form.would_rehire === "no";

const round1 = value => Math.round(value * 10) / 10;

export function summarizeFeedback(items = []) {
  if (!items.length) return { count: 0, average: null, rehire: { yes: 0, conditional: 0, no: 0 }, scores: {} };
  const average = round1(items.reduce((sum, item) => sum + item.rating, 0) / items.length);
  const rehire = { yes: 0, conditional: 0, no: 0 };
  items.forEach(item => { rehire[item.would_rehire] = (rehire[item.would_rehire] || 0) + 1; });
  const scores = {};
  SCORE_FIELDS.forEach(([key]) => {
    const given = items.map(item => item[key]).filter(value => value != null);
    scores[key] = given.length ? round1(given.reduce((sum, value) => sum + value, 0) / given.length) : null;
  });
  return { count: items.length, average, rehire, scores };
}

export function groupFeedbackByVendor(items = []) {
  const map = {};
  items.forEach(item => { (map[item.vendor_id] ||= []).push(item); });
  return map;
}

// Read-only stars. Half values round to the nearest whole star for display;
// the number next to them carries the precision.
export function Stars({ value, size = 14, className }) {
  const filled = Math.round(value || 0);
  return <span className={cn("inline-flex items-center gap-0.5", className)} role="img" aria-label={`${value} out of 5 stars`}>
    {[1, 2, 3, 4, 5].map(n => <Star key={n} size={size} aria-hidden="true" className={n <= filled ? "fill-amber-400 text-amber-400" : "fill-slate-200 text-slate-200"}/>)}
  </span>;
}

// "4.2 ★ · 6 reviews" style summary; null when nothing has been said yet.
export function RatingSummary({ summary, compact = false }) {
  if (!summary?.count) return null;
  return <span className="inline-flex items-center gap-1.5 text-sm text-slate-700">
    <Stars value={summary.average} size={compact ? 12 : 14}/>
    <span className="tabular-nums text-slate-950">{summary.average.toFixed(1)}</span>
    {!compact && <span className="text-slate-500">· {summary.count} {summary.count === 1 ? "review" : "reviews"}</span>}
  </span>;
}
