import { AlertCircle, CheckCircle2, CircleDashed, FilterX, Layers3, Plus, RefreshCw, Search, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button, EmptyState, Input, LoadingSpinner, Pill, Select } from "../../../components/ui";
import { projectsApi } from "../../../api/projectsApi";
import { TaskApplicabilityControls } from "./TaskApplicabilityDecisionModal";
import { ProjectManualTaskModal } from "./ProjectManualTaskModal";
import { canAddTasks, canAddToTemplate } from "./TaskScope";
import { ProjectTaskClassification } from "./ProjectTaskClassification";
import { isOrgAdmin } from "../../../utils/constants";

const emptyPage = { items: [], pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 } };
const emptySummary = { total: 0, included: 0, excluded: 0, pending_review: 0 };
const inFlightReads = new Map();

function deduplicatedRead(key, request) {
  if (inFlightReads.has(key)) return inFlightReads.get(key);
  const pending = Promise.resolve().then(request);
  inFlightReads.set(key, pending);
  const clear = () => { if (inFlightReads.get(key) === pending) inFlightReads.delete(key); };
  pending.then(clear, clear);
  return pending;
}

function plannedDays(task) {
  if (task.schedule_classification === "pre_activation") return "Pre-Activation";
  if (task.planned_start_day === task.planned_end_day) return `Day ${task.planned_start_day}`;
  return `Days ${task.planned_start_day}–${task.planned_end_day}`;
}

function sourceLabel(value) {
  return (value || "Unknown").replaceAll("_", " ").replace(/(^|\s)\S/g, match => match.toUpperCase());
}

function TaskState({ task }) {
  if (!task.included || task.decision_state === "excluded") return <Pill tone="red">Excluded</Pill>;
  if (task.decision_state === "included") return <Pill tone="green">Included</Pill>;
  return <Pill tone="orange">Undecided</Pill>;
}

function TaskRow({ projectId, task, onDecided, canDecide }) {
  return <article data-testid="review-task" className="grid gap-3 border-t border-slate-100 px-4 py-4 first:border-t-0 sm:px-5 lg:grid-cols-[76px_minmax(0,1fr)_104px_100px_104px_minmax(220px,auto)] lg:items-center">
    <div className="flex items-center justify-between gap-3 lg:block"><span className="font-mono text-xs font-black tracking-wide text-blue-700">{task.code}</span><div className="lg:hidden"><TaskState task={task}/></div></div>
    <div className="min-w-0"><h5 className="text-sm font-black leading-5 text-slate-950">{task.title}</h5><p className="mt-1 text-xs leading-5 text-slate-500">{task.description || "No additional description."}</p><div className="mt-2 flex flex-wrap gap-2 lg:hidden"><span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-black uppercase tracking-wide text-slate-600">{plannedDays(task)}</span><span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-black uppercase tracking-wide text-slate-600">{sourceLabel(task.source)}</span></div></div>
    <span className="hidden text-xs font-bold text-slate-700 lg:block">{plannedDays(task)}</span>
    <span className={`hidden text-xs font-black capitalize lg:block ${task.applicability === "conditional" ? "text-amber-700" : "text-slate-700"}`}>{task.applicability}</span>
    <div className="hidden lg:block"><TaskState task={task}/><span className="mt-1 block text-[10px] font-bold text-slate-400">{sourceLabel(task.source)}</span></div>
    <TaskApplicabilityControls projectId={projectId} task={task} onDecided={onDecided} canDecide={canDecide}/>
    <span className="text-xs font-black capitalize text-slate-600 lg:hidden">{task.applicability}</span>
  </article>;
}


function mergeTaskTaxonomy(current, tasks) {
  const phases = [...current.phases];
  const categoriesByPhase = Object.fromEntries(Object.entries(current.categoriesByPhase).map(([key, values]) => [key, [...values]]));
  tasks.forEach(task => {
    const phase = (task.phase || "").trim();
    const category = (task.category || "").trim();
    if (!phase) return;
    if (!phases.includes(phase)) phases.push(phase);
    if (!categoriesByPhase[phase]) categoriesByPhase[phase] = [];
    if (category && !categoriesByPhase[phase].includes(category)) categoriesByPhase[phase].push(category);
  });
  return { phases, categoriesByPhase };
}

function groupedTasks(tasks) {
  const phases = new Map();
  tasks.forEach(task => {
    const phase = task.phase || "Unassigned phase";
    const category = task.category || "Unassigned category";
    if (!phases.has(phase)) phases.set(phase, new Map());
    if (!phases.get(phase).has(category)) phases.get(phase).set(category, []);
    phases.get(phase).get(category).push(task);
  });
  return [...phases.entries()];
}

