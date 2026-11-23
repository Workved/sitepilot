import { BookOpenCheck, ChevronLeft, ChevronRight, DatabaseZap, FilePlus2, FilterX, Layers3, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { templatesApi } from "../../api/templatesApi";
import { Alert, Button, EmptyState, Input, LoadingSpinner, RefreshButton, Select } from "../../components/ui";
import { TemplateAuthoringModal } from "./components/TemplateAuthoringModal";
import { TemplateArchiveVersionModal } from "./components/TemplateArchiveVersionModal";
import { TemplateDeleteDraftModal } from "./components/TemplateDeleteDraftModal";
import { TemplateCard } from "./components/TemplateCard";
import { TemplateDraftEditorEntry } from "./components/TemplateDraftEditorEntry";
import { TemplateDetails } from "./TemplateDetails";
import { TemplateTable } from "./components/TemplateTable";
import { useDebouncedValue } from "./useDebouncedValue";
import { ORG_ADMIN_ROLES } from "../../utils/constants";

const emptyPage = { items: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 } };

function LoadingState() {
  return <div className="grid min-h-64 place-items-center rounded-[22px] border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading approved templates..."/></div>;
}

export function TemplatesPage({ user, debounceMs = 350 }) {
  const canManageTemplates = ORG_ADMIN_ROLES.includes(user.role);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(emptyPage);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);
  const [selectedTemplateVersionId, setSelectedTemplateVersionId] = useState(null);
  const [templateView, setTemplateView] = useState("list");
  const [activeTemplateTab, setActiveTemplateTab] = useState("tasks");
  const [authoring, setAuthoring] = useState(null);
  const [archiveVersion, setArchiveVersion] = useState(null);
  const [deleteDraftVersion, setDeleteDraftVersion] = useState(null);
  const [draftEditorSummary, setDraftEditorSummary] = useState(null);
  const debouncedSearch = useDebouncedValue(search.trim(), debounceMs);

  useEffect(() => {
    if (canManageTemplates || templateView !== "editor") return;
    setTemplateView("list");
    setSelectedTemplateVersionId(null);
    setDraftEditorSummary(null);
    setActiveTemplateTab("tasks");
  }, [canManageTemplates, templateView]);

  useEffect(() => {
    if (search.trim() !== debouncedSearch) return undefined;
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    const params = { page, page_size: 20 };
    if (debouncedSearch) params.search = debouncedSearch;
    if (canManageTemplates && status) params.status = status;
    templatesApi.list(params, { signal: controller.signal })
      .then(data => { if (active) setResult(data); })
      .catch(requestError => {
        if (active && requestError.name !== "AbortError") setError(requestError.message || "Templates could not be loaded.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [debouncedSearch, canManageTemplates, page, retryKey, status]);

  const hasFilters = Boolean(search.trim() || (canManageTemplates && status));
  const publishedOnPage = useMemo(() => result.items.filter(item => item.status === "published").length, [result.items]);
  const draftOnPage = useMemo(() => result.items.filter(item => item.status === "draft").length, [result.items]);

  function selectVersion(versionId) {
    setSelectedTemplateVersionId(versionId);
    setTemplateView("detail");
  }

  function clearFilters() {
    setSearch("");
    setStatus("");
    setPage(1);
  }

  function openCreatedDraft(response) {
    if (!response?.version_id || response.status !== "draft") {
      throw new Error("The new draft response was incomplete. The template list has not been left.");
    }
    setAuthoring(null);
    // Go straight to editing. The editor loads the full draft itself, and
    // its Back button still leads to this draft's details.
    setDraftEditorSummary(response);
    setSelectedTemplateVersionId(response.version_id);
    setActiveTemplateTab("tasks");
    setTemplateView("editor");
    setRetryKey(value => value + 1);
  }

  function backToList() {
    setTemplateView("list");
    setSelectedTemplateVersionId(null);
    setDraftEditorSummary(null);
    setActiveTemplateTab("tasks");
  }

  if (templateView === "editor" && draftEditorSummary) {
    return <section className="grid gap-5" data-template-view={templateView} data-selected-version-id={selectedTemplateVersionId}>
      <TemplateDraftEditorEntry summary={draftEditorSummary} user={user} onBack={() => setTemplateView("detail")} onPublished={response => { setDraftEditorSummary(null); setSelectedTemplateVersionId(response.version_id); setActiveTemplateTab("tasks"); setTemplateView("detail"); setRetryKey(value => value + 1); }}/>
    </section>;
  }

  if (templateView === "detail" && selectedTemplateVersionId) {
    return <section className="grid gap-5" data-template-view={templateView} data-selected-version-id={selectedTemplateVersionId}>
      <TemplateDetails
        versionId={selectedTemplateVersionId}
        user={user}
        debounceMs={debounceMs}
        activeTemplateTab={activeTemplateTab}
        onTabChange={setActiveTemplateTab}
        onBack={backToList}
        onClone={canManageTemplates ? source => setAuthoring({ mode: "clone", source }) : undefined}
        onArchive={canManageTemplates ? source => setArchiveVersion(source) : undefined}
        onDeleteDraft={canManageTemplates ? source => setDeleteDraftVersion(source) : undefined}
        onOpenDraftEditor={canManageTemplates ? source => {
          setDraftEditorSummary(source);
          setTemplateView("editor");
        } : undefined}
      />
      {authoring && <TemplateAuthoringModal mode={authoring.mode} source={authoring.source} onClose={() => setAuthoring(null)} onSuccess={openCreatedDraft}/>}
      {archiveVersion && <TemplateArchiveVersionModal version={archiveVersion} onClose={() => setArchiveVersion(null)} onSuccess={() => { setArchiveVersion(null); backToList(); setRetryKey(value => value + 1); }}/>}
      {deleteDraftVersion && <TemplateDeleteDraftModal version={deleteDraftVersion} onClose={() => setDeleteDraftVersion(null)} onSuccess={() => { setDeleteDraftVersion(null); backToList(); setRetryKey(value => value + 1); }}/>}
    </section>;
  }

  return <section className="grid gap-5" data-template-view={templateView} data-selected-version-id={selectedTemplateVersionId || ""}>
    <header className="relative overflow-hidden rounded-[26px] border border-slate-200/80 bg-slate-950 p-5 text-white shadow-[0_24px_70px_rgba(15,23,42,.16)] sm:p-7">
      <div aria-hidden="true" className="absolute -right-14 -top-20 size-64 rounded-full border-[36px] border-blue-500/15"/>
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between"><div><div className="flex items-center gap-2 text-xs font-medium text-blue-300"><BookOpenCheck size={15}/> Approved delivery system</div><h2 className="mt-3 max-w-2xl text-2xl font-normal tracking-[-.04em] sm:text-3xl">Template library</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">{canManageTemplates ? "Clone a template to make changes, then review and publish it." : "View the schedules new projects are created from. This view is read-only."}</p>{canManageTemplates && <Button className="mt-4 w-full bg-blue-600 hover:bg-blue-500 sm:w-fit" onClick={() => setAuthoring({ mode: "create" })}><FilePlus2 size={17}/> Create Template</Button>}</div><div className="grid grid-cols-2 gap-2 sm:flex"><span className="rounded-xl border border-white/10 bg-white/[.07] px-4 py-3"><b className="block text-xl font-black">{result.pagination.total}</b><small className="text-slate-300">Visible versions</small></span><span className="rounded-xl border border-white/10 bg-white/[.07] px-4 py-3"><b className="block text-xl font-black">{publishedOnPage}</b><small className="text-slate-300">Published here</small></span>{canManageTemplates && <span className="col-span-2 rounded-xl border border-amber-300/20 bg-amber-300/10 px-4 py-3 sm:col-span-1"><b className="block text-xl font-black text-amber-200">{draftOnPage}</b><small className="text-amber-100/80">Drafts here</small></span>}</div></div>
    </header>

    <div className="rounded-[22px] border border-slate-200 bg-white p-3"><div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <label className="relative min-w-0 flex-1"><Search aria-hidden="true" className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18}/><Input aria-label="Search templates" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} className="min-h-12 pl-11" placeholder="Search template name, code or version"/></label>
      {canManageTemplates && <Select aria-label="Filter template status" value={status} onChange={event => { setStatus(event.target.value); setPage(1); }} className="min-h-12 sm:max-w-48"><option value="">Published &amp; draft</option><option value="published">Published</option><option value="draft">Draft</option><option value="archived">Archived (history)</option></Select>}
      {hasFilters && <Button variant="ghost" className="min-h-12" onClick={clearFilters}><FilterX size={17}/> Clear filters</Button>}
      <RefreshButton className="min-h-12" loading={loading} onClick={() => setRetryKey(value => value + 1)}/>
    </div></div>

    {loading ? <LoadingState/> : error ? <Alert tone="danger" className="items-center"><div><strong className="block">Template library unavailable</strong><span className="mt-1 block font-medium">{error}</span></div><Button size="sm" variant="secondary" onClick={() => setRetryKey(value => value + 1)}><RefreshCw size={15}/> Retry</Button></Alert> : !result.items.length ? <EmptyState className="min-h-64 bg-white" icon={hasFilters ? <Search size={21}/> : <DatabaseZap size={21}/>} title={hasFilters ? "No templates match these filters" : "No template versions available"} description={hasFilters ? "Clear the filters or try a broader name, code or version." : "Published template versions will appear here after the approved import is completed."} action={hasFilters ? <Button variant="secondary" onClick={clearFilters}><FilterX size={16}/> Clear filters</Button> : null}/> : <>
      <TemplateTable items={result.items} selectedTemplateVersionId={selectedTemplateVersionId} onSelect={selectVersion} onArchive={canManageTemplates ? setArchiveVersion : undefined} onDeleteDraft={canManageTemplates ? setDeleteDraftVersion : undefined}/>
      <div className="grid gap-3 lg:hidden">{result.items.map(item => <TemplateCard key={item.version_id} item={item} selected={selectedTemplateVersionId === item.version_id} onSelect={selectVersion}/>)}</div>
    </>}

    {!loading && !error && result.pagination.total_pages > 1 && <nav aria-label="Template pagination" className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-3 sm:flex-row sm:items-center sm:justify-between"><span className="px-2 text-xs font-bold text-slate-500">Page {result.pagination.page} of {result.pagination.total_pages} / {result.pagination.total} versions</span><div className="grid grid-cols-2 gap-2"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(value => Math.max(1, value - 1))}><ChevronLeft size={16}/> Previous</Button><Button variant="secondary" disabled={page >= result.pagination.total_pages} onClick={() => setPage(value => value + 1)}>Next <ChevronRight size={16}/></Button></div></nav>}

    <footer className="grid gap-3 rounded-2xl border border-slate-200/80 bg-slate-50 p-4 text-xs text-slate-500 sm:grid-cols-2"><span className="flex items-center gap-2"><ShieldCheck size={16} className="text-emerald-600"/> Visibility follows your assigned SiteOps role.</span><span className="flex items-center gap-2 sm:justify-end"><Layers3 size={16} className="text-blue-600"/> Open a version to see its tasks and prerequisite approvals.</span></footer>
    {authoring && <TemplateAuthoringModal mode={authoring.mode} source={authoring.source} onClose={() => setAuthoring(null)} onSuccess={openCreatedDraft}/>}
    {archiveVersion && <TemplateArchiveVersionModal version={archiveVersion} onClose={() => setArchiveVersion(null)} onSuccess={() => { setArchiveVersion(null); setRetryKey(value => value + 1); }}/>}
    {deleteDraftVersion && <TemplateDeleteDraftModal version={deleteDraftVersion} onClose={() => setDeleteDraftVersion(null)} onSuccess={() => { setDeleteDraftVersion(null); setRetryKey(value => value + 1); }}/>}
  </section>;
}