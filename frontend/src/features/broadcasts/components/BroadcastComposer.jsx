import { AlertTriangle, CalendarClock, CalendarDays, ChevronDown, Clock, MapPin, Save, Send } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { broadcastApi } from "../../../api/broadcastApi";
import { Button, Field, Input, Modal, Select, Textarea } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { formatDateShort } from "../../../utils/format";
import { plural } from "../broadcastFormat";
import { GROUP_ORDER, RecipientGroupSelector } from "./RecipientGroupSelector";
import { RecipientPreviewDrawer } from "./RecipientPreviewDrawer";

const EMPTY_FORM = { title: "", meetingDate: "", meetingTime: "", locationOrLink: "", agenda: "", messageBody: "" };

function formFromTemplate(template) {
  if (!template) return EMPTY_FORM;
  return { ...EMPTY_FORM, title: template.title || "", agenda: template.agenda || "", messageBody: template.message_body || "" };
}

function Step({ title, children, actions }) {
  return <section className="grid gap-3">
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-[15px] font-medium text-slate-950">{title}</h3>
      {actions}
    </div>
    {children}
  </section>;
}

function TemplatePicker({ templates, onPick }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  if (!templates.length) return null;
  return <div ref={ref} className="relative">
    <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)} className="inline-flex items-center gap-1 text-sm text-blue-700 hover:underline">Use a template <ChevronDown size={14}/></button>
    {open && <div role="menu" className="absolute right-0 top-[calc(100%+6px)] z-20 grid max-h-64 w-60 gap-0.5 overflow-y-auto rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      {templates.map(template => <button key={template.id} type="button" role="menuitem" onClick={() => { setOpen(false); onPick(template); }} className="rounded-xl px-3 py-2 text-left text-sm text-slate-800 hover:bg-slate-50">{template.name}</button>)}
    </div>}
  </div>;
}

// What recipients will see, updated as you type.
export function MessagePreview({ form, projectName }) {
  const facts = [
    form.meetingDate && [CalendarDays, formatDateShort(form.meetingDate)],
    form.meetingTime && [Clock, form.meetingTime],
    form.locationOrLink && [MapPin, form.locationOrLink],
  ].filter(Boolean);
  return <div className="rounded-[18px] bg-canvas p-3" aria-label="Message preview">
    <div className="rounded-2xl rounded-tl-md bg-white p-4 shadow-[0_1px_2px_rgba(21,23,26,.08)]">
      {projectName && <p className="text-xs text-slate-500">{projectName}</p>}
      <p className={cn("mt-0.5 text-[15px] font-medium", form.title ? "text-slate-950" : "text-slate-400")}>{form.title || "Your title"}</p>
      {facts.length > 0 && <ul className="mt-2 grid gap-1 text-[13px] text-slate-600">
        {facts.map(([Icon, text]) => <li key={text} className="flex items-center gap-1.5"><Icon size={13} className="shrink-0 text-slate-400" aria-hidden="true"/><span className="truncate">{text}</span></li>)}
      </ul>}
      {form.agenda && <p className="mt-3 whitespace-pre-wrap text-[13px] leading-5 text-slate-600">{form.agenda}</p>}
      <p className={cn("mt-3 whitespace-pre-wrap text-sm leading-6", form.messageBody ? "text-slate-800" : "text-slate-400")}>{form.messageBody || "Your message appears here as you write it."}</p>
    </div>
  </div>;
}