export function ProjectTemplateReview({ projectId, user, projectStatus = "draft", debounceMs = 300 }) {
  const canReview = isOrgAdmin(user) || user?.role === "project_manager";
  // Reading is Admin/Super Admin + the assigned PM; deciding scope is Admin/Super Admin alone.
  const canDecide = isOrgAdmin(user);
  const [result, setResult] = useState(emptyPage);
  const [summary, setSummary] = useState(emptySummary);
  const [loading, setLoading] = useState(canReview);
  const [summaryLoading, setSummaryLoading] = useState(canReview);
  const [error, setError] = useState(null);
  const [summaryError, setSummaryError] = useState(null);
  const [retry, setRetry] = useState(0);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [phase, setPhase] = useState("");
  const [category, setCategory] = useState("");
  const [applicability, setApplicability] = useState("");
  const [included, setIncluded] = useState("");
  const [source, setSource] = useState("");
  const [page, setPage] = useState(1);
  const [manualTaskOpen, setManualTaskOpen] = useState(false);
  const [taskTaxonomy, setTaskTaxonomy] = useState({ phases: [], categoriesByPhase: {} });

  useEffect(() => { const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), debounceMs); return () => window.clearTimeout(timer); }, [search, debounceMs]);
  useEffect(() => { setPage(1); }, [debouncedSearch, phase, category, applicability, included, source]);

  useEffect(() => {
    if (!canReview) return undefined;
    let active = true;
    setLoading(true); setError(null);
    const params = { page, page_size: 100, search: debouncedSearch, phase: phase.trim(), category: category.trim(), applicability, source: source.trim() };
    if (included !== "") params.included = included === "true";
    const requestKey = `project-review:tasks:${projectId}:${JSON.stringify(params)}`;
    deduplicatedRead(requestKey, () => projectsApi.templateReviewTasks(projectId, params))
      .then(tasks => { if (active) { setResult(tasks); setTaskTaxonomy(current => mergeTaskTaxonomy(current, tasks.items || [])); } })
      .catch(caught => { if (active) setError(caught); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [applicability, canReview, category, debouncedSearch, included, page, phase, projectId, retry, source]);

  useEffect(() => {
    if (!canReview) return undefined;
    let active = true;
    setSummaryLoading(true); setSummaryError(null);
    deduplicatedRead(`project-review:summary:${projectId}`, () => projectsApi.templateReviewSummary(projectId))
      .then(counts => { if (active) setSummary(counts); })
      .catch(caught => { if (active) setSummaryError(caught); })
      .finally(() => { if (active) setSummaryLoading(false); });
    return () => { active = false; };
  }, [canReview, projectId, retry]);

  const groups = useMemo(() => groupedTasks(result.items), [result.items]);
  const hasFilters = Boolean(search || phase || category || applicability || included || source);
  function clearFilters() { setSearch(""); setDebouncedSearch(""); setPhase(""); setCategory(""); setApplicability(""); setIncluded(""); setSource(""); setPage(1); }
  function refreshAfterDecision() { setRetry(value => value + 1); }
  function refreshAfterManualTask() { setPage(1); setRetry(value => value + 1); }

  if (!canReview) return <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5" role="status"><h3 className="font-black text-amber-950">Task review is role restricted</h3><p className="mt-1 text-sm leading-6 text-amber-800">Generated-task review is available to Admin and the assigned Project Manager. Existing task generation access is unchanged.</p></section>;

  return <section className="grid gap-4" aria-label="Generated task review">
    {manualTaskOpen && <ProjectManualTaskModal projectId={projectId} phaseOptions={taskTaxonomy.phases} categoriesByPhase={taskTaxonomy.categoriesByPhase} onClose={() => setManualTaskOpen(false)} onCreated={refreshAfterManualTask} canTemplate={canAddToTemplate(user)}/>}
    <header className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 p-5 text-white sm:p-6"><div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-600"><Layers3 size={18}/></span><div><span className="text-[10px] font-black uppercase tracking-[.2em] text-blue-300">Controlled scope review</span><h3 className="mt-1 text-xl font-black tracking-tight">Generated project tasks</h3><p className="mt-1 max-w-2xl text-sm leading-6 text-slate-300">Review the project-owned task snapshot by phase and category before inclusion decisions progress.</p></div></div>{canAddTasks(user) && projectStatus === "draft" && !manualTaskOpen && <Button className="w-full sm:w-auto" onClick={() => setManualTaskOpen(true)}><Plus size={16}/> Add manual task</Button>}</div></header>
    {projectStatus === "draft" && <ProjectTaskClassification projectId={projectId}/>}

    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Review summary">{[
      ["Total", summary.total, Layers3, "bg-blue-50 text-blue-700"], ["Included", summary.included, CheckCircle2, "bg-emerald-50 text-emerald-700"],
      ["Excluded", summary.excluded, XCircle, "bg-rose-50 text-rose-700"], ["Undecided", summary.pending_review, CircleDashed, "bg-amber-50 text-amber-700"],
    ].map(([label, value, Icon, tone]) => <article key={label} className="rounded-2xl border border-slate-200 bg-white p-4"><span className={`grid size-9 place-items-center rounded-xl ${tone}`}><Icon size={17}/></span><strong className="mt-3 block text-2xl font-black text-slate-950">{value}</strong><span className="text-xs font-bold text-slate-500">{label}</span></article>)}</div>

    <div className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-3 sm:grid-cols-2 lg:grid-cols-3">
      <label className="relative sm:col-span-2 lg:col-span-3"><span className="sr-only">Search tasks</span><Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={17}/><Input value={search} onChange={event => setSearch(event.target.value)} className="pl-10" placeholder="Search task code, title or description"/></label>
      <Input aria-label="Filter by phase" value={phase} onChange={event => setPhase(event.target.value)} placeholder="Phase"/>
      <Input aria-label="Filter by category" value={category} onChange={event => setCategory(event.target.value)} placeholder="Category"/>
      <Select aria-label="Filter by applicability" value={applicability} onChange={event => setApplicability(event.target.value)}><option value="">All applicability</option><option value="mandatory">Mandatory</option><option value="conditional">Conditional</option></Select>
      <Select aria-label="Filter by inclusion" value={included} onChange={event => setIncluded(event.target.value)}><option value="">Included and excluded</option><option value="true">Included</option><option value="false">Excluded</option></Select>
      <Input aria-label="Filter by source" value={source} onChange={event => setSource(event.target.value)} placeholder="Source"/>
      {hasFilters && <Button variant="secondary" onClick={clearFilters}><FilterX size={16}/> Clear filters</Button>}
    </div>

    {(loading || summaryLoading) ? <div className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"><LoadingSpinner label="Loading generated tasks..."/></div>
      : (error || summaryError) ? <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert"><div className="flex items-start gap-3"><AlertCircle className="shrink-0 text-rose-700" size={20}/><div><h4 className="font-black text-rose-950">Task review unavailable</h4><p className="mt-1 text-sm text-rose-800">{(error || summaryError).status === 403 ? "You are not assigned to review this project." : (error || summaryError).status === 401 ? "Your session has expired. Sign in again." : "The generated task list could not be loaded."}</p></div></div><Button className="mt-4" variant="secondary" onClick={() => setRetry(value => value + 1)}><RefreshCw size={16}/> Retry</Button></div>
      : !result.items.length ? <EmptyState className="min-h-64 bg-white" icon={<Layers3 size={21}/>} title={hasFilters ? "No tasks match these filters" : "No generated tasks to review"} description={hasFilters ? "Clear one or more filters and try again." : "Generate the controlled task snapshot before starting review."} action={hasFilters ? <Button variant="secondary" onClick={clearFilters}><FilterX size={16}/> Clear filters</Button> : null}/>
      : <div className="grid gap-5">{groups.map(([phaseName, categories]) => <section key={phaseName} className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 sm:px-5"><div><span className="text-[10px] font-black uppercase tracking-[.18em] text-blue-700">Phase</span><h4 className="mt-0.5 font-black text-slate-950">{phaseName}</h4></div><Pill tone="gray">{[...categories.values()].reduce((count, tasks) => count + tasks.length, 0)} tasks</Pill></header>
        {[...categories.entries()].map(([categoryName, tasks]) => <div key={categoryName} className="border-t border-slate-200 first:border-t-0"><div className="flex items-center justify-between bg-white px-4 py-3 sm:px-5"><span className="text-xs font-black uppercase tracking-wide text-slate-500">{categoryName}</span><span className="text-[10px] font-bold text-slate-400">{tasks.length} task{tasks.length === 1 ? "" : "s"}</span></div><div className="border-t border-slate-100">{tasks.map(task => <TaskRow key={task.id} projectId={projectId} task={task} onDecided={refreshAfterDecision} canDecide={canDecide}/>)}</div></div>)}
      </section>)}
      {result.pagination.total_pages > 1 && <nav className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-3" aria-label="Task review pages"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>Previous</Button><span className="text-xs font-black text-slate-500">Page {page} of {result.pagination.total_pages}</span><Button variant="secondary" disabled={page >= result.pagination.total_pages} onClick={() => setPage(value => value + 1)}>Next</Button></nav>}
      </div>}
  </section>;
}
