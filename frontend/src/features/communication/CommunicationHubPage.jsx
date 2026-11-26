import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronLeft, ChevronRight, Plus, Search, Tag } from "lucide-react";
import { communicationApi } from "../../api/communicationApi";
import { vendorAssignmentApi } from "../../api/vendorAssignmentApi";
import { vendorsApi } from "../../api/vendorsApi";
import { Button, ConfirmModal, EmptyState, LoadingSpinner, Modal, Popover } from "../../components/ui";
import { useRoute } from "../../lib/route";
import { groupFeedbackByVendor, summarizeFeedback } from "./vendorFeedback";
import { cn } from "../../utils/cn";
import { paginationItems } from "../../utils/pagination";

const emptyHub = { vendor_feedback: [], vendors: [], contacts: [], categories: [], projects: [], project_vendors: [], relationships: [], past_projects: [], project_history: [], contact_projects: [], contact_tasks: [] };
import { CompanyModal, ProfileModal, VENDOR_COLUMNS, VendorRow } from "./components/CommunicationDirectory";
import { VendorProfile } from "./components/VendorProfile";
import { BlacklistModal, canBlacklist, canUnblacklist, isBlocked } from "./components/VendorBlacklist";
import { VendorCategoryManager, canManageCategories } from "./components/VendorCategoryManager";

const PAGE_SIZE_OPTIONS = [10, 25, 50];
// Type and blacklist status share one segmented control.
const VIEW_OPTIONS = [["all", "All"], ["main", "Main"], ["sub", "Sub-vendors"], ["blacklisted", "Blacklisted"]];

