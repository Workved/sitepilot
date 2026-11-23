import { cn } from "../../utils/cn";
import { LoaderCircle } from "lucide-react";

// Primary is ink, not blue: the redesign keeps blue for data, links and
// focus, so the main call to action reads as the one solid dark shape.
const variants = {
  primary: "bg-slate-950 text-white hover:bg-slate-800 focus-visible:outline-slate-950",
  secondary: "border border-slate-200 bg-white text-slate-800 hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-blue-600",
  ghost: "bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-950 focus-visible:outline-blue-600",
  danger: "border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 focus-visible:outline-rose-600",
};
const sizes = { sm: "min-h-9 rounded-lg px-3 text-sm", md: "min-h-11 rounded-xl px-4 text-sm", lg: "min-h-12 rounded-xl px-5 text-[15px]", icon: "size-11 rounded-xl p-0" };
export function Button({ as: Component = "button", variant = "primary", size = "md", className, type, children, loading = false, disabled = false, ...props }) {
  return (
    <Component
      type={Component === "button" ? (type || "button") : type}
      className={cn("inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50", variants[variant], sizes[size], className)}
      {...props}
      disabled={Component === "button" ? (loading || disabled) : undefined}
      aria-busy={loading || undefined}
    >
      {loading && <LoaderCircle aria-hidden="true" className="animate-spin" size={17} />}
      {children}
    </Component>
  );
}