export function BroadcastComposer({ projects, templates, action, initialTemplate, onClose, onCreated, onTemplateSaved }) {
  const [sendMode, setSendMode] = useState("now");
  const [projectId, setProjectId] = useState(projects.length === 1 ? projects[0].id : "");
  const [selectedGroups, setSelectedGroups] = useState(new Set(GROUP_ORDER));
  const [excludedKeys, setExcludedKeys] = useState(new Set());
  const [counts, setCounts] = useState({});
  const [allRecipients, setAllRecipients] = useState([]);
  const [loadingRecipients, setLoadingRecipients] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [form, setForm] = useState(() => formFromTemplate(initialTemplate));
  const [scheduledDate, setScheduledDate] = useState("");
  const [scheduledTime, setScheduledTime] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  // Opened by the user or by a template with an agenda; never snapped shut
  // just because the fields were cleared.
  const [detailsOpen, setDetailsOpen] = useState(() => Boolean(initialTemplate?.agenda));

  // Fetched once per project (always the full group set) and filtered by
  // `recipient_type` client-side: an empty `groups` query would fall back to
  // "all groups" server-side, which is wrong when every group is unticked.
  useEffect(() => {
    if (!projectId) { setCounts({}); setAllRecipients([]); return undefined; }
    let cancelled = false;
    setLoadingRecipients(true);
    broadcastApi.recipients(projectId, GROUP_ORDER)
      .then(data => { if (!cancelled) { setCounts(data.counts); setAllRecipients(data.recipients); } })
      .catch(() => { if (!cancelled) { setCounts({}); setAllRecipients([]); } })
      .finally(() => { if (!cancelled) setLoadingRecipients(false); });
    return () => { cancelled = true; };
  }, [projectId]);

  const recipients = useMemo(() => allRecipients.filter(recipient => selectedGroups.has(recipient.recipient_type)), [allRecipients, selectedGroups]);
  const included = recipients.filter(item => !excludedKeys.has(item.key));
  const unreachable = included.filter(item => !(item.channels || []).length).length;
  const selectedProject = projects.find(project => project.id === projectId);

  function setField(key, value) { setForm(current => ({ ...current, [key]: value })); }
  function selectProject(id) { setProjectId(id); setSelectedGroups(new Set(GROUP_ORDER)); setExcludedKeys(new Set()); }
  function toggleGroup(group) { setSelectedGroups(prev => { const next = new Set(prev); next.has(group) ? next.delete(group) : next.add(group); return next; }); }
  function toggleAllGroups(selectAll) { setSelectedGroups(selectAll ? new Set(GROUP_ORDER) : new Set()); }
  function toggleExclude(key) { setExcludedKeys(prev => { const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next; }); }
  function applyTemplate(template) { if (template.agenda) setDetailsOpen(true); setForm(current => ({ ...current, ...formFromTemplate(template), meetingDate: current.meetingDate, meetingTime: current.meetingTime, locationOrLink: current.locationOrLink })); }

  async function handleSubmit() {
    setFormError("");
    if (!projectId) return setFormError("Select a project to message.");
    if (selectedGroups.size === 0) return setFormError("Select at least one recipient group.");
    if (!form.title.trim()) return setFormError("Enter a title.");
    if (!form.messageBody.trim()) return setFormError("Enter a message body.");
    let scheduledAt = null;
    if (sendMode === "scheduled") {
      if (!scheduledDate || !scheduledTime) return setFormError("Choose a schedule date and time.");
      scheduledAt = new Date(`${scheduledDate}T${scheduledTime}:00`).toISOString();
    }

    setSubmitting(true);
    const result = await action(() => broadcastApi.create({
      project_id: projectId, title: form.title, meeting_date: form.meetingDate || null, meeting_time: form.meetingTime || null,
      location_or_link: form.locationOrLink || null, agenda: form.agenda || null, message_body: form.messageBody,
      recipient_groups: [...selectedGroups], excluded_recipient_keys: [...excludedKeys],
      send_mode: sendMode, scheduled_at: scheduledAt,
    }), sendMode === "scheduled" ? "Broadcast scheduled" : "Broadcast sent");
    setSubmitting(false);
    if (result?.ok) onCreated?.(); else setFormError(result?.error || "The broadcast could not be sent.");
  }

  async function handleSaveTemplate() {
    if (!templateName.trim()) return;
    const result = await action(() => broadcastApi.createTemplate({
      name: templateName, title: form.title || "Untitled message", agenda: form.agenda || null, message_body: form.messageBody || "",
    }), "Template saved", { refresh: false });
    if (result?.ok) { setSaveTemplateOpen(false); setTemplateName(""); onTemplateSaved?.(); }
  }

  const scheduleLabel = scheduledDate && scheduledTime ? `${formatDateShort(scheduledDate)}, ${scheduledTime}` : "";
  const sendLabel = sendMode === "scheduled"
    ? (scheduleLabel ? `Schedule for ${scheduleLabel}` : "Schedule broadcast")
    : `Send to ${plural(included.length, "person", "people")}`;

  const footer = <div className="flex flex-wrap items-center gap-3">
    {formError && <p role="alert" className="flex items-center gap-1.5 text-sm text-rose-700"><AlertTriangle size={15}/>{formError}</p>}
    <div className="ml-auto flex items-center gap-2">
      <Button variant="ghost" onClick={() => setSaveTemplateOpen(true)} disabled={!form.title.trim() && !form.messageBody.trim()}><Save size={15}/> Save as template</Button>
      <Button loading={submitting} onClick={handleSubmit}>{sendMode === "scheduled" ? <CalendarClock size={16}/> : <Send size={16}/>}{sendLabel}</Button>
    </div>
  </div>;

  return <Modal title="New broadcast" subtitle="Message everyone on a project team at once, by WhatsApp and in the app." onClose={onClose} className="sm:max-w-5xl" footer={footer}>
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="grid content-start gap-6">
        <Step title="Project">
          <Field label="Which project team?" htmlFor="broadcast-project">
            <Select id="broadcast-project" value={projectId} onChange={event => selectProject(event.target.value)}>
              <option value="">Choose an active project…</option>
              {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
            </Select>
          </Field>
          {!projects.length && <p className="text-sm text-slate-500">There are no active projects to message yet.</p>}
        </Step>

        {projectId && <Step title="Who gets it" actions={<button type="button" onClick={() => setDrawerOpen(true)} disabled={!recipients.length} className="text-sm text-blue-700 hover:underline disabled:pointer-events-none disabled:opacity-40">Review people</button>}>
          <RecipientGroupSelector counts={counts} selectedGroups={selectedGroups} onToggleGroup={toggleGroup} onToggleAll={toggleAllGroups} loading={loadingRecipients}/>
        </Step>}

        <Step title="Message" actions={<TemplatePicker templates={templates} onPick={applyTemplate}/>}>
          <Field label="Title" htmlFor="broadcast-title"><Input id="broadcast-title" value={form.title} onChange={event => setField("title", event.target.value)} placeholder="Weekly site review, or just a quick update"/></Field>
          <Field label="Message body" htmlFor="broadcast-body"><Textarea id="broadcast-body" className="min-h-32" value={form.messageBody} onChange={event => setField("messageBody", event.target.value)} placeholder="Write the announcement recipients will see…"/></Field>
          <details className="group rounded-2xl border border-line" open={detailsOpen} onToggle={event => setDetailsOpen(event.currentTarget.open)}>
            <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm text-slate-700">
              Meeting details and agenda <span className="text-xs text-slate-400">optional</span>
            </summary>
            <div className="grid gap-4 border-t border-line p-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Date" htmlFor="broadcast-date"><Input id="broadcast-date" type="date" value={form.meetingDate} onChange={event => setField("meetingDate", event.target.value)}/></Field>
                <Field label="Time" htmlFor="broadcast-time"><Input id="broadcast-time" type="time" value={form.meetingTime} onChange={event => setField("meetingTime", event.target.value)}/></Field>
              </div>
              <Field label="Location or link" htmlFor="broadcast-location"><Input id="broadcast-location" value={form.locationOrLink} onChange={event => setField("locationOrLink", event.target.value)} placeholder="Site office, or a video call link"/></Field>
              <Field label="Agenda or notes" htmlFor="broadcast-agenda"><Textarea id="broadcast-agenda" value={form.agenda} onChange={event => setField("agenda", event.target.value)} placeholder="What this covers"/></Field>
            </div>
          </details>
        </Step>

        <Step title="When">
          <div role="group" aria-label="When to send" className="flex w-fit gap-0.5 rounded-[10px] bg-slate-100 p-[3px]">
            {[["now", "Send now"], ["scheduled", "Schedule"]].map(([value, label]) => <button key={value} type="button" aria-pressed={sendMode === value} onClick={() => setSendMode(value)}
              className={cn("h-8 rounded-lg px-3 text-[13px] transition", sendMode === value ? "bg-white text-slate-950 shadow-[0_1px_3px_rgba(21,23,26,.12)]" : "text-slate-500 hover:text-slate-950")}>{label}</button>)}
          </div>
          {sendMode === "scheduled" && <div className="grid grid-cols-2 gap-3">
            <Field label="Send on" htmlFor="broadcast-schedule-date"><Input id="broadcast-schedule-date" type="date" value={scheduledDate} onChange={event => setScheduledDate(event.target.value)}/></Field>
            <Field label="Send at" htmlFor="broadcast-schedule-time"><Input id="broadcast-schedule-time" type="time" value={scheduledTime} onChange={event => setScheduledTime(event.target.value)}/></Field>
          </div>}
        </Step>
      </div>

      <aside className="grid content-start gap-3 lg:sticky lg:top-0">
        <h3 className="text-[15px] font-medium text-slate-950">What they'll see</h3>
        <MessagePreview form={form} projectName={selectedProject?.name}/>
        {projectId && <div className="rounded-2xl border border-line p-4 text-sm">
          <p className="text-slate-950">{loadingRecipients ? "Finding people…" : `${plural(included.length, "person", "people")} will get this`}</p>
          {!loadingRecipients && unreachable > 0 && <p className="mt-1 flex items-center gap-1.5 text-orange-700"><AlertTriangle size={14}/>{unreachable} {unreachable === 1 ? "has" : "have"} no phone or email</p>}
          {!loadingRecipients && excludedKeys.size > 0 && <p className="mt-1 text-slate-500">{excludedKeys.size} left out by you</p>}
        </div>}
      </aside>
    </div>

    {drawerOpen && <RecipientPreviewDrawer title="Who gets it" subtitle={selectedProject?.name} recipients={recipients} excludedKeys={excludedKeys} onToggleExclude={toggleExclude} onClose={() => setDrawerOpen(false)}/>}

    {saveTemplateOpen && <Modal title="Save as template" subtitle="Reuse this title, agenda and message on a future broadcast." onClose={() => setSaveTemplateOpen(false)} className="sm:max-w-md"
      footer={<div className="flex justify-end"><Button onClick={handleSaveTemplate} disabled={!templateName.trim()}>Save template</Button></div>}>
      <Field label="Template name" htmlFor="template-name"><Input id="template-name" autoFocus value={templateName} onChange={event => setTemplateName(event.target.value)} placeholder="e.g. Weekly site review"/></Field>
    </Modal>}
  </Modal>;
}
