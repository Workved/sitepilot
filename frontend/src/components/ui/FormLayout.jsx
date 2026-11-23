import { cn } from "../../utils/cn";

export function FormGrid({ children, className }) {
  return <div className={cn("grid grid-cols-1 gap-4 md:grid-cols-2", className)}>{children}</div>;
}

export function FormSection({ title, description, icon: Icon, children, className }) {
  return <section className={cn("overflow-hidden rounded-[20px] border border-line bg-white", className)}><header className="flex items-start gap-3 border-b border-line px-4 py-4 sm:px-5">{Icon && <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-700"><Icon size={18}/></span>}<div><h3 className="text-[15px] font-medium text-slate-950">{title}</h3>{description && <p className="mt-0.5 text-[13px] leading-5 text-slate-500">{description}</p>}</div></header><div className="p-4 sm:p-5">{children}</div></section>;
}

export function DetailGrid({ items, className }) {
  return <div className={cn("grid grid-cols-1 gap-px overflow-hidden rounded-[20px] border border-line bg-line sm:grid-cols-2", className)}>{items.map(({ label, value }) => <article key={label} className="min-w-0 bg-white p-4"><span className="block text-[13px] text-slate-500">{label}</span><strong className="mt-1 block break-words text-[15px] font-normal leading-6 text-slate-900">{value || "Not provided"}</strong></article>)}</div>;
}
