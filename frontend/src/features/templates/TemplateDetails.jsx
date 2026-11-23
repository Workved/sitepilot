import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  BookOpenCheck,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Copy,
  DatabaseZap,
  FilterX,
  GitBranch,
  Layers3,
  Link2,
  ListChecks,
  PencilLine,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { templatesApi } from "../../api/templatesApi";
import { Alert, Button, EmptyState, Input, LoadingSpinner, Pill, RefreshButton, Select } from "../../components/ui";
import { formatTemplateDate, statusTone } from "./components/TemplateCard";
import { TemplateDependencyCard } from "./components/TemplateDependencyCard";
import { TemplateDependencyTable } from "./components/TemplateDependencyTable";
import { TemplateGateCard } from "./components/TemplateGateCard";
import { TemplateGateTable } from "./components/TemplateGateTable";
import { TemplateTaskCard } from "./components/TemplateTaskCard";
import { TemplateTaskTable } from "./components/TemplateTaskTable";
import { useDebouncedValue } from "./useDebouncedValue";

const emptyTaskPage = { items: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 } };
const emptyDependencyPage = { items: [], pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 } };
const emptyDependencyCounts = { total: 0, finishToStart: 0, startToStart: 0, blocking: 0, invalid: 0 };
const emptyGatePage = { items: [], pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 } };

function SummaryMetric({ icon: Icon, label, value, tone = "blue" }) {
  const tones = {
    blue: "bg-blue-50 text-blue-700",
    cyan: "bg-cyan-50 text-cyan-700",
    amber: "bg-amber-50 text-amber-700",
    emerald: "bg-emerald-50 text-emerald-700",
    rose: "bg-rose-50 text-rose-700",
  };
  return <div className="rounded-2xl border border-slate-200 bg-white p-4">
    <span className={`grid size-9 place-items-center rounded-xl ${tones[tone]}`}><Icon size={18}/></span>
    <strong className="mt-4 block text-2xl font-normal tracking-[-.04em] text-slate-950">{value}</strong>
    <span className="mt-1 block text-xs font-bold text-slate-500">{label}</span>
  </div>;
}

function accessError(error) {
  if (error?.status === 404) return { title: "Template version not found", description: "This version does not exist or is not available to your role." };
  if (error?.status === 403) return { title: "Template access denied", description: "Your role cannot access template management." };
  if (error?.status === 401) return { title: "Session expired", description: "Sign in again to continue viewing templates." };
  return { title: "Template details unavailable", description: error?.message || "The template version could not be loaded." };
}

function TaskGroup({ eyebrow, title, description, tasks }) {
  if (!tasks.length) return null;
  return <section className="grid gap-3" data-testid={`task-group-${eyebrow}`}>
    <div className="flex items-end justify-between gap-4 px-1">
      <div><span className="text-xs font-medium text-slate-500">{eyebrow}</span><h3 className="mt-1 text-lg font-black tracking-[-.02em] text-slate-950">{title}</h3><p className="mt-1 text-xs font-medium text-slate-500">{description}</p></div>
      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-600">{tasks.length} loaded</span>
    </div>
    <TemplateTaskTable tasks={tasks}/>
    <div className="grid gap-3 lg:hidden">{tasks.map(task => <TemplateTaskCard key={task.id} task={task}/>)}</div>
  </section>;
}

function Tabs({ active, onChange, summary }) {
  const tabs = [
    { key: "tasks", label: "Tasks", count: summary.task_count, icon: ListChecks },
    { key: "dependencies", label: "Dependencies", count: summary.dependency_count, icon: GitBranch },
    { key: "gates", label: "Prerequisite approvals", count: summary.gate_count, icon: ShieldCheck },
  ];
  return <nav aria-label="Template detail tabs" className="flex gap-1 overflow-x-auto rounded-2xl border border-slate-200 bg-white p-1.5 shadow-sm">{tabs.map(tab => {
    const Icon = tab.icon;
    const selected = active === tab.key;
    return <button key={tab.key} type="button" aria-selected={selected} role="tab" onClick={() => onChange(tab.key)} className={`inline-flex min-h-11 shrink-0 items-center gap-2 rounded-xl px-3.5 text-sm font-black transition ${selected ? "bg-slate-950 text-white shadow-md" : "text-slate-500 hover:bg-slate-100 hover:text-slate-950"}`}><Icon size={16}/>{tab.label}<span className={`rounded-full px-2 py-0.5 text-[10px] ${selected ? "bg-white/15 text-white" : "bg-slate-100 text-slate-500"}`}>{tab.count}</span></button>;
  })}</nav>;
}


