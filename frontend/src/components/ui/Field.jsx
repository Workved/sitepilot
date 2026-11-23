import { cn } from "../../utils/cn";

const controlClass = "min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-950 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500";

export function Field({ label, hint, error, className, children, htmlFor }) {
  const classes = cn("grid gap-1.5 text-sm font-medium text-slate-700", className);
  const feedback = (error || hint) && <small className={cn("text-[13px] font-normal", error ? "text-rose-600" : "text-slate-500")}>{error || hint}</small>;

  if (htmlFor) {
    return <div className={classes}><label htmlFor={htmlFor}><span>{label}</span></label>{children}{feedback}</div>;
  }

  return <label className={classes}><span>{label}</span>{children}{feedback}</label>;
}

export function Input({ className, ...props }) { return <input className={cn(controlClass, className)} {...props} />; }
export function Select({ className, children, ...props }) { return <select className={cn(controlClass, "appearance-auto", className)} {...props}>{children}</select>; }
export function Textarea({ className, ...props }) { return <textarea className={cn(controlClass, "min-h-24 resize-y leading-6", className)} {...props} />; }
