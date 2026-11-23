import { cn } from "../../../utils/cn";

/*
 * Building blocks shared by every tab inside a project workspace, so the
 * tabs read as one product: a plain header row (no card around it), flat
 * bordered cards, and the same stat strip the Overview dashboard uses.
 */

export function PaneHeader({ title, description, meta, actions, className }) {
  return <header className={cn("flex flex-wrap items-end justify-between gap-x-4 gap-y-3", className)}>
    <div className="min-w-0">
      <h3 className="text-[17px] font-medium text-slate-950">{title}</h3>
      {description && <p className="mt-0.5 max-w-2xl text-sm leading-6 text-slate-500">{description}</p>}
      {meta && <div className="mt-2 flex flex-wrap items-center gap-2">{meta}</div>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </header>;
}

export function PaneCard({ title, description, actions, children, className, bodyClassName, as: Tag = "section" }) {
  const hasHeader = title || description || actions;
  return <Tag className={cn("rounded-[20px] border border-line bg-white", className)}>
    {hasHeader && <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
      <div className="min-w-0">
        {title && <h4 className="text-[15px] font-medium text-slate-950">{title}</h4>}
        {description && <p className="mt-0.5 text-[13px] leading-5 text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>}
    <div className={cn("p-5", bodyClassName)}>{children}</div>
  </Tag>;
}

const STAT_COLORS = {
  blue: "var(--color-blue-600)",
  green: "var(--color-ok)",
  orange: "var(--color-behind)",
  red: "#d9483b",
  violet: "var(--color-gate)",
  yellow: "#f2c94c",
  gray: "var(--color-slate-300)",
};

// A row of counts: coloured edge, label, big light number. A zero count
// greys its edge so the eye goes to what is actually non-zero.
export function StatStrip({ items, className }) {
  return <dl className={cn("grid gap-3 sm:grid-cols-2", items.length >= 4 ? "xl:grid-cols-4" : items.length === 3 ? "lg:grid-cols-3" : "", className)}>
    {items.map(({ label, value, hint, tone = "blue" }) => <div key={label} className="flex items-center gap-3 rounded-2xl border border-line bg-white px-4 py-3.5">
      <span className="h-8 w-1.5 shrink-0 rounded" style={{ background: value ? STAT_COLORS[tone] || tone : "var(--color-slate-200)" }} aria-hidden="true"/>
      <div className="min-w-0 flex-1">
        <dt className="truncate text-sm text-slate-950">{label}</dt>
        {hint && <dd className="truncate text-xs text-slate-500">{hint}</dd>}
      </div>
      <dd className={cn("text-2xl font-light tabular-nums leading-none", value ? "text-slate-950" : "text-slate-400")}>{value}</dd>
    </div>)}
  </dl>;
}

// Small labelled fact for detail rows: label above, value below.
export function Fact({ label, children, className }) {
  return <div className={cn("min-w-0", className)}>
    <dt className="text-xs text-slate-500">{label}</dt>
    <dd className="mt-0.5 truncate text-sm text-slate-950">{children}</dd>
  </div>;
}

export function PaneLoading({ label }) {
  return <div className="grid min-h-40 place-items-center rounded-[20px] border border-line bg-white text-sm text-slate-500">{label}</div>;
}
