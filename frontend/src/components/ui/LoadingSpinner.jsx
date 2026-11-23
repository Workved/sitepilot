import { LoaderCircle } from "lucide-react";
import { cn } from "../../utils/cn";

export function LoadingSpinner({ label = "Loading", className }) {
  return <span role="status" className={cn("inline-flex items-center gap-2 text-sm text-slate-500", className)}><LoaderCircle aria-hidden="true" className="animate-spin text-blue-600" size={18} /><span>{label}</span></span>;
}