function GateSummary({ gates }) {
  const counts = useMemo(() => ({
    total: gates.length,
    exact: gates.filter(gate => gate.mapping_classification === "exact").length,
    broad: gates.filter(gate => gate.mapping_classification === "broad_text").length,
    configuration: gates.filter(gate => gate.requires_configuration).length,
    invalid: gates.filter(gate => gate.validation_state === "invalid").length,
  }), [gates]);
  const cards = [
    { label: "Approvals", value: counts.total, icon: ShieldCheck, tone: "blue" },
    { label: "Linked to tasks", value: counts.exact, icon: Link2, tone: "cyan" },
    { label: "Imported wording only", value: counts.broad, icon: Layers3, tone: "amber" },
    { label: "Need tasks linked", value: counts.configuration, icon: ShieldAlert, tone: "rose" },
    { label: "Validation issues", value: counts.invalid, icon: AlertTriangle, tone: "amber" },
  ];
  return <section aria-label="External gate summary" className="grid grid-cols-2 gap-3 lg:grid-cols-5">{cards.map(card => <SummaryMetric key={card.label} {...card}/>)}</section>;
}

function DependencySummary({ counts }) {
  const cards = [
    { label: "Links", value: counts.total, icon: GitBranch, tone: "blue" },
    { label: "Finish first", value: counts.finishToStart, icon: Link2, tone: "cyan" },
    { label: "Start together", value: counts.startToStart, icon: Layers3, tone: "emerald" },
    { label: "Enforced", value: counts.blocking, icon: ShieldCheck, tone: "rose" },
    { label: "Validation issues", value: counts.invalid, icon: ShieldAlert, tone: "amber" },
  ];
  return <section aria-label="Dependency summary" className="grid grid-cols-2 gap-3 lg:grid-cols-5">{cards.map(card => <SummaryMetric key={card.label} {...card}/>)}</section>;
}

