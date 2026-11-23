import { Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, Field, Input, Modal, Pill, Select, Textarea } from "../../../components/ui";

const initialForm = { title: "", external_party: "", required_by_type: "project_day", required_by_day: "", required_by_date: "", impact: "", reason: "", blocking: true, affected_project_task_ids: [] };

export function ProjectManualGateModal({ projectId, onClose, onCreated }) {
  const [form, setForm] = useState(initialForm);
  const [tasks, setTasks] = useState([]);
  const [loadingTasks, setLoadingTasks] = useState(true);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const [apiError, setApiError] = useState("");
  const submitRef = useRef(false);
  useEffect(() => {
    let active = true;
    projectsApi.templateReviewTasks(projectId, { included: true, page_size: 100 })
      .then(data => { if (active) setTasks(data.items || []); })
      .catch(error => { if (active) setApiError(error?.message || "Unable to load project tasks."); })
      .finally(() => { if (active) setLoadingTasks(false); });
    return () => { active = false; };
  }, [projectId]);

  const selected = useMemo(() => new Set(form.affected_project_task_ids), [form.affected_project_task_ids]);
  function update(field, value) { setForm(current => ({ ...current, [field]: value })); setErrors(current => ({ ...current, [field]: "" })); }
  function toggleTask(id) { setForm(current => ({ ...current, affected_project_task_ids: selected.has(id) ? current.affected_project_task_ids.filter(item => item !== id) : [...current.affected_project_task_ids, id] })); setErrors(current => ({ ...current, affected_project_task_ids: "" })); }
  function validate() {
    const next = {};
    ["title", "external_party", "impact", "reason"].forEach(field => { if (!form[field].trim()) next[field] = "Required."; });
    if (form.required_by_type === "project_day" && (!Number.isInteger(Number(form.required_by_day)) || Number(form.required_by_day) < 1)) next.required_by_day = "Enter a valid project day.";
    if (form.required_by_type === "date" && !form.required_by_date) next.required_by_date = "Select a required-by date.";
    if (form.blocking && !form.affected_project_task_ids.length) next.affected_project_task_ids = "Select at least one included task for a blocking approval.";
    setErrors(next); return !Object.keys(next).length;
  }
  async function submit(event) {
    event.preventDefault();
    if (saving || submitRef.current || !validate()) return;
    submitRef.current = true; setSaving(true); setApiError("");
    try {
      const created = await projectsApi.createManualGate(projectId, {
        title: form.title.trim(), external_party: form.external_party.trim(), required_by_type: form.required_by_type,
        required_by_day: form.required_by_type === "project_day" ? Number(form.required_by_day) : null,
        required_by_date: form.required_by_type === "date" ? form.required_by_date : null,
        affected_project_task_ids: form.affected_project_task_ids, blocking: form.blocking,
        impact: form.impact.trim(), reason: form.reason.trim(),
      });
      onCreated?.(created); onClose();
    } catch (error) { setApiError(error?.message || "The manual approval could not be created."); }
    finally { submitRef.current = false; setSaving(false); }
  }

  return <Modal title="Add manual external approval" subtitle="Create a project-only approval. The published template remains unchanged." onClose={() => { if (!saving) onClose(); }} className="sm:max-w-3xl">
    <form className="grid gap-5" onSubmit={submit}>
      <div className="flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-blue-50 p-4"><div><p className="text-sm font-medium text-blue-950">Project-only scope</p><p className="mt-1 text-xs text-blue-700">The backend assigns a unique manual gate code and the Project Manager as owner.</p></div><Pill tone="blue">Manual source</Pill></div>
      <Field label="Title" htmlFor="manual-gate-title" error={errors.title}><Input id="manual-gate-title" value={form.title} onChange={e => update("title", e.target.value)} disabled={saving}/></Field>
      <Field label="External party" htmlFor="manual-gate-party" error={errors.external_party}><Input id="manual-gate-party" value={form.external_party} onChange={e => update("external_party", e.target.value)} disabled={saving}/></Field>
      <div className="grid gap-4 sm:grid-cols-2"><Field label="Required by" htmlFor="manual-gate-required-type"><Select id="manual-gate-required-type" value={form.required_by_type} onChange={e => update("required_by_type", e.target.value)} disabled={saving}><option value="project_day">Project day</option><option value="date">Calendar date</option></Select></Field>{form.required_by_type === "project_day" ? <Field label="Project day" htmlFor="manual-gate-day" error={errors.required_by_day}><Input id="manual-gate-day" type="number" min="1" value={form.required_by_day} onChange={e => update("required_by_day", e.target.value)} disabled={saving}/></Field> : <Field label="Date" htmlFor="manual-gate-date" error={errors.required_by_date}><Input id="manual-gate-date" type="date" value={form.required_by_date} onChange={e => update("required_by_date", e.target.value)} disabled={saving}/></Field>}</div>
      <label className="flex items-center gap-3 rounded-xl border border-slate-200 p-3 text-sm font-bold text-slate-700"><input type="checkbox" checked={form.blocking} onChange={e => update("blocking", e.target.checked)} disabled={saving}/>Blocking approval</label>
      <Field label="Affected included tasks" hint={loadingTasks ? "Loading tasks..." : `${form.affected_project_task_ids.length} selected`}><div className="max-h-56 overflow-auto rounded-xl border border-slate-200 p-2">{!loadingTasks && !tasks.length ? <p className="p-3 text-sm text-slate-500">No included project tasks are available.</p> : tasks.map(task => <label key={task.id} className="flex items-start gap-3 rounded-lg p-2 text-sm hover:bg-slate-50"><input type="checkbox" className="mt-1" checked={selected.has(task.id)} onChange={() => toggleTask(task.id)} disabled={saving}/><span><strong>{task.code}</strong> — {task.title}<small className="block text-slate-500">{task.phase || "No phase"} · {task.category || "No category"}</small></span></label>)}</div></Field>
      {errors.affected_project_task_ids && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{errors.affected_project_task_ids}</div>}
      <Field label="Impact" htmlFor="manual-gate-impact" error={errors.impact}><Textarea id="manual-gate-impact" value={form.impact} onChange={e => update("impact", e.target.value)} disabled={saving}/></Field>
      <Field label="Reason" htmlFor="manual-gate-reason" error={errors.reason}><Textarea id="manual-gate-reason" value={form.reason} onChange={e => update("reason", e.target.value)} disabled={saving}/></Field>
      {apiError && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{apiError}</div>}
      <div className="grid gap-2 sm:grid-cols-2"><Button type="button" variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button><Button type="submit" loading={saving} disabled={saving || loadingTasks}><Plus size={16}/> Add manual approval</Button></div>
    </form>
  </Modal>;
}
