import { createPortal } from "react-dom";
import { AlertTriangle, ClipboardEdit, Paperclip, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button, Pill } from "../../../components/ui";
import { actorProjectRoles, STATUS_TONE, TaskDetailContent } from "./TaskDetailContent";
import { taskTypeOf } from "./executionViewHelpers";
import { COMPUTED_READINESS_STATES, readinessLabel, readinessTone } from "./TaskReadinessPanel";

const TABS = [
  ["overview", "Overview"],
  ["actions", "Action Forms"],
  ["activity", "Activity Log"],
];

const FOOTER_TONE = {
  blue: "text-slate-700", red: "text-rose-700", amber: "text-orange-700", gray: "text-slate-500",
};

function anchorTo(id) {
  document.getElementById(id)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

// Right-side overlay drawer for a task's full detail - large, scrolls
// internally, backdrop behind it, page behind locked from scrolling while
// it's open. Shared by the Admin/PM/Super Admin Execution Calendar and the
// Supervisor 3-Day Operations Board. Three tabs only (Overview/Action
// Forms/Activity Log); all business logic (permissions, transitions, forms)
// lives in TaskDetailContent and is only reorganized here, never duplicated.
export function TaskDetailDrawer({ projectId, project, task, user, candidates, onClose, onChanged }) {
  const [activeTab, setActiveTab] = useState("overview");
  // Bumped on every click so re-requesting the SAME kind while the panel is
  // already open still re-triggers TaskBlockerDelayPanel's effect (a plain
  // string prop wouldn't change value on a repeat click).
  const [blockerDelayRequest, setBlockerDelayRequest] = useState(null);
  const [footer, setFooter] = useState(null);

  // The page behind the drawer must not scroll while it's open.
  useEffect(() => {
    if (!task) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [task]);

  useEffect(() => { setActiveTab("overview"); }, [task?.id]);

  // Memoized, not recomputed as a fresh array every render: TaskDetailContent
  // depends on `roles` inside the effect that lifts the footer descriptor up
  // via `onFooterState`/`setFooter` - a new array reference every render
  // would retrigger that effect every time this component re-renders for
  // ANY reason (including the footer state update itself), which is an
  // infinite render loop, not just a wasted recompute.
  const roles = useMemo(() => actorProjectRoles(project, user), [project, user]);
  const taskType = taskTypeOf(task);

  if (!task) return null;

  function goToActionForms(anchorId) {
    setActiveTab("actions");
    // The Action Forms pane only exists in the DOM once this tab is active,
    // so the scroll has to wait a tick for it to mount.
    requestAnimationFrame(() => anchorTo(anchorId));
  }

  function requestBlockerDelay() {
    setBlockerDelayRequest({ kind: "blocker", nonce: Date.now() });
    goToActionForms("action-blockers-delays");
  }

  const meta = [task.phase, task.category].filter(Boolean).join(" / ") || "Unphased";

  return createPortal(<>
    <div className="fixed inset-0 z-40 bg-slate-950/30" onClick={onClose} aria-hidden="true"/>
    <aside
      className="fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-canvas shadow-[-16px_0_50px_rgba(21,23,26,.14)] sm:w-[820px] sm:max-w-[92vw] sm:rounded-l-[26px]"
      aria-label={`Task detail - ${task.original_code}`}
    >
      <header className="border-b border-line bg-white px-5 pb-0 pt-5 sm:rounded-tl-[26px] sm:px-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="flex flex-wrap gap-x-2 text-sm text-slate-500"><span className="tabular-nums">{task.original_code}</span><span>{meta}</span></p>
            <h2 className="mt-1 text-2xl font-light leading-tight tracking-[-0.01em] text-slate-950">{task.title}</h2>
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
              {COMPUTED_READINESS_STATES.includes(task.readiness?.state) && <Pill tone={readinessTone(task.readiness.state)}>{readinessLabel(task.readiness.state)}</Pill>}
              {taskType && <Pill tone={taskType.tone}>{taskType.label}</Pill>}
              {taskType?.flow && <span className="text-xs text-slate-500">{taskType.flow}</span>}
            </div>
          </div>
          <button type="button" aria-label="Close task detail" onClick={onClose} className="grid size-10 shrink-0 place-items-center rounded-xl text-slate-500 transition hover:bg-slate-100 hover:text-slate-950">
            <X size={19}/>
          </button>
        </div>

        {/* Quick actions switch to Action Forms and scroll to the one real
            section inside TaskDetailContent - no duplicated form logic. */}
        {!["completed", "cancelled"].includes(task.lifecycle_status) && <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => goToActionForms("action-progress")}><ClipboardEdit size={14}/> Update Progress</Button>
          <Button size="sm" variant="secondary" onClick={() => goToActionForms("action-progress")}><Paperclip size={14}/> Add Evidence</Button>
          <Button size="sm" variant="secondary" onClick={requestBlockerDelay}><AlertTriangle size={14}/> Report Delay / Blocker</Button>
        </div>}

        <nav className="-mb-px mt-3 flex gap-1" aria-label="Task detail tabs">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-current={activeTab === key ? "true" : undefined}
              onClick={() => setActiveTab(key)}
              className={`inline-flex min-h-11 items-center px-2.5 text-sm transition-colors ${activeTab === key ? "text-slate-950 shadow-[inset_0_-2px_0_var(--color-slate-950)]" : "text-slate-500 hover:text-slate-950"}`}
            >{label}</button>
          ))}
        </nav>
      </header>

      <div className="so-scroll min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
        <TaskDetailContent
          projectId={projectId}
          project={project}
          task={task}
          user={user}
          roles={roles}
          candidates={candidates}
          onChanged={onChanged}
          autoOpenBlockerDelay={blockerDelayRequest?.kind}
          onFooterState={setFooter}
          onRequestReview={() => goToActionForms("action-review")}
          activeTab={activeTab}
        />
      </div>

      {footer && <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-white px-5 py-3.5 sm:px-6">
        <span className={`text-sm ${FOOTER_TONE[footer.tone] || FOOTER_TONE.gray}`}>{footer.helpText}</span>
        <div className="flex items-center gap-2">
          {footer.secondary && <Button variant="secondary" onClick={footer.secondary.onClick} disabled={footer.secondary.disabled} loading={footer.secondary.loading}>{footer.secondary.label}</Button>}
          {footer.primary && <Button onClick={footer.primary.onClick} disabled={footer.primary.disabled} loading={footer.primary.loading}>{footer.primary.label}</Button>}
        </div>
      </footer>}
    </aside>
  </>, document.body);
}
