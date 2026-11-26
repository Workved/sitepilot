import { BookOpenCheck, FolderKanban, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { projectsApi } from "../../api/projectsApi";
import { Button, EmptyState, LoadingSpinner } from "../../components/ui";
import { useRoute } from "../../lib/route";
import { AttentionMenu } from "./components/AttentionMenu";
import { ProjectFormModal } from "./components/ProjectFormModal";
import { filterProjects, ProjectListPane } from "./components/ProjectListPane";
import { ProjectWorkspace } from "./components/ProjectWorkspace";

const CAN_CREATE = ["admin", "super_admin"];

function readApiError(error) {
  const detail = error?.details?.detail;
  if (Array.isArray(detail)) {
    return detail.map(item => {
      const location = Array.isArray(item.loc) ? item.loc.filter(part => part !== "body").join(".") : "";
      return `${location ? `${location}: ` : ""}${item.msg || "Invalid value"}`;
    }).join(" ");
  }
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return error?.message || "Unable to save project.";
}

export function ProjectsPage({ user, action, onTabChange }) {
  const [projects, setProjects] = useState([]);
  const [references, setReferences] = useState({ project_managers: [], supervisors: [], internal_employees: [] });
  const [publishedTemplates, setPublishedTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templatesError, setTemplatesError] = useState("");
  // Additive read models. Null means "not available", which is different
  // from an empty list and is what every consumer checks before rendering
  // progress, phases or the attention counter.
  const [summaries, setSummaries] = useState(null);
  const [attention, setAttention] = useState(null);

  const [route, setRoute] = useRoute();
  const [filter, setFilter] = useState("active");
  const [sort, setSort] = useState("attention");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formProject, setFormProject] = useState(undefined);
  const [formError, setFormError] = useState("");
  const initialLoadStarted = useRef(false);
  // `projects` state is not readable synchronously right after load() in the
  // same tick, so keep the last fetched list here for post-save lookups.
  const loadedProjects = useRef([]);
  // There is no page-level Refresh: the shell's refresh reloads the
  // workspace, which remounts this page and every pane inside it.

  async function loadPublishedTemplates() {
    if (!CAN_CREATE.includes(user.role)) {
      setPublishedTemplates([]);
      return;
    }
    setTemplatesLoading(true);
    setTemplatesError("");
    try {
      const response = await projectsApi.publishedTemplates();
      const items = Array.isArray(response) ? response : (response?.items || []);
      setPublishedTemplates(items.filter(item => item.status === "published"));
    } catch (error) {
      setPublishedTemplates([]);
      setTemplatesError(error?.message || "Unable to load published templates. Refresh and try again.");
    } finally {
      setTemplatesLoading(false);
    }
  }

  async function load() {
    setLoading(true);
    try {
      const [items, refs] = await Promise.all([projectsApi.list(), projectsApi.references()]);
      setProjects(items);
      loadedProjects.current = items;
      setReferences({
        ...refs,
        project_managers: (refs.project_managers || []).filter(item => item.availability !== "unavailable"),
        supervisors: (refs.supervisors || []).filter(item => item.availability !== "unavailable"),
      });
      await loadPublishedTemplates();
    } catch (error) {
      await action(() => Promise.reject(error), "", { refresh: false });
    } finally {
      setLoading(false);
    }
    return loadedProjects.current;
  }

  // Deliberately not awaited alongside the required calls: neither endpoint
  // exists yet, and a 404 here must never stop the project list rendering.
  async function loadReadModels() {
    const [summaryRows, attentionRows] = await Promise.all([
      projectsApi.summaries().catch(() => null),
      projectsApi.attention().catch(() => null),
    ]);
    setSummaries(Array.isArray(summaryRows)
      ? Object.fromEntries(summaryRows.map(row => [row.project_id, row]))
      : null);
    setAttention(Array.isArray(attentionRows) ? attentionRows : null);
  }

  useEffect(() => {
    if (initialLoadStarted.current) return;
    initialLoadStarted.current = true;
    load();
    loadReadModels();
  }, []);

  const filtered = useMemo(() => filterProjects(projects, filter), [projects, filter]);
  const selected = useMemo(
    () => projects.find(item => item.code === route.project) || null,
    [projects, route.project],
  );

  // Open straight into a project rather than a dead "nothing selected"
  // pane. Replace, not push, so Back does not walk through auto-selections.
  // Must stick to `filtered[0]` only - reaching into the full `projects`
  // array for "any non-archived project" when the current filter is empty
  // used to fight the reconciliation effect below: that effect clears a
  // selection that falls outside the filter, this one immediately put it
  // right back (since it was the only non-archived project around), and
  // the two looped forever - the exact "buffering never settles" bug on
  // any empty tab (Active/On hold/Completed) while a Draft project
  // existed. An empty filter now genuinely shows the empty state.
  useEffect(() => {
    if (loading || selected) return;
    const fallback = filtered[0];
    if (fallback) setRoute({ project: fallback.code, pane: route.pane || "overview" }, { replace: true });
  }, [loading, selected, filtered]);

  // `selected` is looked up against the full `projects` array, ignoring
  // `filter` entirely - so it can point at a project the left pane (which
  // DOES respect `filter`) no longer lists at all: switching the filter
  // chip away from a project's current status, a lifecycle transition
  // (activate/hold/complete/archive) moving it out of the filter you're
  // still on, a manual refresh, or even a fresh page load landing on a
  // route left over from before. Any of those needs the same recovery:
  // clear the selection so the fallback effect above picks the next
  // visible project (or the true empty state) instead of leaving a ghost
  // detail pane for a project the list says doesn't exist.
  //
  // Except on arrival: a link (a snag, a vendor's project, a bookmark) to,
  // say, a completed project must open it, so the first time the list loads
  // the filter moves to that project's status instead of dropping it.
  const arrivedViaLink = useRef(true);
  // The one-time "arrived via a link" allowance is only spent once projects
  // have actually loaded, so a render where loading has ended but the list
  // is still empty can't use it up before the linked project is known.
  useEffect(() => {
    if (loading) return;
    if (!selected) { if (projects.length) arrivedViaLink.current = false; return; }
    if (filtered.some(item => item.id === selected.id)) { arrivedViaLink.current = false; return; }
    if (arrivedViaLink.current) { arrivedViaLink.current = false; setFilter(selected.status); return; }
    setRoute({ project: "", pane: "" }, { replace: true });
  }, [loading, selected, filtered, projects.length]);

  const attentionByProject = useMemo(() => {
    if (!attention) return {};
    return attention.reduce((totals, item) => ({ ...totals, [item.project_id]: (totals[item.project_id] || 0) + 1 }), {});
  }, [attention]);

  const selectedAttention = useMemo(
    () => (attention && selected ? attention.filter(item => item.project_id === selected.id) : []),
    [attention, selected],
  );

  function openProject(project) {
    setRoute({ project: project.code, pane: "overview" });
  }

  function openFromAttention(item) {
    const project = projects.find(candidate => candidate.id === item.project_id);
    if (!project) return;
    // Jumping to a project outside the current filter would select a row
    // that is not on screen - widen the filter so the selection stays visible.
    if (!filterProjects(projects, filter).some(candidate => candidate.id === project.id)) setFilter("all");
    setRoute({ project: project.code, pane: item.pane || "overview" });
  }

  async function refreshAll() {
    const items = await load();
    await loadReadModels();
    return items;
  }

  async function saveProject(payload) {
    if (saving) return;
    setSaving(true);
    setFormError("");
    const editing = Boolean(formProject);
    try {
      if (editing) {
        await projectsApi.update(formProject.id, payload);
        setFormProject(undefined);
        await refreshAll();
        setRoute({ project: formProject.code, pane: route.pane || "overview" });
      } else {
        const created = await projectsApi.create(payload);
        setFormProject(undefined);
        const items = await refreshAll();
        // POST returns the full project JSON, but resolve the code off the
        // refreshed list when possible so this does not silently stop
        // selecting the new project if that response shape ever narrows.
        const code = created?.code || items?.find(item => item.id === (created?.id || created?.project_id))?.code;
        if (code) setRoute({ project: code, pane: "overview" });
      }
    } catch (error) {
      setFormError(readApiError(error));
    } finally {
      setSaving(false);
    }
  }

  const canCreate = CAN_CREATE.includes(user.role);
  const hasAttention = Boolean(attention?.length);
  const listActions = (canCreate || hasAttention) ? <>
    <AttentionMenu items={attention} onOpen={openFromAttention}/>
    {canCreate && <Button size="sm" className="w-full whitespace-nowrap" onClick={() => { setFormError(""); setFormProject(null); }}>
      <Plus size={16}/> New project
    </Button>}
  </> : null;

  if (loading) {
    return <section className="rounded-[22px] border border-line bg-white p-6"><LoadingSpinner label="Loading project portfolio…"/></section>;
  }

  return <section className="grid min-w-0 gap-4">
    <h2 className="sr-only">Projects</h2>

    {projects.length === 0
      // One call to action, inside the empty state. (The list toolbar's
      // buttons are sized for the 20rem list column, not a full-width row.)
      ? (() => {
          const canCreate = CAN_CREATE.includes(user.role);
          const noTemplates = canCreate && !templatesLoading && !templatesError && publishedTemplates.length === 0;
          const openForm = () => { setFormError(""); setFormProject(null); };
          return <EmptyState
            icon={<FolderKanban size={21}/>}
            title={!canCreate ? "No projects yet" : noTemplates ? "Publish a template first" : "No projects yet"}
            description={!canCreate
              ? "Projects will appear here once you're added to one."
              : noTemplates
                ? "Every project is built from a published schedule template. Create one in Templates and publish it, then come back to create the first project."
                : "Create a draft project, assign its PM and Supervisor, then activate it from a published template."}
            action={!canCreate || formProject !== undefined ? null
              : noTemplates
                ? (onTabChange ? <Button onClick={() => onTabChange("templates")}><BookOpenCheck size={17}/> Go to Templates</Button> : null)
                : <Button onClick={openForm}><Plus size={17}/> New project</Button>}
          />;
        })()
      : <div className="grid min-w-0 overflow-hidden rounded-[22px] border border-line bg-white lg:h-[calc(100dvh-9.75rem)] lg:min-h-[36rem] lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
          <ProjectListPane
            projects={projects}
            summaries={summaries}
            attentionByProject={attentionByProject}
            filter={filter}
            onFilterChange={setFilter}
            sort={sort}
            onSortChange={setSort}
            actions={listActions}
            search={search}
            onSearchChange={setSearch}
            selectedId={selected?.id}
            onOpen={openProject}
          />
          <div className="flex min-h-0 min-w-0 flex-col bg-[#fbfbfc]">
            {selected
              ? <ProjectWorkspace
                  key={selected.id}
                  projectId={selected.id}
                  references={references}
                  templates={publishedTemplates}
                  user={user}
                  summary={summaries?.[selected.id]}
                  attention={selectedAttention}
                  pane={route.pane || "overview"}
                  onPaneChange={next => setRoute({ pane: next })}
                  onEdit={project => { setFormError(""); setFormProject(project); }}
                  onChanged={refreshAll}
                  onDeleted={async () => { setRoute({ project: "", pane: "" }, { replace: true }); await refreshAll(); }}
                />
              : <p className="p-10 text-center text-sm text-slate-500">Select a project from the list.</p>}
          </div>
        </div>}

    {formProject !== undefined && <ProjectFormModal
      project={formProject}
      references={references}
      templates={publishedTemplates}
      templatesLoading={templatesLoading}
      templatesError={templatesError}
      apiError={formError}
      onClose={() => { if (!saving) setFormProject(undefined); }}
      onSubmit={saveProject}
      saving={saving}
    />}
  </section>;
}
