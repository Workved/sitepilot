import { AlertOctagon, CalendarClock, CheckCircle2, Plus, Send, Trash2, Users2 } from "lucide-react";
import { useEffect, useState } from "react";
import { broadcastApi } from "../../api/broadcastApi";
import { projectsApi } from "../../api/projectsApi";
import { Button, EmptyState, LoadingSpinner, Modal, RefreshButton } from "../../components/ui";
import { cn } from "../../utils/cn";
import { BroadcastComposer } from "./components/BroadcastComposer";
import { BroadcastList } from "./components/BroadcastList";
import { KpiCard } from "./components/KpiCard";
import { MessageHistory } from "./components/MessageHistory";
import { RecipientPreviewDrawer } from "./components/RecipientPreviewDrawer";

const TABS = [
  ["messages", "Broadcast Messages"],
  ["scheduled", "Scheduled"],
  ["history", "Message History"],
  ["templates", "Templates"],
];
const EMPTY_SUMMARY = { messages_sent: 0, total_recipients: 0, delivery_success_rate: 0, scheduled: 0, failed: 0 };

function TemplatesTab({ templates, loading, action, onChanged }) {
  async function remove(template) {
    const result = await action(() => broadcastApi.deleteTemplate(template.id), "Template deleted");
    if (result?.ok) onChanged();
  }

  if (loading) return <div className="grid min-h-40 place-items-center"><LoadingSpinner label="Loading templates…" /></div>;
  if (!templates.length) return <EmptyState title="No templates yet" description="Save a broadcast's content as a template from the composer to reuse it next time." />;

  return <div className="grid gap-3 sm:grid-cols-2">
    {templates.map(template => <article key={template.id} className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-black text-slate-950">{template.name}</h3>
        <button type="button" aria-label={`Delete ${template.name}`} onClick={() => remove(template)} className="grid size-8 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-rose-50 hover:text-rose-700"><Trash2 size={15} /></button>
      </div>
      <p className="text-sm font-bold text-slate-700">{template.title}</p>
      {template.agenda && <p className="line-clamp-2 text-xs text-slate-500">{template.agenda}</p>}
      <p className="line-clamp-2 text-xs text-slate-400">{template.message_body}</p>
    </article>)}
  </div>;
}

