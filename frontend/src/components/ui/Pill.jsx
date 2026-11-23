import { cn } from "../../utils/cn";
const tones = { blue: "bg-blue-50 text-blue-800", green: "bg-emerald-50 text-emerald-800", red: "bg-rose-50 text-rose-800", orange: "bg-orange-50 text-orange-800", yellow: "bg-yellow-50 text-yellow-800", gray: "bg-slate-100 text-slate-700", violet: "bg-violet-50 text-violet-800" };
export function Pill({ children, tone = "blue", className }) { return <span className={cn("inline-flex w-fit items-center rounded-md px-2 py-0.5 text-xs font-medium capitalize leading-5", tones[tone] || tones.blue, className)}>{children}</span>; }
