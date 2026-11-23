import { ChevronLeft, ChevronRight, DatabaseZap, FilePlus2, FilterX, Layers3, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
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
  return <div className="grid min-h-64 place-items-center rounded-[20px] border border-line bg-white p-8"><LoadingSpinner label="Loading approved templates..."/></div>;
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
    <header className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
      <div className="min-w-0">
        <h2 className="text-[17px] font-medium text-slate-950">Template library</h2>
        <p className="mt-0.5 max-w-2xl text-sm leading-6 text-slate-500">{canManageTemplates ? "The schedules new projects are created from. Clone a template to make changes, then review and publish it." : "View the schedules new projects are created from. This view is read-only."}</p>
        {!loading && !error && <p className="mt-2 flex flex-wrap gap-2 text-xs">
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-700">{result.pagination.total} {result.pagination.total === 1 ? "version" : "versions"}</span>
        </p>}
      </div>
      {canManageTemplates && <Button onClick={() => setAuthoring({ mode: "create" })}><FilePlus2 size={17}/> Create Template</Button>}
    </header>

    <div className="rounded-[20px] border border-line bg-white p-3"><div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <label className="relative min-w-0 flex-1"><Search aria-hidden="true" className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" size={17}/><Input aria-label="Search templates" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} className="bg-slate-50 pl-10" placeholder="Search template name, code or version"/></label>
      {canManageTemplates && <Select aria-label="Filter template status" value={status} onChange={event => { setStatus(event.target.value); setPage(1); }} className="sm:max-w-48"><option value="">Published &amp; draft</option><option value="published">Published</option><option value="draft">Draft</option><option value="archived">Archived (history)</option></Select>}
      {hasFilters && <Button variant="ghost" onClick={clearFilters}><FilterX size={17}/> Clear filters</Button>}
      <RefreshButton loading={loading} onClick={() => setRetryKey(value => value + 1)}/>
    </div></div>

    {loading ? <LoadingState/> : error ? <Alert tone="danger" className="items-center"><div><strong className="block">Template library unavailable</strong><span className="mt-1 block font-medium">{error}</span></div><Button size="sm" variant="secondary" onClick={() => setRetryKey(value => value + 1)}><RefreshCw size={15}/> Retry</Button></Alert> : !result.items.length ? <EmptyState className="min-h-64 bg-white" icon={hasFilters ? <Search size={21}/> : <DatabaseZap size={21}/>} title={hasFilters ? "No templates match these filters" : "No template versions available"} description={hasFilters ? "Clear the filters or try a broader name, code or version." : "Published template versions will appear here after the approved import is completed."} action={hasFilters ? <Button variant="secondary" onClick={clearFilters}><FilterX size={16}/> Clear filters</Button> : null}/> : <>
      <TemplateTable items={result.items} selectedTemplateVersionId={selectedTemplateVersionId} onSelect={selectVersion} onArchive={canManageTemplates ? setArchiveVersion : undefined} onDeleteDraft={canManageTemplates ? setDeleteDraftVersion : undefined}/>
      <div className="grid gap-3 lg:hidden">{result.items.map(item => <TemplateCard key={item.version_id} item={item} selected={selectedTemplateVersionId === item.version_id} onSelect={selectVersion}/>)}</div>
    </>}

    {!loading && !error && result.pagination.total_pages > 1 && <nav aria-label="Template pagination" className="flex flex-col gap-3 rounded-[20px] border border-line bg-white p-3 sm:flex-row sm:items-center sm:justify-between"><span className="px-2 text-xs text-slate-500">Page {result.pagination.page} of {result.pagination.total_pages} / {result.pagination.total} versions</span><div className="grid grid-cols-2 gap-2"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(value => Math.max(1, value - 1))}><ChevronLeft size={16}/> Previous</Button><Button variant="secondary" disabled={page >= result.pagination.total_pages} onClick={() => setPage(value => value + 1)}>Next <ChevronRight size={16}/></Button></div></nav>}

    <p className="flex flex-wrap items-center gap-x-5 gap-y-1 px-1 text-xs text-slate-500"><span className="flex items-center gap-1.5"><ShieldCheck size={14}/> Visibility follows your assigned SiteOps role.</span><span className="flex items-center gap-1.5"><Layers3 size={14}/> Open a version to see its tasks and prerequisite approvals.</span></p>
    {authoring && <TemplateAuthoringModal mode={authoring.mode} source={authoring.source} onClose={() => setAuthoring(null)} onSuccess={openCreatedDraft}/>}
    {archiveVersion && <TemplateArchiveVersionModal version={archiveVersion} onClose={() => setArchiveVersion(null)} onSuccess={() => { setArchiveVersion(null); setRetryKey(value => value + 1); }}/>}
    {deleteDraftVersion && <TemplateDeleteDraftModal version={deleteDraftVersion} onClose={() => setDeleteDraftVersion(null)} onSuccess={() => { setDeleteDraftVersion(null); setRetryKey(value => value + 1); }}/>}
  </section>;
}