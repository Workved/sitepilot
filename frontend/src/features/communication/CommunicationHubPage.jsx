import { useEffect, useMemo, useRef, useState } from "react";
import {
  Ban, ChevronDown, ChevronLeft, ChevronRight, ContactRound, FolderKanban,
  LayoutGrid, List, Plus, Search, SlidersHorizontal, Tag, UsersRound,
} from "lucide-react";
import { communicationApi } from "../../api/communicationApi";
import { vendorAssignmentApi } from "../../api/vendorAssignmentApi";
import { vendorsApi } from "../../api/vendorsApi";
import { ConfirmModal, EmptyState, LoadingSpinner, Modal, RefreshButton } from "../../components/ui";
import { cn } from "../../utils/cn";
import { paginationItems } from "../../utils/pagination";

const emptyHub = { vendors: [], contacts: [], categories: [], projects: [], project_vendors: [], relationships: [], past_projects: [], project_history: [], contact_projects: [], contact_tasks: [] };
import { CategoryChip, CompanyModal, Metric, ProfileModal, VendorRow } from "./components/CommunicationDirectory";
import { VendorDetailPanel } from "./components/VendorDetailPanel";
import { BlacklistModal, canBlacklist, canUnblacklist, isBlocked } from "./components/VendorBlacklist";

const SORT_OPTIONS = [
  ["name_asc", "Name (A-Z)"],
  ["name_desc", "Name (Z-A)"],
  ["newest", "Newest first"],
  ["projects_desc", "Most projects"],
];
const PAGE_SIZE_OPTIONS = [6, 12, 25];
const TYPE_OPTIONS = [["all", "All types"], ["main", "Main vendors"], ["sub", "Sub-vendors"]];

