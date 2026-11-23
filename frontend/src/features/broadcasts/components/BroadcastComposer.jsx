import { CalendarClock, Eye, Save, Send, Sparkles, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { broadcastApi } from "../../../api/broadcastApi";
import { Button, Field, Input, Modal, Select, Textarea } from "../../../components/ui";
import { cn } from "../../../utils/cn";
import { formatDateShort } from "../../../utils/format";
import { GROUP_ORDER, RecipientGroupSelector } from "./RecipientGroupSelector";
import { RecipientPreviewDrawer } from "./RecipientPreviewDrawer";

const EMPTY_FORM = { title: "", meetingDate: "", meetingTime: "", locationOrLink: "", agenda: "", messageBody: "" };

export function BroadcastComposer({ projects, templates, action, onCreated, onTemplateSaved, embedded = false }) {
  const [sendMode, setSendMode] = useState("now");
  const [projectId, setProjectId] = useState("");
  const [selectedGroups, setSelectedGroups] = useState(new Set());
  const [excludedKeys, setExcludedKeys] = useState(new Set());
  const [counts, setCounts] = useState({});
  const [allRecipients, setAllRecipients] = useState([]);
  const [loadingRecipients, setLoadingRecipients] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [templateMenuOpen, setTemplateMenuOpen] = useState(false);
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [scheduledDate, setScheduledDate] = useState("");
  const [scheduledTime, setScheduledTime] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  // Fetched once per project (always the full group set) rather than
  // re-fetched on every checkbox toggle: `counts` never depends on the
  // current selection anyway, and filtering the already-loaded superset by
  // `recipient_type` client-side keeps "Preview recipient list" in sync
  // with an empty selection too (an empty `groups` query param would
  // otherwise fall back to "all groups" server-side, per the /recipients
  // route, which is right for a blank filter bar but wrong here).
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

  const recipients = useMemo(
    () => allRecipients.filter(recipient => selectedGroups.has(recipient.recipient_type)),
    [allRecipients, selectedGroups],
  );

  function setField(key, value) { setForm(current => ({ ...current, [key]: value })); }

  function selectProject(id) {
    setProjectId(id);
    setSelectedGroups(new Set(GROUP_ORDER));
    setExcludedKeys(new Set());
  }

  function toggleGroup(group) {
    setSelectedGroups(prev => { const next = new Set(prev); next.has(group) ? next.delete(group) : next.add(group); return next; });
  }
  function toggleAllGroups(selectAll) { setSelectedGroups(selectAll ? new Set(GROUP_ORDER) : new Set()); }
  function toggleExclude(key) { setExcludedKeys(prev => { const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next; }); }

  function applyTemplate(template) {
    setTemplateMenuOpen(false);
    setField("title", template.title);
    setField("agenda", template.agenda || "");
    setField("messageBody", template.message_body);
  }

  function resetForm() {
    setForm(EMPTY_FORM);
    setScheduledDate("");
    setScheduledTime("");
    setSendMode("now");
    setExcludedKeys(new Set());
  }

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
    if (result?.ok) { resetForm(); onCreated?.(); } else setFormError(result?.error || "The broadcast could not be sent.");
  }

  async function handleSaveTemplate() {
    if (!templateName.trim()) return;
    const result = await action(() => broadcastApi.createTemplate({
      name: templateName, title: form.title || "Untitled message", agenda: form.agenda || null, message_body: form.messageBody || "",
    }), "Template saved");
    if (result?.ok) { setSaveTemplateOpen(false); setTemplateName(""); onTemplateSaved?.(); }
  }

  const includedCount = recipients.filter(item => !excludedKeys.has(item.key)).length;
  const selectedProject = projects.find(project => project.id === projectId);

  return <section className={cn("grid gap-5", !embedded && "rounded-2xl border border-slate-200 bg-white p-5")}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      {!embedded && <div>
        <p className="text-xs font-medium text-slate-500">Create</p>
        <h3 className="mt-1 text-lg font-black text-slate-950">New Broadcast</h3>
      </div>}
      <div className={cn("flex items-center gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1", embedded && "ml-auto")}>
        <button type="button" onClick={() => setSendMode("now")} className={cn("rounded-lg px-3 py-1.5 text-xs font-black transition", sendMode === "now" ? "bg-blue-700 text-white" : "text-slate-500 hover:bg-white")}>Send Now</button>
        <button type="button" onClick={() => setSendMode("scheduled")} className={cn("rounded-lg px-3 py-1.5 text-xs font-black transition", sendMode === "scheduled" ? "bg-blue-700 text-white" : "text-slate-500 hover:bg-white")}>Schedule</button>
      </div>
    </div>

    <Field label="Select project" htmlFor="broadcast-project">
      <Select id="broadcast-project" value={projectId} onChange={event => selectProject(event.target.value)}>
        <option value="">Choose an active project…</option>
        {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </Select>
    </Field>

    {projectId && <>
      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-sm font-black text-slate-800"><Users size={15} /> Recipients</span>
          <button type="button" onClick={() => setDrawerOpen(true)} disabled={!recipients.length} className="text-xs font-bold text-blue-700 hover:underline disabled:pointer-events-none disabled:opacity-40">Preview recipient list →</button>
        </div>
        <RecipientGroupSelector counts={counts} selectedGroups={selectedGroups} onToggleGroup={toggleGroup} onToggleAll={toggleAllGroups} loading={loadingRecipients} />
      </div>

      <div className="grid gap-4 border-t border-slate-100 pt-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-black text-slate-800">Message details</p>
          {templates.length > 0 && <div className="relative">
            <button type="button" onClick={() => setTemplateMenuOpen(v => !v)} className="flex items-center gap-1.5 text-xs font-bold text-blue-700 hover:underline"><Sparkles size={13} /> Use a template</button>
            {templateMenuOpen && <div className="absolute right-0 top-[calc(100%+6px)] z-20 grid w-56 gap-0.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-[0_18px_50px_rgba(15,23,42,.14)]">
              {templates.map(template => <button key={template.id} type="button" onClick={() => applyTemplate(template)} className="rounded-lg px-3 py-2 text-left text-sm font-bold text-slate-700 hover:bg-slate-50">{template.name}</button>)}
            </div>}
          </div>}
        </div>

        <Field label="Title" htmlFor="broadcast-title"><Input id="broadcast-title" value={form.title} onChange={event => setField("title", event.target.value)} placeholder="Weekly site review, or just a quick update" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date (optional)" htmlFor="broadcast-date"><Input id="broadcast-date" type="date" value={form.meetingDate} onChange={event => setField("meetingDate", event.target.value)} /></Field>
          <Field label="Time (optional)" htmlFor="broadcast-time"><Input id="broadcast-time" type="time" value={form.meetingTime} onChange={event => setField("meetingTime", event.target.value)} /></Field>
        </div>
        <Field label="Location or link (optional)" htmlFor="broadcast-location"><Input id="broadcast-location" value={form.locationOrLink} onChange={event => setField("locationOrLink", event.target.value)} placeholder="Site office, or a video call link" /></Field>
        <Field label="Agenda or notes (optional)" htmlFor="broadcast-agenda"><Textarea id="broadcast-agenda" value={form.agenda} onChange={event => setField("agenda", event.target.value)} placeholder="What this covers - leave blank for a quick message" /></Field>
        <Field label="Message body" htmlFor="broadcast-body"><Textarea id="broadcast-body" className="min-h-32" value={form.messageBody} onChange={event => setField("messageBody", event.target.value)} placeholder="Write the announcement recipients will see…" /></Field>

        {sendMode === "scheduled" && <div className="grid grid-cols-2 gap-3 rounded-2xl border border-blue-200 bg-blue-50/60 p-3">
          <Field label="Send on" htmlFor="broadcast-schedule-date"><Input id="broadcast-schedule-date" type="date" value={scheduledDate} onChange={event => setScheduledDate(event.target.value)} /></Field>
          <Field label="Send at" htmlFor="broadcast-schedule-time"><Input id="broadcast-schedule-time" type="time" value={scheduledTime} onChange={event => setScheduledTime(event.target.value)} /></Field>
        </div>}
      </div>

      {formError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{formError}</div>}

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
        <Button type="button" variant="secondary" size="sm" onClick={() => setPreviewOpen(true)}><Eye size={15} /> Preview Message</Button>
        <Button type="button" variant="secondary" size="sm" onClick={() => setSaveTemplateOpen(true)}><Save size={15} /> Save as Template</Button>
        <Button type="button" size="sm" loading={submitting} onClick={handleSubmit} className="ml-auto">
          {sendMode === "scheduled" ? <CalendarClock size={15} /> : <Send size={15} />}
          {sendMode === "scheduled" ? "Schedule Broadcast" : "Send Broadcast"} ({includedCount})
        </Button>
      </div>
    </>}

    {drawerOpen && <RecipientPreviewDrawer title="Recipient preview" subtitle={selectedProject?.name} recipients={recipients} excludedKeys={excludedKeys} onToggleExclude={toggleExclude} onClose={() => setDrawerOpen(false)} />}

    {previewOpen && <Modal title="Message preview" subtitle={selectedProject?.name} onClose={() => setPreviewOpen(false)}>
      <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <h3 className="text-lg font-black text-slate-950">{form.title || "Untitled message"}</h3>
        <p className="text-sm font-bold text-slate-600">
          {form.meetingDate ? formatDateShort(form.meetingDate) : "No date set"}{form.meetingTime ? ` · ${form.meetingTime}` : ""}
          {form.locationOrLink ? ` · ${form.locationOrLink}` : ""}
        </p>
        {form.agenda && <div><p className="text-xs font-medium text-slate-500">Agenda</p><p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{form.agenda}</p></div>}
        <div><p className="text-xs font-medium text-slate-500">Message</p><p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{form.messageBody || "No message written yet."}</p></div>
      </div>
    </Modal>}

    {saveTemplateOpen && <Modal title="Save as template" subtitle="Reuse this title, agenda and message on a future broadcast." onClose={() => setSaveTemplateOpen(false)}
      footer={<div className="flex justify-end"><Button onClick={handleSaveTemplate} disabled={!templateName.trim()}>Save template</Button></div>}>
      <Field label="Template name" htmlFor="template-name"><Input id="template-name" autoFocus value={templateName} onChange={event => setTemplateName(event.target.value)} placeholder="e.g. Weekly Site Review" /></Field>
    </Modal>}
  </section>;
}
