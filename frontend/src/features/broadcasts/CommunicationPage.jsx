import { MoreHorizontal, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { broadcastApi } from "../../api/broadcastApi";
import { projectsApi } from "../../api/projectsApi";
import { Button, ConfirmModal } from "../../components/ui";
import { useRoute } from "../../lib/route";
import { cn } from "../../utils/cn";
import { summaryLine } from "./broadcastFormat";
import { BroadcastComposer } from "./components/BroadcastComposer";
import { BroadcastDetail, EmptyReader } from "./components/BroadcastDetail";
import { BroadcastList } from "./components/BroadcastList";

const SECTIONS = [
  ["sent", "Sent"],
  ["scheduled", "Scheduled"],
  ["templates", "Templates"],
];
const PAGE = 30;
const EMPTY_SUMMARY = { messages_sent: 0, total_recipients: 0, delivery_success_rate: 0, scheduled: 0, failed: 0 };

function TemplateMenu({ template, onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  return <div ref={ref} className="relative">
    <button type="button" aria-label={`More actions for ${template.name}`} aria-expanded={open} onClick={() => setOpen(value => !value)}
      className="grid size-8 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-950"><MoreHorizontal size={16}/></button>
    {open && <div role="menu" className="absolute right-0 top-[calc(100%+4px)] z-20 w-44 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      <button type="button" role="menuitem" onClick={() => { setOpen(false); onDelete(template); }} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-rose-700 hover:bg-rose-50"><Trash2 size={15}/> Delete template</button>
    </div>}
  </div>;
}

function TemplatesSection({ templates, loading, onUse, onDelete, onNew }) {
  if (loading) return <p className="rounded-[20px] border border-line bg-white p-10 text-center text-sm text-slate-500">Loading templates…</p>;
  if (!templates.length) return <div className="grid justify-items-center gap-2 rounded-[20px] border border-line bg-white px-6 py-12 text-center">
    <p className="text-sm text-slate-950">No templates yet</p>
    <p className="max-w-sm text-sm text-slate-500">Write a broadcast you send often, like a weekly site review, then save it as a template from the composer.</p>
    <Button variant="secondary" size="sm" className="mt-2" onClick={onNew}><Plus size={15}/> New broadcast</Button>
  </div>;
  return <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
    {templates.map(template => <li key={template.id} className="flex flex-col rounded-[20px] border border-line bg-white p-5">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[15px] font-medium text-slate-950">{template.name}</h3>
        <TemplateMenu template={template} onDelete={onDelete}/>
      </div>
      <p className="mt-1 text-sm text-slate-700">{template.title}</p>
      <p className="mt-2 line-clamp-3 flex-1 whitespace-pre-wrap text-[13px] leading-5 text-slate-500">{template.message_body || template.agenda}</p>
      <Button variant="secondary" size="sm" className="mt-4 self-start" onClick={() => onUse(template)}>Use template</Button>
    </li>)}
  </ul>;
}

export function CommunicationPage({ action }) {
  const [route, setRoute] = useRoute();
  const section = SECTIONS.some(([key]) => key === route.pane) ? route.pane : "sent";
  const selectedId = route.broadcast || "";

  const [projects, setProjects] = useState([]);
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [summaryLoaded, setSummaryLoaded] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [broadcasts, setBroadcasts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [composer, setComposer] = useState(null);
  const [deleting, setDeleting] = useState(null);

  async function loadTemplates() {
    setTemplatesLoading(true);
    try { setTemplates(await broadcastApi.templates()); } catch { setTemplates([]); } finally { setTemplatesLoading(false); }
  }

  useEffect(() => {
    projectsApi.list({ status: "active" }).then(list => setProjects(list.map(project => ({ id: project.id, name: project.name, code: project.code })))).catch(() => {});
    broadcastApi.summary().then(data => { setSummary(data); setSummaryLoaded(true); }).catch(() => setSummaryLoaded(true));
    loadTemplates();
  }, []);

  useEffect(() => {
    if (section === "templates") return undefined;
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      broadcastApi.list({ status: section === "scheduled" ? "scheduled" : "", search: search.trim(), limit })
        .then(data => { if (!cancelled) setBroadcasts(section === "sent" ? data.filter(item => item.status !== "scheduled") : data); })
        .catch(() => { if (!cancelled) setBroadcasts([]); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, search ? 250 : 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [section, search, limit]);

  function goSection(key, nextStatus = "") {
    setStatus(nextStatus);
    setLimit(PAGE);
    setRoute({ pane: key === "sent" ? "" : key, broadcast: "" });
  }
  function openBroadcast(id) { setRoute({ broadcast: id || "" }); }
  function openComposer(template = null) { setComposer({ template }); }

  // On a wide screen the reading pane is never blank when there is something
  // to read: show the newest message until one is picked.
  const shown = status ? broadcasts.filter(item => item.status === status) : broadcasts;
  const wide = typeof window !== "undefined" && window.matchMedia?.("(min-width: 1024px)").matches;
  const activeId = selectedId || (wide ? shown[0]?.id : "") || "";

  async function sendNow(broadcast) {
    // The dashboard refresh remounts this page; the open message survives in the URL.
    await action(() => broadcastApi.send(broadcast.id), "Broadcast sent");
  }

  async function deleteTemplate() {
    const template = deleting;
    setDeleting(null);
    const result = await action(() => broadcastApi.deleteTemplate(template.id), "Template deleted", { refresh: false });
    if (result?.ok) loadTemplates();
  }

  const sentCount = (summary.messages_sent || 0) + (summary.failed || 0);
  const counts = { sent: sentCount, scheduled: summary.scheduled || 0, templates: templates.length };

  return <div className="grid gap-4">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-[17px] font-medium text-slate-950">Broadcasts</h2>
        <p className="mt-0.5 text-sm text-slate-500">
          {summaryLoaded ? summaryLine(summary) : "Loading…"}
          {summary.failed > 0 && <>, <button type="button" onClick={() => goSection("sent", "failed")} className="text-rose-700 hover:underline">{summary.failed} failed</button></>}
        </p>
      </div>
      <Button onClick={() => openComposer()}><Plus size={17}/> New broadcast</Button>
    </header>

    <nav aria-label="Communication sections" className="flex gap-1 overflow-x-auto border-b border-line">
      {SECTIONS.map(([key, label]) => {
        const active = section === key;
        return <button key={key} type="button" onClick={() => goSection(key)} aria-current={active ? "page" : undefined}
          className={cn("inline-flex min-h-11 shrink-0 items-center gap-1.5 whitespace-nowrap px-2.5 text-sm transition-colors", active ? "text-slate-950 shadow-[inset_0_-2px_0_var(--color-slate-950)]" : "text-slate-500 hover:text-slate-950")}>
          {label}{" "}<span className={cn("tabular-nums text-xs", active ? "text-slate-500" : "text-slate-400")}>{counts[key]}</span>
        </button>;
      })}
    </nav>

    {section === "templates"
      ? <TemplatesSection templates={templates} loading={templatesLoading} onUse={openComposer} onDelete={setDeleting} onNew={() => openComposer()}/>
      : <div className="grid gap-4 lg:h-[calc(100dvh-14rem)] lg:min-h-[480px] lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)]">
          <div className={cn("min-h-0 lg:grid", selectedId ? "hidden" : "grid")}>
            <BroadcastList broadcasts={shown} allBroadcasts={broadcasts} loading={loading} search={search} onSearchChange={setSearch}
              status={status} onStatusChange={setStatus} showStatusFilter={section === "sent"} ascending={section === "scheduled"}
              selectedId={activeId} onOpen={broadcast => openBroadcast(broadcast.id)}
              onLoadMore={() => setLimit(current => current + PAGE)} hasMore={broadcasts.length >= limit}
              emptyTitle={section === "scheduled" ? "Nothing scheduled" : "No messages sent yet"}
              emptyDescription={section === "scheduled" ? "Schedule a broadcast for later and it waits here until it goes out." : "Send a broadcast and you'll be able to read it back and see who got it."}
              emptyAction={<Button variant="secondary" size="sm" className="mt-2" onClick={() => openComposer()}><Plus size={15}/> New broadcast</Button>}/>
          </div>
          <div className={cn("min-h-0 lg:grid", selectedId ? "grid" : "hidden")}>
            {activeId ? <BroadcastDetail key={activeId} broadcastId={activeId} onBack={() => openBroadcast("")} onSendNow={sendNow}/> : <EmptyReader/>}
          </div>
        </div>}

    {composer && <BroadcastComposer projects={projects} templates={templates} action={action} initialTemplate={composer.template}
      onClose={() => setComposer(null)} onCreated={() => setComposer(null)} onTemplateSaved={loadTemplates}/>}

    {deleting && <ConfirmModal title="Delete template?" message={`"${deleting.name}" will be removed. Broadcasts already sent with it are not affected.`}
      confirmLabel="Delete template" onClose={() => setDeleting(null)} onConfirm={deleteTemplate}/>}
  </div>;
}