export function TemplateDetails({ versionId, user, onBack, onClone, onArchive, onDeleteDraft, onOpenDraftEditor, activeTemplateTab, onTabChange, debounceMs = 350 }) {
  const [summary, setSummary] = useState(null);
  const [versionLoading, setVersionLoading] = useState(true);
  const [versionError, setVersionError] = useState(null);
  const [versionRetry, setVersionRetry] = useState(0);

  const [search, setSearch] = useState("");
  const [scheduleClassification, setScheduleClassification] = useState("");
  const [phase, setPhase] = useState("");
  const [category, setCategory] = useState("");
  const [applicability, setApplicability] = useState("");
  const [taskPage, setTaskPage] = useState(1);
  const [taskResult, setTaskResult] = useState(emptyTaskPage);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [taskError, setTaskError] = useState(null);
  const [taskRetry, setTaskRetry] = useState(0);

  const [dependencySearch, setDependencySearch] = useState("");
  const [dependencyType, setDependencyType] = useState("");
  const [dependencyBlocking, setDependencyBlocking] = useState("");
  const [dependencyValidation, setDependencyValidation] = useState("");
  const [dependencyResult, setDependencyResult] = useState(emptyDependencyPage);
  const [dependencyCounts, setDependencyCounts] = useState(emptyDependencyCounts);
  const [dependenciesLoading, setDependenciesLoading] = useState(false);
  const [dependencyError, setDependencyError] = useState(null);
  const [dependencyRetry, setDependencyRetry] = useState(0);

  const [gateSearch, setGateSearch] = useState("");
  const [gateMapping, setGateMapping] = useState("");
  const [gateConfiguration, setGateConfiguration] = useState("");
  const [gateParty, setGateParty] = useState("");
  const [gateValidation, setGateValidation] = useState("");
  const [gateResult, setGateResult] = useState(emptyGatePage);
  const [gatesLoading, setGatesLoading] = useState(false);
  const [gateError, setGateError] = useState(null);
  const [gateRetry, setGateRetry] = useState(0);

  const debouncedSearch = useDebouncedValue(search.trim(), debounceMs);
  const debouncedPhase = useDebouncedValue(phase.trim(), debounceMs);
  const debouncedCategory = useDebouncedValue(category.trim(), debounceMs);
  const debouncedDependencySearch = useDebouncedValue(dependencySearch.trim(), debounceMs);
  const debouncedGateSearch = useDebouncedValue(gateSearch.trim(), debounceMs);
  const debouncedGateParty = useDebouncedValue(gateParty.trim(), debounceMs);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setSummary(null);
    setVersionLoading(true);
    setVersionError(null);
    templatesApi.getVersion(versionId, { signal: controller.signal })
      .then(data => { if (active) setSummary(data); })
      .catch(error => { if (active && error.name !== "AbortError") setVersionError(error); })
      .finally(() => { if (active) setVersionLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [versionId, versionRetry]);

  useEffect(() => {
    if (activeTemplateTab !== "tasks" || versionLoading || versionError || !summary) return undefined;
    if (search.trim() !== debouncedSearch || phase.trim() !== debouncedPhase || category.trim() !== debouncedCategory) return undefined;
    const controller = new AbortController();
    let active = true;
    if (taskPage === 1) setTasksLoading(true);
    else setLoadingMore(true);
    setTaskError(null);
    const params = { page: taskPage, page_size: 20 };
    if (debouncedSearch) params.search = debouncedSearch;
    if (scheduleClassification) params.schedule_classification = scheduleClassification;
    if (debouncedPhase) params.phase = debouncedPhase;
    if (debouncedCategory) params.category = debouncedCategory;
    if (applicability) params.applicability = applicability;
    templatesApi.listTasks(versionId, params, { signal: controller.signal })
      .then(data => {
        if (!active) return;
        setTaskResult(previous => ({
          items: taskPage === 1 ? data.items : [...previous.items, ...data.items],
          pagination: data.pagination,
        }));
      })
      .catch(error => { if (active && error.name !== "AbortError") setTaskError(error); })
      .finally(() => { if (active) { setTasksLoading(false); setLoadingMore(false); } });
    return () => { active = false; controller.abort(); };
  }, [activeTemplateTab, applicability, debouncedCategory, debouncedPhase, debouncedSearch, scheduleClassification, taskPage, taskRetry, versionId, versionLoading, versionError, summary, search, phase, category]);

  const hasDependencyFilters = Boolean(dependencySearch.trim() || dependencyType || dependencyBlocking || dependencyValidation);

  useEffect(() => {
    if (activeTemplateTab !== "dependencies" || versionLoading || versionError || !summary) return undefined;
    if (dependencySearch.trim() !== debouncedDependencySearch) return undefined;
    const controller = new AbortController();
    let active = true;
    setDependenciesLoading(true);
    setDependencyError(null);
    const params = { page: 1, page_size: 100 };
    if (debouncedDependencySearch) params.search = debouncedDependencySearch;
    if (dependencyType) params.dependency_type = dependencyType;
    if (dependencyBlocking) params.blocking = dependencyBlocking === "true";
    if (dependencyValidation) params.validation_state = dependencyValidation;
    templatesApi.listDependencies(versionId, params, { signal: controller.signal })
      .then(data => {
        if (!active) return;
        setDependencyResult(data);
        setDependencyCounts({
          total: data.summary.total,
          finishToStart: data.summary.finish_to_start,
          startToStart: data.summary.start_to_start,
          blocking: data.summary.blocking,
          invalid: data.summary.validation_issues,
        });
      })
      .catch(error => { if (active && error.name !== "AbortError") setDependencyError(error); })
      .finally(() => { if (active) setDependenciesLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [activeTemplateTab, debouncedDependencySearch, dependencyBlocking, dependencyRetry, dependencyType, dependencyValidation, hasDependencyFilters, summary, versionError, versionId, versionLoading, dependencySearch]);


  const hasGateFilters = Boolean(gateSearch.trim() || gateMapping || gateConfiguration || gateParty.trim() || gateValidation);

  useEffect(() => {
    if (activeTemplateTab !== "gates" || versionLoading || versionError || !summary) return undefined;
    if (gateSearch.trim() !== debouncedGateSearch || gateParty.trim() !== debouncedGateParty) return undefined;
    const controller = new AbortController();
    let active = true;
    setGatesLoading(true);
    setGateError(null);
    const params = { page: 1, page_size: 100 };
    if (debouncedGateSearch) params.search = debouncedGateSearch;
    if (gateMapping) params.mapping_classification = gateMapping;
    if (gateConfiguration) params.requires_configuration = gateConfiguration === "true";
    if (debouncedGateParty) params.external_party = debouncedGateParty;
    if (gateValidation) params.validation_state = gateValidation;
    templatesApi.listGates(versionId, params, { signal: controller.signal })
      .then(data => { if (active) setGateResult(data); })
      .catch(error => { if (active && error.name !== "AbortError") setGateError(error); })
      .finally(() => { if (active) setGatesLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [activeTemplateTab, debouncedGateParty, debouncedGateSearch, gateConfiguration, gateMapping, gateRetry, gateValidation, summary, versionError, versionId, versionLoading, gateSearch, gateParty]);

  const hasTaskFilters = Boolean(search.trim() || scheduleClassification || phase.trim() || category.trim() || applicability);
  const preActivationTasks = useMemo(() => taskResult.items.filter(task => task.schedule_classification === "pre_activation"), [taskResult.items]);
  const executionTasks = useMemo(() => taskResult.items.filter(task => task.schedule_classification !== "pre_activation"), [taskResult.items]);
  const invalidCount = useMemo(() => taskResult.items.filter(task => task.validation_state === "invalid").length, [taskResult.items]);
  const invalidDependencyCount = useMemo(() => dependencyResult.items.filter(item => item.validation_state === "invalid").length, [dependencyResult.items]);
  const invalidGateCount = useMemo(() => gateResult.items.filter(item => item.validation_state === "invalid").length, [gateResult.items]);

  const isRefreshing = versionLoading || tasksLoading || dependenciesLoading || gatesLoading;
  function refreshAll() {
    setVersionRetry(value => value + 1);
    setTaskRetry(value => value + 1);
    setDependencyRetry(value => value + 1);
    setGateRetry(value => value + 1);
  }

  function resetTaskPage() { setTaskPage(1); }
  function clearTaskFilters() {
    setSearch("");
    setScheduleClassification("");
    setPhase("");
    setCategory("");
    setApplicability("");
    setTaskPage(1);
  }
  function clearDependencyFilters() {
    setDependencySearch("");
    setDependencyType("");
    setDependencyBlocking("");
    setDependencyValidation("");
  }
  function clearGateFilters() {
    setGateSearch("");
    setGateMapping("");
    setGateConfiguration("");
    setGateParty("");
    setGateValidation("");
  }
  function focusTask(taskCode) {
    setSearch(taskCode);
    setScheduleClassification("");
    setPhase("");
    setCategory("");
    setApplicability("");
    setTaskPage(1);
    onTabChange("tasks");
  }

  if (versionLoading) return <div className="grid min-h-80 place-items-center rounded-[24px] border border-slate-200 bg-white"><LoadingSpinner label="Loading template details..."/></div>;
  if (versionError || !summary) {
    const copy = accessError(versionError);
    return <div className="grid gap-4"><Button variant="ghost" className="w-fit" onClick={onBack}><ArrowLeft size={17}/> Back to Templates</Button><Alert tone="danger" className="items-center"><div><strong className="block">{copy.title}</strong><span className="mt-1 block font-medium">{copy.description}</span></div>{!versionError?.status || versionError.status >= 500 ? <Button size="sm" variant="secondary" onClick={() => setVersionRetry(value => value + 1)}><RefreshCw size={15}/> Retry</Button> : null}</Alert></div>;
  }

  return <div className="grid gap-5" data-testid="template-details">
    <header className="relative overflow-hidden rounded-[26px] bg-slate-950 p-5 text-white shadow-[0_24px_70px_rgba(15,23,42,.18)] sm:p-7">
      <div aria-hidden="true" className="absolute -right-20 -top-24 size-72 rounded-full border-[42px] border-blue-500/15"/>
      <div className="relative">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <Button variant="ghost" className="-ml-3 w-fit text-slate-300 hover:bg-white/10 hover:text-white" onClick={onBack}><ArrowLeft size={17}/> Back to Templates</Button>
          <div className="grid gap-2 sm:flex sm:flex-wrap sm:justify-end" aria-label="Template version actions">
            <RefreshButton className="border-white/15 bg-white/10 text-white hover:bg-white/15" loading={isRefreshing} onClick={refreshAll}/>
            {onClone && summary.status !== "archived" && <Button variant="secondary" className="border-white/15 bg-white/10 text-white hover:bg-white/15" onClick={() => onClone(summary)}><Copy size={17}/> Clone</Button>}
            {onArchive && summary.status === "published" && <Button className="bg-amber-500 text-slate-950 hover:bg-amber-400" onClick={() => onArchive(summary)}><Archive size={17}/> Archive Version</Button>}
            {summary.status === "draft" && onOpenDraftEditor && <Button className="bg-blue-600 hover:bg-blue-500" onClick={() => onOpenDraftEditor(summary)}><PencilLine size={17}/> Edit draft</Button>}
            {summary.status === "draft" && onDeleteDraft && <Button variant="secondary" className="border-rose-300/30 bg-rose-500/15 text-rose-100 hover:bg-rose-500/25" onClick={() => onDeleteDraft(summary)}><Trash2 size={17}/> Delete Draft</Button>}
          </div>
        </div>
        <div className="mt-5 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-blue-300">{summary.template_code}</span><Pill tone={statusTone(summary.status)}>{summary.status}</Pill>{summary.is_current_published && <span className="inline-flex items-center gap-1 text-xs font-black text-emerald-300"><CheckCircle2 size={15}/> Current published</span>}</div><h2 className="mt-3 max-w-3xl text-2xl font-normal tracking-[-.04em] sm:text-4xl">{summary.template_name}</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">{summary.template_description || "Governed project execution schedule."}</p></div>
          <div className="grid grid-cols-2 gap-2 text-xs font-bold sm:flex"><span className="rounded-xl border border-white/10 bg-white/[.07] px-3.5 py-3"><b className="block text-white">Version {summary.version_no}</b><small className="text-slate-400">Template version</small></span><span className="rounded-xl border border-white/10 bg-white/[.07] px-3.5 py-3"><b className="block text-white">{summary.duration_days} days</b><small className="text-slate-400">Planned duration</small></span><span className="col-span-2 rounded-xl border border-white/10 bg-white/[.07] px-3.5 py-3 sm:col-span-1"><b className="block text-white">{formatTemplateDate(summary.published_at)}</b><small className="text-slate-400">Published</small></span></div>
        </div>
      </div>
    </header>

    <section aria-label="Template summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4"><SummaryMetric icon={ListChecks} label="Template tasks" value={summary.task_count} tone="blue"/><SummaryMetric icon={GitBranch} label="Dependencies" value={summary.dependency_count} tone="cyan"/><SummaryMetric icon={ShieldCheck} label="Prerequisite approvals" value={summary.gate_count} tone="amber"/><SummaryMetric icon={Clock3} label="Schedule duration" value={`${summary.duration_days}d`} tone="emerald"/></section>

    <Tabs active={activeTemplateTab} onChange={onTabChange} summary={summary}/>

    {activeTemplateTab === "tasks" && <>
      <section className="rounded-[22px] border border-slate-200 bg-white p-3">
        <div className="grid gap-3 xl:grid-cols-[minmax(240px,1.4fr)_repeat(4,minmax(150px,.7fr))_auto]">
          <label className="relative"><Search aria-hidden="true" className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={17}/><Input aria-label="Search template tasks" value={search} onChange={event => { setSearch(event.target.value); resetTaskPage(); }} className="min-h-11 pl-10" placeholder="Search code, title or description"/></label>
          <Select aria-label="Filter schedule classification" value={scheduleClassification} onChange={event => { setScheduleClassification(event.target.value); resetTaskPage(); }}><option value="">All schedules</option><option value="pre_activation">Pre-Activation</option><option value="execution">Execution</option></Select>
          <Input aria-label="Filter task phase" value={phase} onChange={event => { setPhase(event.target.value); resetTaskPage(); }} placeholder="Phase"/>
          <Input aria-label="Filter task category" value={category} onChange={event => { setCategory(event.target.value); resetTaskPage(); }} placeholder="Category"/>
          <Select aria-label="Filter applicability" value={applicability} onChange={event => { setApplicability(event.target.value); resetTaskPage(); }}><option value="">All applicability</option><option value="mandatory">Mandatory</option><option value="conditional">Conditional</option></Select>
          {hasTaskFilters && <Button variant="ghost" onClick={clearTaskFilters}><FilterX size={16}/> Clear</Button>}
        </div>
      </section>

      {invalidCount > 0 && <Alert tone="warning"><div><strong>{invalidCount} loaded task{invalidCount === 1 ? "" : "s"} require validation</strong><span className="mt-1 block font-medium">Source records are reported exactly as stored and were not repaired.</span></div></Alert>}

      {tasksLoading ? <div className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"><LoadingSpinner label="Loading template tasks..."/></div> : taskError ? <Alert tone="danger" className="items-center"><div><strong className="block">{accessError(taskError).title}</strong><span className="mt-1 block font-medium">{accessError(taskError).description}</span></div><Button size="sm" variant="secondary" onClick={() => setTaskRetry(value => value + 1)}><RefreshCw size={15}/> Retry</Button></Alert> : !taskResult.items.length ? <EmptyState className="min-h-64 bg-white" icon={hasTaskFilters ? <Search size={21}/> : <DatabaseZap size={21}/>} title={hasTaskFilters ? "No tasks match these filters" : "No tasks stored for this version"} description={hasTaskFilters ? "Clear one or more filters and try again." : "Tasks will appear after this template version receives governed task records."} action={hasTaskFilters ? <Button variant="secondary" onClick={clearTaskFilters}><FilterX size={16}/> Clear filters</Button> : null}/> : <div className="grid gap-7">
        <TaskGroup eyebrow="Before the project starts" title="Pre-Activation" description="Prerequisites completed before the 45-day execution clock begins." tasks={preActivationTasks}/>
        <TaskGroup eyebrow="Project schedule" title="Day 1-45 Execution" description="Tasks in schedule order." tasks={executionTasks}/>
      </div>}

      {!tasksLoading && !taskError && taskResult.items.length > 0 && <footer className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-3 sm:flex-row sm:items-center sm:justify-between"><span className="px-2 text-xs font-bold text-slate-500">Showing {taskResult.items.length} of {taskResult.pagination.total} tasks</span>{taskResult.pagination.page < taskResult.pagination.total_pages && <Button variant="secondary" loading={loadingMore} onClick={() => setTaskPage(value => value + 1)}><Layers3 size={16}/> Load more tasks</Button>}</footer>}
    </>}

    {activeTemplateTab === "dependencies" && <>
      <DependencySummary counts={dependencyCounts}/>
      <section className="rounded-[22px] border border-slate-200 bg-white p-3">
        <div className="grid gap-3 xl:grid-cols-[minmax(260px,1.5fr)_repeat(3,minmax(170px,.7fr))_auto]">
          <label className="relative"><Search aria-hidden="true" className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={17}/><Input aria-label="Search template dependencies" value={dependencySearch} onChange={event => setDependencySearch(event.target.value)} className="min-h-11 pl-10" placeholder="Search tasks"/></label>
          <Select aria-label="Filter dependency type" value={dependencyType} onChange={event => setDependencyType(event.target.value)}><option value="">All link types</option><option value="finish_to_start">Finish first</option><option value="start_to_start">Start together</option></Select>
          <Select aria-label="Filter dependency blocking" value={dependencyBlocking} onChange={event => setDependencyBlocking(event.target.value)}><option value="">Enforced and advisory</option><option value="true">Enforced</option><option value="false">Advisory only</option></Select>
          <Select aria-label="Filter dependency validation" value={dependencyValidation} onChange={event => setDependencyValidation(event.target.value)}><option value="">All validation states</option><option value="valid">Valid</option><option value="invalid">Issues only</option></Select>
          {hasDependencyFilters && <Button variant="ghost" onClick={clearDependencyFilters}><FilterX size={16}/> Clear</Button>}
        </div>
      </section>

      {invalidDependencyCount > 0 && <Alert tone="warning"><AlertTriangle className="shrink-0" size={19}/><div><strong>{invalidDependencyCount} relationship{invalidDependencyCount === 1 ? "" : "s"} require review</strong><span className="mt-1 block font-medium">Warnings reflect stored source data. Shown exactly as saved.</span></div></Alert>}

      {dependenciesLoading ? <div className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"><LoadingSpinner label="Loading template dependencies..."/></div> : dependencyError ? <Alert tone="danger" className="items-center"><div><strong className="block">{accessError(dependencyError).title}</strong><span className="mt-1 block font-medium">{accessError(dependencyError).description}</span></div><Button size="sm" variant="secondary" onClick={() => setDependencyRetry(value => value + 1)}><RefreshCw size={15}/> Retry</Button></Alert> : !dependencyResult.items.length ? <EmptyState className="min-h-64 bg-white" icon={hasDependencyFilters ? <Search size={21}/> : <GitBranch size={21}/>} title={hasDependencyFilters ? "No dependencies match these filters" : "No dependencies stored for this version"} description={hasDependencyFilters ? "Clear one or more filters and try again." : "Relationships will appear after this template version receives dependency records."} action={hasDependencyFilters ? <Button variant="secondary" onClick={clearDependencyFilters}><FilterX size={16}/> Clear filters</Button> : null}/> : <section className="grid gap-3">
        <div className="flex flex-col gap-1 px-1 sm:flex-row sm:items-end sm:justify-between"><div><span className="text-xs font-medium text-cyan-700">Read-only</span><h3 className="mt-1 text-lg font-black tracking-[-.02em] text-slate-950">Task relationships</h3><p className="mt-1 text-xs font-medium text-slate-500">Select a task code to inspect that task in context.</p></div><span className="text-xs font-bold text-slate-500">Showing {dependencyResult.items.length} of {dependencyResult.pagination.total}</span></div>
        <TemplateDependencyTable dependencies={dependencyResult.items} onFocusTask={focusTask}/>
        <div className="grid gap-3 lg:hidden">{dependencyResult.items.map(dependency => <TemplateDependencyCard key={dependency.id} dependency={dependency} onFocusTask={focusTask}/>)}</div>
      </section>}
    </>}

    {activeTemplateTab === "gates" && <>
      <GateSummary gates={gateResult.items}/>
      <section className="rounded-[22px] border border-slate-200 bg-white p-3">
        <div className="grid gap-3 xl:grid-cols-[minmax(240px,1.4fr)_repeat(4,minmax(150px,.7fr))_auto]">
          <label className="relative"><Search aria-hidden="true" className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={17}/><Input aria-label="Search external gates" value={gateSearch} onChange={event => setGateSearch(event.target.value)} className="min-h-11 pl-10" placeholder="Search code, approval or party"/></label>
          <Select aria-label="Filter gate mapping" value={gateMapping} onChange={event => setGateMapping(event.target.value)}><option value="">All</option><option value="exact">Linked to tasks</option><option value="broad_text">Imported wording</option><option value="unmapped">Not linked</option></Select>
          <Select aria-label="Filter gate configuration" value={gateConfiguration} onChange={event => setGateConfiguration(event.target.value)}><option value="">Linked or not</option><option value="true">Needs tasks linked</option><option value="false">Linked</option></Select>
          <Input aria-label="Filter external party" value={gateParty} onChange={event => setGateParty(event.target.value)} placeholder="Who approves"/>
          <Select aria-label="Filter gate validation" value={gateValidation} onChange={event => setGateValidation(event.target.value)}><option value="">All validation states</option><option value="valid">Valid</option><option value="invalid">Issues only</option></Select>
          {hasGateFilters && <Button variant="ghost" onClick={clearGateFilters}><FilterX size={16}/> Clear</Button>}
        </div>
      </section>

      {invalidGateCount > 0 && <Alert tone="warning"><AlertTriangle className="shrink-0" size={19}/><div><strong>{invalidGateCount} gate{invalidGateCount === 1 ? "" : "s"} require review</strong><span className="mt-1 block font-medium">Shown exactly as saved. Nothing has been changed automatically.</span></div></Alert>}

      {gatesLoading ? <div className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"><LoadingSpinner label="Loading external gates..."/></div> : gateError ? <Alert tone="danger" className="items-center"><div><strong className="block">{accessError(gateError).title}</strong><span className="mt-1 block font-medium">{accessError(gateError).description}</span></div><Button size="sm" variant="secondary" onClick={() => setGateRetry(value => value + 1)}><RefreshCw size={15}/> Retry</Button></Alert> : !gateResult.items.length ? <EmptyState className="min-h-64 bg-white" icon={hasGateFilters ? <Search size={21}/> : <ShieldCheck size={21}/>} title={hasGateFilters ? "No external gates match these filters" : "No external gates stored for this version"} description={hasGateFilters ? "Clear one or more filters and try again." : "Gate records will appear when this version has external approvals."} action={hasGateFilters ? <Button variant="secondary" onClick={clearGateFilters}><FilterX size={16}/> Clear filters</Button> : null}/> : <section className="grid gap-3">
        <div className="flex flex-col gap-1 px-1 sm:flex-row sm:items-end sm:justify-between"><div><span className="text-xs font-medium text-amber-700">Read-only</span><h3 className="mt-1 text-lg font-black tracking-[-.02em] text-slate-950">Prerequisite approvals</h3><p className="mt-1 text-xs font-medium text-slate-500">Each approval lists the tasks it is required before.</p></div><span className="text-xs font-bold text-slate-500">Showing {gateResult.items.length} of {gateResult.pagination.total}</span></div>
        <TemplateGateTable gates={gateResult.items} onFocusTask={focusTask}/>
        <div className="grid gap-3 lg:hidden">{gateResult.items.map(gate => <TemplateGateCard key={gate.id} gate={gate} onFocusTask={focusTask}/>)}</div>
      </section>}
    </>}

    <footer className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-xs font-semibold text-slate-500"><span className="inline-flex items-center gap-2"><BookOpenCheck size={16} className="text-blue-700"/> {summary.status === "archived" ? "Archived version: kept as read-only history, not offered for new projects" : summary.status === "published" ? "Published version is view-only" : "Draft details remain unchanged until edited"}</span><span className="inline-flex items-center gap-2"><CalendarDays size={16} className="text-emerald-700"/> Accessed as {user.role.replaceAll("_", " ")}</span></footer>
  </div>;
}