import { Save, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Alert, Button, LoadingSpinner, Pill, Select } from "../../../components/ui";

const classLabel = value => (value === "class_a" ? "Class A" : "Standard");
const kindLabel = kind => (kind === "approval_gate" ? "Approval Gate" : "Milestone");

// Draft-only per-project override of each work task's Standard/Class A class.
// Defaults come from the template copy; saving changes only this project's
// tasks, never the template. Approval gates and milestones are shown read-only.
export function ProjectTaskClassification({ projectId }) {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({});
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  function apply(result) {
    setData(result);
    setDraft(Object.fromEntries(result.items.filter(item => item.classifiable).map(item => [item.id, item.task_class || "standard"])));
  }

  useEffect(() => {
    let active = true;
    projectsApi.taskClassification(projectId)
      .then(result => { if (active) apply(result); })
      .catch(caught => { if (active) setError(caught?.message || "Task classification could not be loaded."); });
    return () => { active = false; };
  }, [projectId]);

  const changes = useMemo(() => (data?.items || [])
    .filter(item => item.classifiable && draft[item.id] !== (item.task_class || "standard"))
    .map(item => ({ task_id: item.id, task_class: draft[item.id] })), [data, draft]);
  const classACount = Object.values(draft).filter(value => value === "class_a").length;
  const workCount = Object.keys(draft).length;

  if (error && !data) return <Alert tone="danger">{error}</Alert>;
  if (!data) return <section className="grid place-items-center rounded-[20px] border border-line bg-white p-6"><LoadingSpinner/></section>;

  const editable = data.editable;
  const setAll = value => { setSaved(false); setDraft(current => Object.fromEntries(Object.keys(current).map(id => [id, value]))); };

  async function save() {
    setSaving(true);
    setError("");
    try {
      apply(await projectsApi.updateTaskClassification(projectId, changes));
      setSaved(true);
    } catch (caught) {
      setError(caught?.message || "Task classification could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return <section aria-label="Task classification" className="rounded-[20px] border border-line bg-white">
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 p-4 sm:p-5">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-700"><ShieldCheck size={17}/></span>
        <div>
          <h3 className="text-[15px] font-medium text-slate-950">Task classification</h3>
          <p className="mt-0.5 max-w-2xl text-xs leading-5 text-slate-500">
            Class A adds PM approval after Supervisor verification. Defaults come from the template; changes here apply to this project only.
          </p>
        </div>
      </div>
      <Pill tone="yellow">{classACount} Class A · {workCount - classACount} Standard</Pill>
    </header>

    {error && <div className="px-4 pt-3 sm:px-5"><Alert tone="danger">{error}</Alert></div>}
    {saved && !changes.length && <div className="px-4 pt-3 sm:px-5"><Alert tone="success">Task classification saved.</Alert></div>}

    {editable && <div className="flex flex-wrap items-center gap-2 px-4 pt-3 sm:px-5">
      <Button variant="secondary" size="sm" disabled={saving} onClick={() => setAll("standard")}>Set all Standard</Button>
      <Button variant="secondary" size="sm" disabled={saving} onClick={() => setAll("class_a")}>Set all Class A</Button>
      <Button size="sm" className="sm:ml-auto" loading={saving} disabled={!changes.length || saving} onClick={save}>
        <Save size={15}/> Save classification{changes.length ? ` (${changes.length})` : ""}
      </Button>
    </div>}

    <div className="mt-3 max-h-[28rem] overflow-auto border-t border-slate-100">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-slate-50 text-xs font-medium text-slate-500">
          <tr><th className="px-4 py-2 sm:px-5">Code</th><th className="px-2 py-2">Task</th><th className="px-2 py-2">Template default</th><th className="px-4 py-2 sm:px-5">Project classification</th></tr>
        </thead>
        <tbody>
          {data.items.map(item => <tr key={item.id} data-testid="classification-row" className="border-t border-slate-100">
            <td className="px-4 py-2 tabular-nums text-xs text-slate-500 sm:px-5">{item.code}</td>
            <td className="px-2 py-2 text-slate-900">{item.title}</td>
            <td className="px-2 py-2 text-xs text-slate-500">{item.classifiable ? classLabel(item.template_task_class) : kindLabel(item.task_kind)}</td>
            <td className="px-4 py-2 sm:px-5">
              {item.classifiable
                ? <Select aria-label={`Classification for ${item.code}`} value={draft[item.id]} disabled={!editable || saving} onChange={event => { setSaved(false); setDraft(current => ({ ...current, [item.id]: event.target.value })); }} className="min-h-9 w-auto min-w-[120px]">
                    <option value="standard">Standard</option>
                    <option value="class_a">Class A</option>
                  </Select>
                : <Pill tone={item.task_kind === "approval_gate" ? "violet" : "gray"}>{kindLabel(item.task_kind)}</Pill>}
            </td>
          </tr>)}
        </tbody>
      </table>
    </div>
  </section>;
}
