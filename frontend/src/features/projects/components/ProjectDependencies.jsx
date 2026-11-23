import { AlertTriangle, ArrowRight, Check, GitBranch, Plus, RotateCcw, Search } from "lucide-react";
import { PaneHeader, PaneLoading } from "./PaneKit";
import { useEffect, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, EmptyState, Pill } from "../../../components/ui";
import { ProjectManualDependencyModal } from "./ProjectManualDependencyModal";
import { isOrgAdmin } from "../../../utils/constants";

const typeLabel = { finish_to_start: "Finish to Start", start_to_start: "Start to Start" };

export function ProjectDependencies({ project, user }) {
  const [data, setData] = useState({ total: 0, excluded_warning_count: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [query, setQuery] = useState("");
  const [blockingOnly, setBlockingOnly] = useState(false);
  const tasks = project.tasks || project.project_tasks || [];
  const submitRef = useRef(false);
  const canGenerate = ["admin", "super_admin"].includes(user.role) && project.status === "draft";
  // Adding a dependency reshapes the schedule, so it follows the same
  // authority as applicability decisions: Admin/Super Admin only.
  const canAddManual = isOrgAdmin(user) && project.status === "draft";

  async function load() {
    setLoading(true); setError("");
    try { setData(await projectsApi.dependencies(project.id)); }
    catch (caught) { setError(caught?.message || "Unable to load project dependencies."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [project.id]);

  async function generate() {
    if (!canGenerate || !confirmed || busy || submitRef.current) return;
    submitRef.current = true; setBusy(true); setError("");
    try { await projectsApi.generateDependencies(project.id); setConfirmed(false); await load(); }
    catch (caught) { setError(caught?.message || "Unable to generate project dependencies."); }
    finally { submitRef.current = false; setBusy(false); }
  }

  const term = query.trim().toLowerCase();
  const visible = data.items.filter(item => (!blockingOnly || item.blocking) && (!term || [item.predecessor_code, item.successor_code, item.predecessor_title, item.successor_title, item.rule_text]
    .some(value => String(value || "").toLowerCase().includes(term))));
  const blockingCount = data.items.filter(item => item.blocking).length;

  return <div className="grid gap-5">
    <PaneHeader
      title="Dependencies"
      description="Which task has to finish (or start) before another can begin, remapped from the template to this project's tasks."
      meta={!loading && data.total > 0 && <>
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{data.total} dependencies</span>
        {blockingCount > 0 && <span className="rounded-md bg-rose-50 px-2 py-0.5 text-xs text-rose-800">{blockingCount} blocking</span>}
        {data.excluded_warning_count > 0 && <span className="rounded-md bg-orange-50 px-2 py-0.5 text-xs text-orange-800">{data.excluded_warning_count} warnings</span>}
      </>}
      actions={canAddManual && <Button onClick={() => setShowCreateModal(true)}><Plus size={16}/> Create Manual Dependency</Button>}
    />
    {error && <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}<Button variant="secondary" size="sm" onClick={load}><RotateCcw size={15}/> Retry</Button></div>}
    {loading ? <PaneLoading label="Loading dependencies..."/> : data.total === 0 ? <>
      <EmptyState icon={<GitBranch size={20}/>} title="No project dependencies generated" description="Generate dependencies after the complete project task snapshot exists."/>
      {canGenerate && <section className="rounded-[20px] border border-line bg-white p-5"><label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5 size-4 accent-slate-950"/><span>I confirm project tasks are reviewed. Dependency generation remains Draft and does not activate work.</span></label><Button className="mt-4 w-full sm:w-auto" disabled={!confirmed || busy} loading={busy} onClick={generate}>Generate dependencies</Button></section>}
    </> : <section className="overflow-hidden rounded-[20px] border border-line bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <label className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 focus-within:border-blue-600 focus-within:bg-white">
          <Search size={16} className="text-slate-500" aria-hidden="true"/>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search by task code or name" aria-label="Search dependencies" className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"/>
        </label>
        {blockingCount > 0 && <button type="button" aria-pressed={blockingOnly} onClick={() => setBlockingOnly(value => !value)} className={`h-10 rounded-xl border px-3 text-[13px] transition-colors ${blockingOnly ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"}`}>Blocking only</button>}
      </div>
      <ol className="divide-y divide-slate-100">
        {visible.map(item => <li key={item.id} className={`grid gap-x-4 gap-y-2 px-4 py-3.5 sm:grid-cols-[3rem_minmax(0,1fr)_auto] sm:items-start ${item.excluded_task_warning ? "bg-orange-50/60" : ""}`}>
          <span className="text-xs tabular-nums text-slate-400 sm:pt-0.5">#{item.sequence}</span>
          <div className="min-w-0">
            <div className="grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-center">
              <TaskRef code={item.predecessor_code} title={item.predecessor_title}/>
              <ArrowRight size={15} className="hidden text-slate-400 sm:block" aria-label="then"/>
              <TaskRef code={item.successor_code} title={item.successor_title}/>
            </div>
            {item.rule_text && <p className="mt-1.5 text-xs leading-5 text-slate-500">{item.rule_text}</p>}
            {item.excluded_task_warning && <p className="mt-2 flex items-start gap-1.5 text-xs text-orange-800"><AlertTriangle size={14} className="mt-0.5 shrink-0"/>This relationship includes an excluded task and requires review.</p>}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{typeLabel[item.dependency_type]}</span>
            {item.blocking && <Pill tone="red">Blocking</Pill>}
          </div>
        </li>)}
        {visible.length === 0 && <li className="px-4 py-8 text-center text-sm text-slate-500">No dependencies match.</li>}
      </ol>
      <p className="flex items-center gap-2 border-t border-line bg-slate-50 px-4 py-2.5 text-xs text-slate-500"><Check size={14} className="text-emerald-600"/>{data.total} dependencies generated. Retry creates no duplicates.</p>
    </section>}
    {showCreateModal && <ProjectManualDependencyModal projectId={project.id} tasks={tasks} onClose={() => setShowCreateModal(false)} onCreated={load} />}
  </div>;
}

function TaskRef({ code, title }) {
  return <span className="flex min-w-0 items-baseline gap-2">
    <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-xs tabular-nums text-slate-700">{code}</span>
    <span className="truncate text-sm text-slate-950" title={title}>{title}</span>
  </span>;
}
