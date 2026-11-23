// Shared by "Add task" on a draft project and on a running one. Mirrors the
// backend rule (app/services/project_task_addition.py): Admin anywhere, or
// the project's own PM / Supervisor; only Admin can also add the task to
// the template, because every new project made from it gets the task.

export const canAddTasks = user => ["super_admin", "admin", "project_manager", "supervisor"].includes(user?.role);
export const canAddToTemplate = user => ["super_admin", "admin"].includes(user?.role);

export function TaskScopeChoice({ value, onChange, canTemplate, disabled = false }) {
  const options = [
    { key: "project", label: "Only this project", help: "The template and other projects stay as they are." },
    { key: "template", label: "This project and the template", help: "Publishes a new template version with this task. New projects get it; projects already made from the template don't." },
  ];
  return <fieldset className="grid gap-2" disabled={disabled}>
    <legend className="mb-2 text-sm font-bold text-slate-700">Add this task to</legend>
    {options.map(option => {
      const locked = option.key === "template" && !canTemplate;
      return <label key={option.key} className={`flex gap-3 rounded-xl border p-3 text-sm ${value === option.key ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white"} ${locked ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
        <input type="radio" name="task-scope" value={option.key} checked={value === option.key} disabled={locked} onChange={() => onChange(option.key)} className="mt-1"/>
        <span><strong className="block font-medium text-slate-900">{option.label}</strong><span className="mt-0.5 block text-xs leading-5 text-slate-500">{locked ? "Only an Admin can change the template." : option.help}</span></span>
      </label>;
    })}
  </fieldset>;
}

// What happened on the template, for the message shown after saving.
export function templateOutcome(template) {
  if (!template) return null;
  if (template.added) {
    return { ok: true, text: `Also added to the template as ${template.task_code} - version ${template.version_no} is now published.` };
  }
  const draft = template.draft_version_no ? ` A draft (version ${template.draft_version_no}) was left for an Admin to finish in Templates.` : "";
  return { ok: false, text: `The task was added to this project, but not to the template: ${template.error}.${draft}` };
}