export function CommunicationPage({ action }) {
  const [activeTab, setActiveTab] = useState("messages");
  const [projects, setProjects] = useState([]);
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [broadcasts, setBroadcasts] = useState([]);
  const [broadcastsLoading, setBroadcastsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [messagesStatus, setMessagesStatus] = useState("");
  const [limit, setLimit] = useState(20);
  const [detail, setDetail] = useState(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  async function loadProjects() {
    const list = await projectsApi.list({ status: "active" });
    setProjects(list.map(project => ({ id: project.id, name: project.name, code: project.code })));
  }
  async function loadSummary() { setSummary(await broadcastApi.summary()); }
  async function loadTemplates() {
    setTemplatesLoading(true);
    try { setTemplates(await broadcastApi.templates()); } finally { setTemplatesLoading(false); }
  }
  async function loadBroadcasts() {
    setBroadcastsLoading(true);
    try {
      const statusParam = activeTab === "scheduled" ? "scheduled" : activeTab === "messages" ? messagesStatus : "";
      const data = await broadcastApi.list({ status: statusParam, search, limit });
      setBroadcasts(activeTab === "history" ? data.filter(item => item.status !== "scheduled") : data);
    } finally {
      setBroadcastsLoading(false);
    }
  }

  useEffect(() => { loadProjects().catch(() => {}); loadSummary().catch(() => {}); loadTemplates().catch(() => {}); }, []);
  useEffect(() => { setLimit(20); }, [activeTab, search, messagesStatus]);
  useEffect(() => { if (activeTab !== "templates") loadBroadcasts().catch(() => {}); }, [activeTab, search, messagesStatus, limit]);

  async function openDetail(broadcast) {
    setDetail(await broadcastApi.detail(broadcast.id));
  }
  async function sendNow(broadcast) {
    const result = await action(() => broadcastApi.send(broadcast.id), "Broadcast sent");
    if (result?.ok) { loadBroadcasts(); loadSummary(); }
  }
  function afterCreate() { loadBroadcasts(); loadSummary(); setComposerOpen(false); }
  function afterTemplateChange() { loadTemplates(); }

  function openComposer() { setActiveTab("messages"); setComposerOpen(true); }

  async function refreshAll() {
    setRefreshing(true);
    try {
      await Promise.all([
        loadSummary(),
        loadProjects(),
        activeTab === "templates" ? loadTemplates() : loadBroadcasts(),
      ]);
    } finally {
      setRefreshing(false);
    }
  }

  return <div className="grid gap-6">
    <section className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-6">
      <div>
        <p className="text-xs font-medium text-slate-500">Communication</p>
        <h2 className="mt-2 text-3xl font-normal tracking-tight text-slate-950">Communication</h2>
        <span className="mt-2 block text-sm text-slate-500">Send announcements, meeting alerts, quick discussions and updates to your project teams.</span>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <RefreshButton loading={refreshing} onClick={refreshAll}/>
        <Button onClick={openComposer}><Plus size={17} /> Create Broadcast</Button>
      </div>
    </section>

    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <KpiCard icon={<Send size={20} className="text-blue-600" />} tone="border-blue-200 bg-blue-50" label="Messages Sent" value={summary.messages_sent} />
      <KpiCard icon={<Users2 size={20} className="text-violet-600" />} tone="border-violet-200 bg-violet-50" label="Total Recipients" value={summary.total_recipients} />
      <KpiCard icon={<CheckCircle2 size={20} className="text-emerald-600" />} tone="border-emerald-200 bg-emerald-50" label="Delivery Success" value={`${summary.delivery_success_rate}%`} />
      <KpiCard icon={<CalendarClock size={20} className="text-amber-600" />} tone="border-amber-200 bg-amber-50" label="Scheduled" value={summary.scheduled} />
      <KpiCard icon={<AlertOctagon size={20} className="text-rose-600" />} tone="border-rose-200 bg-rose-50" label="Failed" value={summary.failed} className="col-span-2 sm:col-span-1" />
    </section>

    <nav className="flex flex-wrap gap-1 rounded-2xl border border-slate-200 bg-white p-1.5" aria-label="Communication sections">
      {TABS.map(([key, label]) => <button key={key} type="button" onClick={() => setActiveTab(key)} aria-current={activeTab === key ? "page" : undefined}
        className={cn("rounded-xl px-4 py-2.5 text-sm font-black transition", activeTab === key ? "bg-slate-950 text-white" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900")}>{label}</button>)}
    </nav>

    {activeTab === "messages" && <BroadcastList broadcasts={broadcasts} loading={broadcastsLoading} search={search} onSearchChange={setSearch}
      status={messagesStatus} onStatusChange={setMessagesStatus} onOpen={openDetail} onSendNow={sendNow}
      onLoadMore={() => setLimit(current => current + 20)} hasMore={broadcasts.length >= limit} />}

    {activeTab === "scheduled" && <BroadcastList broadcasts={broadcasts} loading={broadcastsLoading} search={search} onSearchChange={setSearch}
      showStatusFilter={false} onOpen={openDetail} onSendNow={sendNow} onLoadMore={() => setLimit(current => current + 20)} hasMore={broadcasts.length >= limit}
      emptyTitle="Nothing scheduled" emptyDescription="Broadcasts you schedule for later will appear here until they're sent." />}

    {activeTab === "history" && <MessageHistory broadcasts={broadcasts} loading={broadcastsLoading} search={search} onSearchChange={setSearch}
      onOpen={openDetail} onLoadMore={() => setLimit(current => current + 20)} hasMore={broadcasts.length >= limit} />}

    {activeTab === "templates" && <TemplatesTab templates={templates} loading={templatesLoading} action={action} onChanged={afterTemplateChange} />}

    {detail && <RecipientPreviewDrawer title={detail.title} subtitle={`${detail.project_name} · ${detail.recipient_count} recipient${detail.recipient_count === 1 ? "" : "s"}`}
      recipients={detail.recipients} readOnly deliverySummary={detail.delivery_summary} onClose={() => setDetail(null)} />}

    {composerOpen && <Modal title="New Broadcast" subtitle="Send an announcement, meeting alert, quick discussion or update to a project team." onClose={() => setComposerOpen(false)} className="sm:max-w-3xl">
      <BroadcastComposer embedded projects={projects} templates={templates} action={action} onCreated={afterCreate} onTemplateSaved={afterTemplateChange} />
    </Modal>}
  </div>;
}
