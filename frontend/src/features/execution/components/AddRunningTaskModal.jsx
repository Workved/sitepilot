import { CheckCircle2, Plus, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Input, Modal, Select, Textarea } from "../../../components/ui";
import { TaskScopeChoice, canAddToTemplate, templateOutcome } from "../../projects/components/TaskScope";

const initialForm = {
  title: "", description: "", phase: "", category: "", planned_start_date: "", planned_end_date: "",
  evidence_required: false, after_task_id: "", reason: "", scope: "project",
};

const formatDate = iso => iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";

// Add a task to a project that has already started. It becomes a live task
// straight away, marked "Added after start"; the original plan is kept.
export function AddRunningTaskModal({ projectId, project, user, onClose, onAdded }) {
  const [form, setForm] = useState(initialForm);
  const [tasks, setTasks] = useState([]);
  const [errors, setErrors] = useState({});
  const [apiError, setApiError] = useState("");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null);
  const canTemplate = canAddToTemplate(user);
  const minDate = project?.start_date || "";

  useEffect(() => {
    let active = true;
    taskExecutionApi.list(projectId).then(rows => { if (active) setTasks(rows || []); }).catch(() => {});
    return () => { active = false; };
  }, [projectId]);

  // Phases and categories come from the project's own tasks, so the new task
  // files under the same headings.
  const categoriesByPhase = useMemo(() => {
    const map = new Map();
    tasks.forEach(task => {
      if (!task.phase) return;
      if (!map.has(task.phase)) map.set(task.phase, new Set());
      if (task.category) map.get(task.phase).add(task.category);
    });
    return map;
  }, [tasks]);
  const phases = [...categoriesByPhase.keys()];
  const categories = [...(categoriesByPhase.get(form.phase) || [])];
  const afterOptions = tasks.filter(task => task.lifecycle_status !== "cancelled");

  function update(field, value) {
    setForm(current => field === "phase" ? { ...current, phase: value, category: "" } : { ...current, [field]: value });
    setErrors(current => ({ ...current, [field]: "" }));
  }

  function validate() {
    const next = {};
    ["title", "phase", "category", "reason"].forEach(field => { if (!form[field].trim()) next[field] = "Required."; });
    if (!form.planned_start_date) next.planned_start_date = "Pick a start date.";
    else if (minDate && form.planned_start_date < minDate) next.planned_start_date = `Can't start before the project (${formatDate(minDate)}).`;
    if (!form.planned_end_date) next.planned_end_date = "Pick an end date.";
    else if (form.planned_start_date && form.planned_end_date < form.planned_start_date) next.planned_end_date = "Must be on or after the start date.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(event) {
    event.preventDefault();
    if (saving || !validate()) return;
    setSaving(true); setApiError("");
    try {
      const created = await projectsApi.addRunningTask(projectId, {
        title: form.title.trim(), description: form.description.trim() || null,
        phase: form.phase, category: form.category.trim(),
        planned_start_date: form.planned_start_date, planned_end_date: form.planned_end_date,
        evidence_required: form.evidence_required, after_task_id: form.after_task_id || null,
        reason: form.reason.trim(), add_to_template: form.scope === "template",
      });
      setResult(created);
      onAdded?.(created);
    } catch (error) {
      setApiError(error?.message || "The task couldn't be added.");
    } finally { setSaving(false); }
  }

  if (result) {
    const outcome = templateOutcome(result.template);
    return <Modal title="Task added" onClose={onClose} className="sm:max-w-lg">
      <div className="grid gap-4">
        <p className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-bold text-emerald-900"><CheckCircle2 size={18} className="mt-0.5 shrink-0"/>{result.code} · {result.title} was added to this project ({formatDate(result.planned_start_date)} - {formatDate(result.planned_end_date)}).</p>
        {outcome && <p role={outcome.ok ? "status" : "alert"} className={`flex items-start gap-2 rounded-xl border p-4 text-sm font-bold ${outcome.ok ? "border-blue-200 bg-blue-50 text-blue-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>{outcome.ok ? <CheckCircle2 size={18} className="mt-0.5 shrink-0"/> : <TriangleAlert size={18} className="mt-0.5 shrink-0"/>}{outcome.text}</p>}
        <Button onClick={onClose}>Done</Button>
      </div>
    </Modal>;
  }

  return <Modal title="Add task to this project" subtitle="The project has started, so this task goes live straight away. It's marked as added after start; the original plan is kept." onClose={() => { if (!saving) onClose(); }} className="sm:max-w-2xl">
    <form className="grid gap-5" onSubmit={submit} noValidate>
      <Field label="Title" htmlFor="add-task-title" error={errors.title}><Input id="add-task-title" value={form.title} onChange={e => update("title", e.target.value)} maxLength={500} disabled={saving}/></Field>
      <Field label="Description (optional)" htmlFor="add-task-description"><Textarea id="add-task-description" value={form.description} onChange={e => update("description", e.target.value)} maxLength={5000} disabled={saving} placeholder="What needs to be done"/></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Phase" htmlFor="add-task-phase" error={errors.phase}><Select id="add-task-phase" value={form.phase} onChange={e => update("phase", e.target.value)} disabled={saving}><option value="">Select phase</option>{phases.map(phase => <option key={phase} value={phase}>{phase}</option>)}</Select></Field>
        <Field label="Category" htmlFor="add-task-category" error={errors.category}>{categories.length
          ? <Select id="add-task-category" value={form.category} onChange={e => update("category", e.target.value)} disabled={saving || !form.phase}><option value="">Select category</option>{categories.map(category => <option key={category} value={category}>{category}</option>)}</Select>
          : <Input id="add-task-category" value={form.category} onChange={e => update("category", e.target.value)} maxLength={200} disabled={saving || !form.phase} placeholder={form.phase ? "Category" : "Select phase first"}/>}</Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Start date" htmlFor="add-task-start" error={errors.planned_start_date}><Input id="add-task-start" type="date" min={minDate || undefined} value={form.planned_start_date} onChange={e => update("planned_start_date", e.target.value)} disabled={saving}/></Field>
        <Field label="End date" htmlFor="add-task-end" error={errors.planned_end_date}><Input id="add-task-end" type="date" min={form.planned_start_date || minDate || undefined} value={form.planned_end_date} onChange={e => update("planned_end_date", e.target.value)} disabled={saving}/></Field>
      </div>
      <Field label="Starts after (optional)" htmlFor="add-task-after" hint="It can't start until this task is finished."><Select id="add-task-after" value={form.after_task_id} onChange={e => update("after_task_id", e.target.value)} disabled={saving}><option value="">No - it can start any time</option>{afterOptions.map(task => <option key={task.id} value={task.id}>{task.original_code} · {task.title}</option>)}</Select></Field>
      <label className="flex items-center gap-2 text-sm font-bold text-slate-700"><input type="checkbox" checked={form.evidence_required} onChange={e => update("evidence_required", e.target.checked)} disabled={saving}/> Photo or file evidence required</label>
      <Field label="Reason" htmlFor="add-task-reason" error={errors.reason}><Textarea id="add-task-reason" value={form.reason} onChange={e => update("reason", e.target.value)} maxLength={2000} disabled={saving} placeholder="Why is this task needed now?"/></Field>
      <TaskScopeChoice value={form.scope} onChange={value => update("scope", value)} canTemplate={canTemplate} disabled={saving}/>
      {apiError && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{apiError}</div>}
      <div className="grid gap-2 sm:grid-cols-2"><Button type="button" variant="secondary" disabled={saving} onClick={onClose}>Cancel</Button><Button type="submit" loading={saving} disabled={saving}><Plus size={16}/> Add task</Button></div>
    </form>
  </Modal>;
}