export function CommunicationHubPage({ user, action }) {
  const [categoriesOpen, setCategoriesOpen] = useState(false);
  const [hub, setHub] = useState(emptyHub);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [projectId, setProjectId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [kind, setKind] = useState("all");
  const [sort, setSort] = useState({ key: "name", direction: "asc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // The open profile lives in the URL (?vendor=<id>): saves reload the whole
  // dashboard, which remounts this page, and the profile must survive that.
  const [route, setRoute] = useRoute();
  const selected = route.vendor || null;
  const setSelected = id => setRoute({ vendor: id || "" });
  const [form, setForm] = useState(null);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [confirmDeleteVendor, setConfirmDeleteVendor] = useState(null);
  const [deleteError, setDeleteError] = useState("");
  const [blacklistTarget, setBlacklistTarget] = useState(null); // { vendor, mode: "blacklist" | "remove" }
  const [blacklistError, setBlacklistError] = useState("");
  function openBlacklist(vendor, mode) { setBlacklistError(""); setBlacklistTarget({ vendor, mode }); }
  const canManage = user.role !== "supervisor";

  const addMenuRef = useRef(null);

  // `quiet` refreshes the data without the full-page spinner, so an open
  // vendor panel stays open (the spinner unmounts it).
  async function load({ quiet = false } = {}) {
    if (!quiet) setLoading(true);
    try {
      const data = await communicationApi.get();
      setHub({ ...emptyHub, ...data });
    } finally {
      if (!quiet) setLoading(false);
    }
  }
  useEffect(() => { load().catch(() => {}); }, []);

  useEffect(() => { setPage(1); }, [query, projectId, categoryId, kind, sort, pageSize]);

  // One save at a time. The ref is the real guard (a fast double-click fires
  // both submits before a state update re-renders the disabled button);
  // `saving` only drives the button's disabled/"Saving..." look. On the
  // hosted backend a create can take seconds (Render free tier cold start),
  // and an unguarded second click used to create the vendor twice.
  const savingRef = useRef(false);
  const [saving, setSaving] = useState(false);
  // `inPanel` is for saves made inside the open vendor panel (work history):
  // the dashboard reload `action` normally does would unmount this page and
  // close the panel, and nothing those saves change is dashboard data.
  async function perform(fn, message, { inPanel = false } = {}) {
    if (savingRef.current) return { ok: false, error: "A save is already in progress." };
    savingRef.current = true;
    setSaving(true);
    let saved = false;
    try {
      const result = await action(async () => {
        await fn();
        saved = true;
        // Close the form as soon as the writes succeed - `action` then
        // reloads the whole dashboard, and the form must not sit open (and
        // re-submittable) through that.
        setForm(null);
      }, message, { refresh: !inPanel });
      if (saved) await load({ quiet: inPanel });
      return result;
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }
  // A vendor created by a "create" attempt whose later steps (profile,
  // categories, contact) failed. Retrying the same form reuses it instead of
  // creating a second company. Cleared whenever a create form opens/closes.
  const pendingCompanyRef = useRef(null);
  useEffect(() => { pendingCompanyRef.current = null; }, [form]);
  async function deleteCompany(vendor) {
    const result = await perform(() => vendorsApi.remove(vendor.id), `${vendor.engagement_type === "main" ? "Main vendor" : "Sub-vendor"} deleted`);
    if (result?.ok) setSelected(null);
    return result;
  }
  async function confirmVendorDeletion() {
    setDeleteError("");
    const result = await deleteCompany(confirmDeleteVendor);
    if (result?.ok) setConfirmDeleteVendor(null);
    else setDeleteError(result?.error || "This vendor cannot be deleted while linked records remain.");
  }
  async function submit(event, fn, message) {
    event.preventDefault();
    await perform(() => fn(Object.fromEntries(new FormData(event.currentTarget))), message);
  }
  async function createCompany(event, mode) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const categoryIds = data.getAll("category_ids");
    const firstCategory = hub.categories.find(item => item.id === categoryIds[0])?.name || "Other";
    const legacy = { name: data.get("name"), category: firstCategory, contact_person: data.get("contact_person"), phone: data.get("phone"), whatsapp: data.get("whatsapp") || null, notes: data.get("notes") || null };
    const profile = { name: legacy.name, engagement_type: mode === "sub" ? "sub_vendor" : "main", parent_vendor_id: mode === "sub" ? data.get("main_contractor_id") : null, category_ids: categoryIds, email: data.get("email") || null, address: data.get("address") || null, gst_number: data.get("gst_number") || null, notes: legacy.notes };
    const contact = { name: legacy.contact_person, designation: data.get("designation") || null, phone: legacy.phone, whatsapp: legacy.whatsapp, is_primary: true };
    await perform(async () => {
      if (!pendingCompanyRef.current) pendingCompanyRef.current = await vendorsApi.create(legacy);
      const company = pendingCompanyRef.current;
      // updateContractor already sets parent_vendor_id for a sub-vendor,
      // which is now the sole source of that relationship - a follow-up
      // linkSubcontractor call would simply conflict with itself.
      await communicationApi.updateContractor(company.id, profile);
      await communicationApi.addContact({ ...contact, vendor_id: company.id });
      pendingCompanyRef.current = null;
    }, mode === "main" ? "Main vendor added" : "Sub-vendor added");
  }
  function savePastProject(vendorId, pastProjectId, payload) {
    return perform(
      () => pastProjectId ? communicationApi.updatePastProject(pastProjectId, payload) : communicationApi.addPastProject(vendorId, payload),
      pastProjectId ? "Past project updated" : "Past project added",
      { inPanel: true },
    );
  }
  function saveFeedback(vendorId, projectId, feedbackId, payload) {
    return perform(
      () => feedbackId ? communicationApi.updateFeedback(feedbackId, payload) : communicationApi.addFeedback(vendorId, projectId, payload),
      feedbackId ? "Feedback updated" : "Feedback added",
      { inPanel: true },
    );
  }
  function deleteFeedback(feedbackId) {
    return perform(() => communicationApi.deleteFeedback(feedbackId), "Feedback removed", { inPanel: true });
  }
  function deletePastProject(pastProjectId) {
    return perform(() => communicationApi.deletePastProject(pastProjectId), "Past project removed", { inPanel: true });
  }
  async function mapToProjects(vendor, projectIds) {
    return perform(async () => {
      for (const targetProjectId of projectIds) {
        await vendorAssignmentApi.mapVendor(targetProjectId, { vendor_id: vendor.id });
      }
    }, `Mapped to ${projectIds.length} project${projectIds.length === 1 ? "" : "s"}`);
  }
  async function updateCompany(event, vendorId) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await perform(() => communicationApi.updateContractor(vendorId, { name: data.get("name"), engagement_type: vendorById[vendorId]?.engagement_type || "main", category_ids: data.getAll("category_ids"), email: data.get("email") || null, address: data.get("address") || null, gst_number: data.get("gst_number") || null, notes: data.get("notes") || null }), "Vendor updated");
  }
  // Blacklist / remove from blacklist, with a reason (BlacklistModal).
  async function submitBlacklist(reason) {
    const { vendor, mode } = blacklistTarget;
    setBlacklistError("");
    const result = await perform(
      () => mode === "remove" ? communicationApi.unblacklistVendor(vendor.id, reason) : communicationApi.blacklistVendor(vendor.id, reason),
      mode === "remove" ? `${vendor.name} removed from the blacklist` : `${vendor.name} blacklisted`,
      { inPanel: true },
    );
    if (result?.ok) setBlacklistTarget(null);
    else setBlacklistError(result?.error || "That didn't work. Try again.");
  }

  const vendorById = useMemo(() => Object.fromEntries(hub.vendors.map(vendor => [vendor.id, vendor])), [hub.vendors]);
  const contactsFor = id => hub.contacts.filter(contact => contact.vendor_id === id);
  const primaryFor = id => contactsFor(id).find(contact => contact.is_primary) || contactsFor(id)[0];
  const childrenFor = id => {
    const relationBySubVendor = Object.fromEntries(hub.relationships.filter(item => item.main_contractor_id === id).map(item => [item.subcontractor_id, item]));
    return hub.vendors
      .filter(vendor => vendor.parent_vendor_id === id || relationBySubVendor[vendor.id])
      .map(vendor => ({ relation: relationBySubVendor[vendor.id] || { id: `parent-${vendor.id}`, main_contractor_id: id, subcontractor_id: vendor.id }, vendor }));
  };
  const projectsFor = id => { const vendor = vendorById[id]; const ids = new Set([id, vendor?.parent_vendor_id].filter(Boolean)); return hub.project_vendors.filter(link => ids.has(link.vendor_id)).map(link => hub.projects.find(project => project.id === link.project_id)).filter(Boolean); };
  const projectVendorIds = useMemo(() => new Set(hub.project_vendors.filter(link => !projectId || link.project_id === projectId).map(link => link.vendor_id)), [hub.project_vendors, projectId]);
  const matches = vendor => {
    const text = `${vendor.name} ${(vendor.categories || []).join(" ")} ${contactsFor(vendor.id).map(contact => contact.name).join(" ")}`.toLowerCase();
    return text.includes(query.toLowerCase()) && (kind !== "blacklisted" || isBlocked(vendor)) && (!categoryId || vendor.category_ids?.includes(categoryId));
  };
  const projectMatches = vendor => { if (!projectId || projectVendorIds.has(vendor.id)) return true; if (vendor.engagement_type === "sub_vendor") return Boolean(vendor.parent_vendor_id && projectVendorIds.has(vendor.parent_vendor_id)); return false; };
  const typeMatches = vendor => (kind === "main" ? vendor.engagement_type === "main" : kind === "sub" ? vendor.engagement_type !== "main" : true);

  const filtered = useMemo(
    () => hub.vendors.filter(vendor => typeMatches(vendor) && projectMatches(vendor) && matches(vendor)),
    [hub.vendors, hub.contacts, kind, projectId, projectVendorIds, query, categoryId],
  );
  // Sorted, then sub-vendors pulled up under their main vendor when both are
  // listed, so the hierarchy reads top to bottom.
  const feedbackByVendor = useMemo(() => groupFeedbackByVendor(hub.vendor_feedback || []), [hub.vendor_feedback]);
  const ratingByVendor = useMemo(() => Object.fromEntries(Object.entries(feedbackByVendor).map(([id, items]) => [id, summarizeFeedback(items)])), [feedbackByVendor]);
  const sorted = useMemo(() => {
    const sign = sort.direction === "desc" ? -1 : 1;
    // Unrated vendors sort after rated ones in either direction.
    const ratingOf = vendor => ratingByVendor[vendor.id]?.average ?? null;
    const byRating = (a, b) => {
      const left = ratingOf(a), right = ratingOf(b);
      if (left === null || right === null) return (left === null) - (right === null) || a.name.localeCompare(b.name);
      return (left - right) * sign || a.name.localeCompare(b.name);
    };
    const byKey = (a, b) => (sort.key === "projects"
      ? (projectsFor(a.id).length - projectsFor(b.id).length) * sign || a.name.localeCompare(b.name)
      : sort.key === "rating" ? byRating(a, b)
      : a.name.localeCompare(b.name) * sign);
    const arr = [...filtered].sort(byKey);
    const listed = new Set(arr.map(vendor => vendor.id));
    const nestedUnder = vendor => vendor.engagement_type !== "main" && vendor.parent_vendor_id && listed.has(vendor.parent_vendor_id);
    const rows = [];
    arr.filter(vendor => !nestedUnder(vendor)).forEach(vendor => {
      rows.push({ vendor, nested: false });
      arr.filter(child => nestedUnder(child) && child.parent_vendor_id === vendor.id).forEach(child => rows.push({ vendor: child, nested: true }));
    });
    return rows;
  }, [filtered, sort, hub.project_vendors, ratingByVendor]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const pageSafe = Math.min(page, totalPages);
  const pageRows = sorted.slice((pageSafe - 1) * pageSize, pageSafe * pageSize);

  const selectedVendor = vendorById[selected];
  // Hidden categories (an Admin removed them while vendors still had them)
  // drop out of pickers; filters still list them while vendors hold them.
  const pickerCategories = useMemo(() => hub.categories.filter(category => category.active !== false), [hub.categories]);
  const filterCategories = useMemo(() => hub.categories.filter(category => category.active !== false || (category.vendor_count || 0) > 0), [hub.categories]);
  const profileCategories = vendor => hub.categories.filter(category => category.active !== false || (vendor?.category_ids || []).includes(category.id));
  const blacklistedCount = hub.vendors.filter(vendor => vendor.blacklisted).length;

  function clearFilters() { setQuery(""); setCategoryId(""); setKind("all"); setProjectId(""); }
  const filtersOn = Boolean(query || categoryId || projectId || kind !== "all");
  const onLiveProjects = new Set(hub.project_vendors.filter(link => hub.projects.find(project => project.id === link.project_id)?.status === "active").map(link => link.vendor_id)).size;
  // Trades with vendors first, so the menu leads with what is useful.
  const tradeOptions = [...filterCategories].sort((a, b) => (b.vendor_count || 0) - (a.vendor_count || 0) || a.name.localeCompare(b.name));
  function toggleSort(key) {
    setSort(current => current.key === key ? { key, direction: current.direction === "asc" ? "desc" : "asc" } : { key, direction: key === "projects" || key === "rating" ? "desc" : "asc" });
  }

  if (loading) return <div className="grid min-h-40 place-items-center"><LoadingSpinner label="Loading vendor hub..." /></div>;

  const profileFor = selectedVendor && <VendorProfile vendor={selectedVendor} parentVendor={vendorById[selectedVendor.parent_vendor_id]} subVendors={childrenFor(selectedVendor.id).map(item => item.vendor)}
      contacts={contactsFor(selectedVendor.id)} projects={projectsFor(selectedVendor.id)}
      unmappedProjects={hub.projects.filter(project => project.status === "active" && !projectsFor(selectedVendor.id).some(mapped => mapped.id === project.id))}
      mapToProjects={projectIds => mapToProjects(selectedVendor, projectIds)} categories={hub.categories}
      canManage={canManage} onBack={() => setSelected(null)}
      remove={() => deleteCompany(selectedVendor)} edit={() => setForm("edit")} blacklist={() => openBlacklist(selectedVendor, "blacklist")} unblacklist={() => openBlacklist(selectedVendor, "remove")}
      addContact={() => setForm("contact")} addSubcontractor={() => setForm("sub")} selectVendor={setSelected}
      user={user} saving={saving}
      pastProjects={hub.past_projects.filter(item => item.vendor_id === selectedVendor.id)}
      projectHistory={hub.project_history.filter(item => item.vendor_id === selectedVendor.id)}
      savePastProject={(pastProjectId, payload) => savePastProject(selectedVendor.id, pastProjectId, payload)}
      deletePastProject={deletePastProject}
      feedback={feedbackByVendor[selectedVendor.id] || []}
      saveFeedback={(projectId, feedbackId, payload) => saveFeedback(selectedVendor.id, projectId, feedbackId, payload)}
      deleteFeedback={deleteFeedback}
      contactProjects={hub.contact_projects} contactTasks={hub.contact_tasks}/>;

  const SortButton = ({ column, label, className }) => {
    const active = sort.key === column;
    return <button type="button" onClick={() => toggleSort(column)} aria-label={`Sort by ${label}`} className={cn("inline-flex items-center gap-1 hover:text-slate-950", active && "text-slate-950", className)}>
      {label}{active && (sort.direction === "asc" ? <ArrowUp size={13}/> : <ArrowDown size={13}/>)}
    </button>;
  };

  return <div className="grid gap-4">
    {selectedVendor ? profileFor : <>
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-[17px] font-medium text-slate-950">Vendors and site contacts</h2>
        <p className="mt-0.5 text-sm text-slate-500">
          {hub.vendors.length} {hub.vendors.length === 1 ? "vendor" : "vendors"}, {hub.contacts.length} {hub.contacts.length === 1 ? "contact" : "contacts"}, {onLiveProjects} on live projects{blacklistedCount > 0 ? `, ${blacklistedCount} blacklisted` : ""}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {canManageCategories(user) && <Button variant="secondary" onClick={() => setCategoriesOpen(true)}><Tag size={16}/> Categories</Button>}
        {canManage && <div ref={addMenuRef} className="relative shrink-0">
          <Button onClick={() => setAddMenuOpen(v => !v)} aria-expanded={addMenuOpen}><Plus size={17}/> Add vendor <ChevronDown size={15}/></Button>
          <Popover anchorRef={addMenuRef} open={addMenuOpen} onClose={() => setAddMenuOpen(false)} role="menu" className="grid w-52 gap-0.5 p-1.5">
            <button type="button" onClick={() => { setAddMenuOpen(false); setForm("main"); }} className="rounded-xl px-3 py-2 text-left text-sm text-slate-800 hover:bg-slate-50">Add main vendor</button>
            <button type="button" onClick={() => { setAddMenuOpen(false); setForm("contact"); }} className="rounded-xl px-3 py-2 text-left text-sm text-slate-800 hover:bg-slate-50">Add contact</button>
          </Popover>
        </div>}
      </div>
    </header>

    <div className="flex flex-wrap items-center gap-2 rounded-[20px] border border-line bg-white p-2">
      <label className="relative min-w-[220px] flex-1">
        <span className="sr-only">Search vendors</span>
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search vendor, trade or contact"
          className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-950 outline-none placeholder:text-slate-400 focus:border-blue-600 focus:bg-white"/>
      </label>
      <select aria-label="Trade" value={categoryId} onChange={event => setCategoryId(event.target.value)} className={cn("h-9 rounded-lg border bg-white px-2.5 text-sm outline-none focus:border-blue-600", categoryId ? "border-slate-950 text-slate-950" : "border-slate-200 text-slate-700")}>
        <option value="">All trades</option>
        {tradeOptions.map(category => <option key={category.id} value={category.id}>{category.name} ({category.vendor_count || 0})</option>)}
      </select>
      <select aria-label="Project" value={projectId} onChange={event => setProjectId(event.target.value)} className={cn("h-9 max-w-[220px] rounded-lg border bg-white px-2.5 text-sm outline-none focus:border-blue-600", projectId ? "border-slate-950 text-slate-950" : "border-slate-200 text-slate-700")}>
        <option value="">All projects</option>{hub.projects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}
      </select>
      <div role="group" aria-label="Vendor type" className="flex gap-0.5 rounded-[10px] bg-slate-100 p-[3px]">
        {VIEW_OPTIONS.map(([value, label]) => <button key={value} type="button" aria-pressed={kind === value} onClick={() => setKind(value)}
          className={cn("h-8 rounded-lg px-2.5 text-[13px] transition", kind === value ? "bg-white text-slate-950 shadow-[0_1px_3px_rgba(21,23,26,.12)]" : "text-slate-500 hover:text-slate-950")}>
          {label}{value === "blacklisted" && blacklistedCount > 0 ? ` ${blacklistedCount}` : ""}
        </button>)}
      </div>
      {filtersOn && <button type="button" onClick={clearFilters} className="h-9 rounded-lg px-2 text-[13px] text-slate-600 hover:bg-slate-100">Clear</button>}
    </div>

    <section aria-label="Vendors" className="overflow-hidden rounded-[20px] border border-line bg-white">
      {pageRows.length === 0
        ? <EmptyState className="m-4" title={hub.vendors.length ? "No vendors match" : "No vendors yet"} description={hub.vendors.length ? "Try a different search term or clear your filters." : "Add your first main vendor to start assigning site work."}/>
        : <>
          <div className={cn("hidden gap-x-4 border-b border-line bg-slate-50 px-5 py-2.5 text-[13px] text-slate-500 md:grid", VENDOR_COLUMNS)}>
            <SortButton column="name" label="Vendor"/><span>Trades</span><span>Primary contact</span><SortButton column="rating" label="Rating"/><SortButton column="projects" label="Projects" className="justify-end"/><span className="sr-only">Status and actions</span>
          </div>
          <div className="divide-y divide-line">
            {pageRows.map(({ vendor, nested }) => <VendorRow key={vendor.id} vendor={vendor} nested={nested} parentName={vendorById[vendor.parent_vendor_id]?.name}
              primary={primaryFor(vendor.id)} projectCount={projectsFor(vendor.id).length} rating={ratingByVendor[vendor.id]}
              selected={vendor.id === selected} onSelect={() => setSelected(vendor.id)}
              onEdit={canManage ? () => { setSelected(vendor.id); setForm("edit"); } : undefined} onDelete={canManage ? () => setConfirmDeleteVendor(vendor) : undefined}
              canBlacklist={canBlacklist(user)} canUnblacklist={canUnblacklist(user)}
              onBlacklist={() => openBlacklist(vendor, "blacklist")} onUnblacklist={() => openBlacklist(vendor, "remove")}/>)}
          </div>
        </>}

      {sorted.length > 0 && <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-slate-50 px-4 py-2.5">
        <span className="text-xs text-slate-500">Showing {(pageSafe - 1) * pageSize + 1}–{Math.min(pageSafe * pageSize, sorted.length)} of {sorted.length}</span>
        {totalPages > 1 && <nav aria-label="Vendor pages" className="flex items-center gap-1">
          <button type="button" aria-label="Previous page" disabled={pageSafe === 1} onClick={() => setPage(pageSafe - 1)} className="grid size-8 place-items-center rounded-lg text-slate-600 hover:bg-white disabled:opacity-40"><ChevronLeft size={16}/></button>
          {paginationItems(pageSafe, totalPages).map((item, i) => item === "..."
            ? <span key={`ellipsis-${i}`} className="px-1 text-xs text-slate-400">...</span>
            : <button key={item} type="button" aria-current={item === pageSafe ? "page" : undefined} onClick={() => setPage(item)} className={cn("grid size-8 place-items-center rounded-lg text-xs tabular-nums", item === pageSafe ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-white")}>{item}</button>)}
          <button type="button" aria-label="Next page" disabled={pageSafe === totalPages} onClick={() => setPage(pageSafe + 1)} className="grid size-8 place-items-center rounded-lg text-slate-600 hover:bg-white disabled:opacity-40"><ChevronRight size={16}/></button>
        </nav>}
        <label className="flex items-center gap-2 text-xs text-slate-500">Rows
          <select value={pageSize} onChange={event => setPageSize(Number(event.target.value))} className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-800 outline-none focus:border-blue-600">
            {PAGE_SIZE_OPTIONS.map(size => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
      </footer>}
    </section>
    </>}

    {categoriesOpen && <VendorCategoryManager onClose={() => setCategoriesOpen(false)} onChanged={() => load({ quiet: true })}/>}
    {form === "main" && <CompanyModal title="Add main vendor" categories={pickerCategories} saving={saving} onClose={() => setForm(null)} onSubmit={event => createCompany(event, "main")}/>}
    {form === "sub" && selectedVendor?.engagement_type === "main" && <CompanyModal title="Add sub-vendor" categories={pickerCategories} fixedMainContractor={selectedVendor} saving={saving} onClose={() => setForm(null)} onSubmit={event => createCompany(event, "sub")}/>}
    {form === "edit" && selectedVendor && <ProfileModal vendor={selectedVendor} categories={profileCategories(selectedVendor)} saving={saving} onClose={() => setForm(null)} onSubmit={event => updateCompany(event, selectedVendor.id)}/>}
    {form === "contact" && <Modal title="Add vendor contact" subtitle="Add a person under a main vendor or sub-vendor" onClose={() => setForm(null)}>
      <form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-medium [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-slate-950 [&>button]:px-5 [&>button]:font-medium [&>button]:text-white two-col grid-cols-2 max-[720px]:grid-cols-1" onSubmit={event => submit(event, payload => communicationApi.addContact({ ...payload, is_primary: false }), "Contact added")}>
        <label className="full-field col-span-full max-[720px]:col-span-1">Vendor<select name="vendor_id" defaultValue={selectedVendor?.id || ""} required>{hub.vendors.map(vendor => <option value={vendor.id} key={vendor.id}>{vendor.name}</option>)}</select></label>
        <label>Name<input name="name" required/></label>
        <label>Designation<input name="designation"/></label>
        <label>Phone<input name="phone" required/></label>
        <label>WhatsApp<input name="whatsapp"/></label>
        <button disabled={saving} className="disabled:cursor-not-allowed disabled:opacity-60">{saving ? "Saving..." : "Add contact"}</button>
      </form>
    </Modal>}
    {canManage && !selectedVendor && <button className="fixed bottom-24 right-4 z-30 grid size-14 place-items-center rounded-full bg-slate-950 p-0 text-white shadow-xl min-[721px]:hidden" aria-label="Add vendor" onClick={() => setForm("main")}><Plus/></button>}

    {blacklistTarget && <BlacklistModal vendor={blacklistTarget.vendor} mode={blacklistTarget.mode} saving={saving} error={blacklistError}
      projectCount={projectsFor(blacklistTarget.vendor.id).length} subVendorCount={childrenFor(blacklistTarget.vendor.id).length}
      onClose={() => setBlacklistTarget(null)} onSubmit={submitBlacklist}/>}

    {confirmDeleteVendor && (() => {
      const blocked = confirmDeleteVendor.engagement_type === "main" && childrenFor(confirmDeleteVendor.id).length > 0;
      return <ConfirmModal
        title={blocked ? "Deletion blocked" : `Delete ${confirmDeleteVendor.name}?`}
        message={deleteError || (blocked
          ? `This main vendor has ${childrenFor(confirmDeleteVendor.id).length} linked sub-vendor(s). Transfer or delete them first, or edit this vendor and mark it inactive.`
          : "This permanently removes the company, its contacts and relationships, and unassigns it from current tasks.")}
        confirmLabel={blocked ? "Linked sub-vendors must be resolved" : "Delete permanently"}
        confirmDisabled={blocked}
        onClose={() => { setConfirmDeleteVendor(null); setDeleteError(""); }}
        onConfirm={confirmVendorDeletion}/>;
    })()}
  </div>;
}
