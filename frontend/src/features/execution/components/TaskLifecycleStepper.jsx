import { Check, X } from "lucide-react";
import { cn } from "../../../utils/cn";

// Compact stepper for the required lifecycle: READY -> IN_PROGRESS ->
// SUBMITTED -> REVIEW -> APPROVED, with a REJECTED branch back to
// IN_PROGRESS. Maps 1:1 onto the backend's existing lifecycle_status
// vocabulary (task_lifecycle.py's TASK_LIFECYCLE_STATUSES) - "review"
// covers both `verified` and `approval_pending` (the decision-in-flight
// states), "approved" covers `completed`. No new statuses are introduced.
//
// When the task's approval metadata says no PM/Admin approval is required
// (standard work verified by the Supervisor only, or a milestone), there is
// no real multi-party decision step to show - verification auto-completes
// the task in the same call. That task instead uses a shorter stepper that
// collapses "Review"/"Approved" into a single "Completed" step.
const STEPS_WITH_APPROVAL = [
  { key: "ready", label: "Ready", statuses: ["planned", "ready"] },
  { key: "in_progress", label: "In progress", statuses: ["in_progress"] },
  { key: "submitted", label: "Submitted", statuses: ["submitted"] },
  { key: "review", label: "Review", statuses: ["verified", "approval_pending"] },
  { key: "approved", label: "Approved", statuses: ["completed"] },
];

const STEPS_NO_APPROVAL = [
  { key: "ready", label: "Ready", statuses: ["planned", "ready"] },
  { key: "in_progress", label: "In progress", statuses: ["in_progress"] },
  { key: "submitted", label: "Submitted", statuses: ["submitted", "verified", "approval_pending"] },
  { key: "completed", label: "Completed", statuses: ["completed"] },
];

function activeStepIndex(steps, status) {
  if (status === "rejected" || status === "cancelled") return -1;
  return steps.findIndex(step => step.statuses.includes(status));
}

export function TaskLifecycleStepper({ status, approvalRequired }) {
  if (status === "cancelled") {
    return <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500"><X size={14}/> Cancelled</div>;
  }

  const steps = approvalRequired === false ? STEPS_NO_APPROVAL : STEPS_WITH_APPROVAL;
  const activeIndex = activeStepIndex(steps, status);
  const rejected = status === "rejected";

  return <div className="flex flex-wrap items-center gap-1" aria-label="Task lifecycle progress">
    {steps.map((step, index) => {
      const done = !rejected && index < activeIndex;
      const current = !rejected && index === activeIndex;
      return <span key={step.key} className="flex items-center gap-1">
        <span className={cn(
          "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
          done && "bg-emerald-50 text-emerald-700",
          current && "bg-blue-600 text-white",
          !done && !current && "bg-slate-100 text-slate-400",
        )}>
          {done && <Check size={11}/>}
          {step.label}
        </span>
        {index < steps.length - 1 && <span className={cn("h-px w-3", done ? "bg-emerald-300" : "bg-slate-200")} aria-hidden="true"/>}
      </span>;
    })}
    {rejected && <span className="ml-1 flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700"><X size={11}/> Rejected - back to In progress</span>}
  </div>;
}
