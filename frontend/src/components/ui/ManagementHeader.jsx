import { Button } from "./Button";
// The shell's top bar already shows the module name, so this header leads
// with the page's own title; the eyebrow stays as quiet context, not a
// tracked-out all-caps label.
export function ManagementHeader({ eyebrow, title, subtitle, actionLabel, actionIcon, onAction }) {
  return <section className="flex flex-col gap-5 rounded-[22px] border border-line bg-white p-6 sm:flex-row sm:items-end sm:justify-between"><div className="min-w-0">{eyebrow && <p className="text-[13px] text-slate-500">{eyebrow}</p>}<h2 className="mt-1 text-[28px] font-normal leading-tight tracking-[-0.02em] text-slate-950">{title}</h2>{subtitle && <span className="mt-1.5 block max-w-2xl text-sm leading-6 text-slate-500">{subtitle}</span>}</div>{actionLabel && <Button size="lg" onClick={onAction}>{actionIcon}{actionLabel}</Button>}</section>;
}