export function CommunicationHubPage({ user, action }) {
  const [hub, setHub] = useState(emptyHub);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [projectId, setProjectId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("all");
  const [sortBy, setSortBy] = useState("name_asc");
  const [viewMode, setViewMode] = useState("list");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(6);
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [confirmDeleteVendor, setConfirmDeleteVendor] = useState(null);
  const [deleteError, setDeleteError] = useState("");
  const [blacklistTarget, setBlacklistTarget] = useState(null); // { vendor, mode: "blacklist" | "remove" }
  const [blacklistError, setBlacklistError] = useState("");
  function openBlacklist(vendor, mode) { setBlacklistError(""); setBlacklistTarget({ vendor, mode }); }
  const canManage = user.role !== "supervisor";

  const filtersRef = useRef(null);
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

  useEffect(() => {
    function onClickOutside(event) {
      if (filtersRef.current && !filtersRef.current.contains(event.target)) setFiltersOpen(false);
      if (addMenuRef.current && !addMenuRef.current.contains(event.target)) setAddMenuOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => { setPage(1); }, [query, projectId, categoryId, status, type, sortBy, pageSize]);

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
    return text.includes(query.toLowerCase()) && (!status || (status === "blacklisted" && isBlocked(vendor))) && (!categoryId || vendor.category_ids?.includes(categoryId));
  };
  const projectMatches = vendor => { if (!projectId || projectVendorIds.has(vendor.id)) return true; if (vendor.engagement_type === "sub_vendor") return Boolean(vendor.parent_vendor_id && projectVendorIds.has(vendor.parent_vendor_id)); return false; };
  const typeMatches = vendor => (type === "all" ? true : type === "main" ? vendor.engagement_type === "main" : vendor.engagement_type !== "main");

  const filtered = useMemo(
    () => hub.vendors.filter(vendor => typeMatches(vendor) && projectMatches(vendor) && matches(vendor)),
    [hub.vendors, hub.contacts, type, projectId, projectVendorIds, query, status, categoryId],
  );
  const sorted = useMemo(() => {
    const arr = [...filtered];
    if (sortBy === "name_desc") arr.sort((a, b) => b.name.localeCompare(a.name));
    else if (sortBy === "newest") arr.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    else if (sortBy === "projects_desc") arr.sort((a, b) => projectsFor(b.id).length - projectsFor(a.id).length);
    else arr.sort((a, b) => a.name.localeCompare(b.name));
    return arr;
  }, [filtered, sortBy, hub.project_vendors]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const pageSafe = Math.min(page, totalPages);
  const pageVendors = sorted.slice((pageSafe - 1) * pageSize, pageSafe * pageSize);

  const selectedVendor = vendorById[selected];
  const activeProjects = hub.projects.filter(project => project.status === "active").length;
  const thisMonthVendors = useMemo(() => {
    const now = new Date();
    return hub.vendors.filter(vendor => {
      const created = new Date(vendor.created_at);
      return created.getFullYear() === now.getFullYear() && created.getMonth() === now.getMonth();
    }).length;
  }, [hub.vendors]);
  const categoriesInUse = hub.categories.filter(category => (category.vendor_count || 0) > 0).length;
  const blacklistedCount = hub.vendors.filter(vendor => vendor.blacklisted).length;
  const topCategories = useMemo(() => [...hub.categories].sort((a, b) => (b.vendor_count || 0) - (a.vendor_count || 0)).slice(0, 8), [hub.categories]);

  function clearFilters() { setCategoryId(""); setType("all"); setStatus(""); setProjectId(""); }

  if (loading) return <div className="grid min-h-40 place-items-center"><LoadingSpinner label="Loading vendor hub..." /></div>;

  return <div className="grid gap-6">
    <section className="grid gap-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-[0_12px_40px_rgba(15,23,42,.06)]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-black uppercase tracking-[.18em] text-blue-700">Vendor Hub</p>
          <h2 className="mt-2 text-3xl font-black tracking-tight text-slate-950">Vendors, contacts & site communication</h2>
          <span className="mt-2 block text-sm text-slate-500">Centralized directory of vendors and contacts across all projects.</span>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <RefreshButton loading={loading} onClick={() => load()}/>
          {canManage && <div ref={addMenuRef} className="relative shrink-0">
            <button type="button" onClick={() => setAddMenuOpen(v => !v)}
              className="flex min-h-11 items-center gap-2 rounded-xl bg-blue-700 px-4 text-sm font-black text-white shadow-[0_10px_24px_rgba(29,78,216,0.22)] transition hover:bg-blue-800">
              <Plus size={17}/> Add vendor <ChevronDown size={15}/>
            </button>
            {addMenuOpen && <div className="absolute right-0 top-[calc(100%+8px)] z-20 grid w-52 gap-0.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-[0_18px_50px_rgba(15,23,42,.14)]">
              <button type="button" onClick={() => { setAddMenuOpen(false); setForm("main"); }} className="rounded-lg px-3 py-2 text-left text-sm font-bold text-slate-700 hover:bg-slate-50">Add main vendor</button>
              <button type="button" onClick={() => { setAddMenuOpen(false); setForm("contact"); }} className="rounded-lg px-3 py-2 text-left text-sm font-bold text-slate-700 hover:bg-slate-50">Add contact</button>
            </div>}
          </div>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Metric icon={<UsersRound size={20}/>} label="Total Vendors" value={hub.vendors.length} hint={thisMonthVendors > 0 ? `+${thisMonthVendors} this month` : "Across all sites"} tone="border-blue-200 bg-blue-50"/>
        <Metric icon={<Tag size={20}/>} label="Active Categories" value={categoriesInUse} hint={`of ${hub.categories.length} total`} tone="border-emerald-200 bg-emerald-50"/>
        <Metric icon={<ContactRound size={20}/>} label="Site Contacts" value={hub.contacts.length} hint="Across all vendors" tone="border-violet-200 bg-violet-50"/>
        <Metric icon={<FolderKanban size={20}/>} label="Active Projects" value={activeProjects} hint={`of ${hub.projects.length} total`} tone="border-amber-200 bg-amber-50"/>
        <Metric icon={<Ban size={20}/>} label="Blacklisted" value={blacklistedCount} tone="border-rose-200 bg-rose-50" className="col-span-2 sm:col-span-1"
          action={blacklistedCount > 0 && <button type="button" onClick={() => setStatus("blacklisted")} className="text-[11px] font-black text-blue-700 hover:underline">See all</button>}/>
      </div>
    </section>

    <section className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_12px_40px_rgba(15,23,42,.06)]">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search vendor or contact..."
            className="min-h-11 w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm font-medium text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"/>
        </div>
        <select value={projectId} onChange={event => setProjectId(event.target.value)}
          className="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-700 outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10">
          <option value="">All Projects</option>{hub.projects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}
        </select>
        <select value={status} onChange={event => setStatus(event.target.value)}
          className="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-700 outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10">
          <option value="">All vendors</option><option value="blacklisted">Blacklisted</option>
        </select>
        <div ref={filtersRef} className="relative">
          <button type="button" onClick={() => setFiltersOpen(v => !v)}
            className={cn("flex min-h-11 items-center gap-2 rounded-xl border px-3.5 text-sm font-bold transition", (categoryId || type !== "all") ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50")}>
            <SlidersHorizontal size={16}/> More filters
          </button>
          {filtersOpen && <div className="absolute right-0 top-[calc(100%+8px)] z-20 grid w-64 gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-[0_18px_50px_rgba(15,23,42,.14)]">
            <div>
              <p className="px-1 pb-1.5 text-[10px] font-black uppercase tracking-wide text-slate-400">Type</p>
              <div className="grid gap-0.5">{TYPE_OPTIONS.map(([value, label]) => <button key={value} type="button" onClick={() => setType(value)}
                className={cn("rounded-lg px-2.5 py-1.5 text-left text-sm font-bold transition", type === value ? "bg-blue-700 text-white" : "text-slate-700 hover:bg-slate-50")}>{label}</button>)}</div>
            </div>
            <div>
              <p className="px-1 pb-1.5 text-[10px] font-black uppercase tracking-wide text-slate-400">Category</p>
              <div className="grid max-h-48 gap-0.5 overflow-y-auto">
                <button type="button" onClick={() => setCategoryId("")} className={cn("rounded-lg px-2.5 py-1.5 text-left text-sm font-bold transition", !categoryId ? "bg-blue-700 text-white" : "text-slate-700 hover:bg-slate-50")}>All categories</button>
                {hub.categories.map(category => <button key={category.id} type="button" onClick={() => setCategoryId(category.id)}
                  className={cn("flex items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-sm font-bold transition", categoryId === category.id ? "bg-blue-700 text-white" : "text-slate-700 hover:bg-slate-50")}>
                  {category.name}<span className={cn("text-xs", categoryId === category.id ? "text-blue-100" : "text-slate-400")}>{category.vendor_count || 0}</span>
                </button>)}
              </div>
            </div>
            {(categoryId || type !== "all" || status || projectId) && <button type="button" onClick={clearFilters} className="rounded-lg border border-slate-200 py-1.5 text-xs font-bold text-slate-500 hover:bg-slate-50">Clear filters</button>}
          </div>}
        </div>
        <select value={sortBy} onChange={event => setSortBy(event.target.value)}
          className="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-700 outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10">
          {SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>Sort: {label}</option>)}
        </select>
        <div className="flex items-center gap-1 rounded-xl border border-slate-200 bg-white p-1">
          <button type="button" onClick={() => setViewMode("list")} aria-pressed={viewMode === "list"} aria-label="List view"
            className={cn("grid size-9 place-items-center rounded-lg transition", viewMode === "list" ? "bg-blue-700 text-white" : "text-slate-500 hover:bg-slate-50")}><List size={16}/></button>
          <button type="button" onClick={() => setViewMode("grid")} aria-pressed={viewMode === "grid"} aria-label="Grid view"
            className={cn("grid size-9 place-items-center rounded-lg transition", viewMode === "grid" ? "bg-blue-700 text-white" : "text-slate-500 hover:bg-slate-50")}><LayoutGrid size={16}/></button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 overflow-x-auto pb-0.5">
        <CategoryChip label="All" count={hub.vendors.length} active={!categoryId} onClick={() => setCategoryId("")}/>
        {topCategories.map(category => <CategoryChip key={category.id} label={category.name} count={category.vendor_count || 0} active={categoryId === category.id} onClick={() => setCategoryId(current => current === category.id ? "" : category.id)}/>)}
        {hub.categories.length > topCategories.length && <CategoryChip label="More" count={hub.categories.length - topCategories.length} active={filtersOpen} onClick={() => setFiltersOpen(true)}/>}
      </div>
    </section>

    {/* VendorDetailPanel is a fixed-position overlay drawer (same chrome as
        Execution's TaskDetailDrawer) - no grid-cols split needed to host it. */}
    <div className="grid gap-3">
      {pageVendors.length === 0
        ? <EmptyState title="No vendors match" description="Try a different search term or clear your filters."/>
        : <div className={viewMode === "grid" ? "grid gap-3 sm:grid-cols-2" : "grid gap-3"}>
            {pageVendors.map(vendor => <VendorRow key={vendor.id} vendor={vendor} primary={primaryFor(vendor.id)} projectCount={projectsFor(vendor.id).length}
              selected={vendor.id === selected} layout={viewMode} onSelect={() => setSelected(vendor.id)}
              onEdit={() => { setSelected(vendor.id); setForm("edit"); }} onDelete={() => setConfirmDeleteVendor(vendor)}
              canBlacklist={canBlacklist(user)} canUnblacklist={canUnblacklist(user)}
              onBlacklist={() => openBlacklist(vendor, "blacklist")} onUnblacklist={() => openBlacklist(vendor, "remove")}/>)}
          </div>}

      {sorted.length > 0 && <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3">
        <span className="text-xs font-semibold text-slate-500">Showing {(pageSafe - 1) * pageSize + 1} to {Math.min(pageSafe * pageSize, sorted.length)} of {sorted.length} vendors</span>
        <div className="flex items-center gap-1">
          <button type="button" disabled={pageSafe === 1} onClick={() => setPage(pageSafe - 1)} className="grid size-8 place-items-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-50 disabled:pointer-events-none disabled:opacity-40"><ChevronLeft size={15}/></button>
          {paginationItems(pageSafe, totalPages).map((item, i) => item === "..."
            ? <span key={`ellipsis-${i}`} className="px-1 text-xs font-bold text-slate-400">...</span>
            : <button key={item} type="button" onClick={() => setPage(item)} className={cn("grid size-8 place-items-center rounded-lg text-xs font-black transition", item === pageSafe ? "bg-blue-700 text-white" : "text-slate-600 hover:bg-slate-50")}>{item}</button>)}
          <button type="button" disabled={pageSafe === totalPages} onClick={() => setPage(pageSafe + 1)} className="grid size-8 place-items-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-50 disabled:pointer-events-none disabled:opacity-40"><ChevronRight size={15}/></button>
        </div>
        <label className="flex items-center gap-2 text-xs font-semibold text-slate-500">Rows per page:
          <select value={pageSize} onChange={event => setPageSize(Number(event.target.value))} className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-bold text-slate-700 outline-none focus:border-blue-600">
            {PAGE_SIZE_OPTIONS.map(size => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
      </div>}
    </div>

    {selectedVendor && <VendorDetailPanel vendor={selectedVendor} parentVendor={vendorById[selectedVendor.parent_vendor_id]} subVendors={childrenFor(selectedVendor.id).map(item => item.vendor)}
      contacts={contactsFor(selectedVendor.id)} projects={projectsFor(selectedVendor.id)}
      unmappedProjects={hub.projects.filter(project => project.status === "active" && !projectsFor(selectedVendor.id).some(mapped => mapped.id === project.id))}
      mapToProjects={projectIds => mapToProjects(selectedVendor, projectIds)} categories={hub.categories}
      canManage={canManage} onClose={() => setSelected(null)}
      remove={() => deleteCompany(selectedVendor)} edit={() => setForm("edit")} blacklist={() => openBlacklist(selectedVendor, "blacklist")} unblacklist={() => openBlacklist(selectedVendor, "remove")}
      addContact={() => setForm("contact")} addSubcontractor={() => setForm("sub")} selectVendor={setSelected}
      onContactChanged={load}
      user={user} saving={saving}
      pastProjects={hub.past_projects.filter(item => item.vendor_id === selectedVendor.id)}
      projectHistory={hub.project_history.filter(item => item.vendor_id === selectedVendor.id)}
      savePastProject={(pastProjectId, payload) => savePastProject(selectedVendor.id, pastProjectId, payload)}
      deletePastProject={deletePastProject}
      contactProjects={hub.contact_projects} contactTasks={hub.contact_tasks}/>}

    {form === "main" && <CompanyModal title="Add main vendor" categories={hub.categories} saving={saving} onClose={() => setForm(null)} onSubmit={event => createCompany(event, "main")}/>}
    {form === "sub" && selectedVendor?.engagement_type === "main" && <CompanyModal title="Add sub-vendor" categories={hub.categories} fixedMainContractor={selectedVendor} saving={saving} onClose={() => setForm(null)} onSubmit={event => createCompany(event, "sub")}/>}
    {form === "edit" && selectedVendor && <ProfileModal vendor={selectedVendor} categories={hub.categories} saving={saving} onClose={() => setForm(null)} onSubmit={event => updateCompany(event, selectedVendor.id)}/>}
    {form === "contact" && <Modal title="Add vendor contact" subtitle="Add a person under a main vendor or sub-vendor" onClose={() => setForm(null)}>
      <form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white two-col grid-cols-2 max-[720px]:grid-cols-1" onSubmit={event => submit(event, payload => communicationApi.addContact({ ...payload, is_primary: false }), "Contact added")}>
        <label className="full-field col-span-full max-[720px]:col-span-1">Vendor<select name="vendor_id" defaultValue={selectedVendor?.id || ""} required>{hub.vendors.map(vendor => <option value={vendor.id} key={vendor.id}>{vendor.name}</option>)}</select></label>
        <label>Name<input name="name" required/></label>
        <label>Designation<input name="designation"/></label>
        <label>Phone<input name="phone" required/></label>
        <label>WhatsApp<input name="whatsapp"/></label>
        <button disabled={saving} className="disabled:cursor-not-allowed disabled:opacity-60">{saving ? "Saving..." : "Add contact"}</button>
      </form>
    </Modal>}
    {canManage && <button className="fixed bottom-24 right-4 z-30 grid size-14 place-items-center rounded-full bg-blue-700 p-0 text-white shadow-xl min-[721px]:hidden" aria-label="Add vendor" onClick={() => setForm("main")}><Plus/></button>}

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
