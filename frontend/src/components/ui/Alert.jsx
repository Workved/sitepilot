import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { cn } from "../../utils/cn";
import { IconButton } from "./IconButton";

const tones = {
  info: { icon: Info, className: "border-blue-100 bg-blue-50 text-blue-900", iconClass: "text-blue-600" },
  success: { icon: CircleCheck, className: "border-emerald-100 bg-emerald-50 text-emerald-900", iconClass: "text-emerald-600" },
  warning: { icon: CircleAlert, className: "border-amber-100 bg-amber-50 text-amber-900", iconClass: "text-amber-600" },
  danger: { icon: CircleAlert, className: "border-rose-100 bg-rose-50 text-rose-900", iconClass: "text-rose-600" },
};

export function Alert({ children, tone = "info", onDismiss, className, ...props }) {
  const config = tones[tone] || tones.info;
  const Icon = config.icon;
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex items-start gap-3 rounded-2xl border bg-white px-4 py-3 text-sm", config.className, className)} {...props}>
      <Icon aria-hidden="true" className={cn("mt-0.5 shrink-0", config.iconClass)} size={18} />
      <div className="min-w-0 flex-1 leading-6">{children}</div>
      {onDismiss && <IconButton aria-label="Dismiss message" title="Dismiss" size="sm" variant="ghost" onClick={onDismiss}><X size={17} /></IconButton>}
    </div>
  );
}
