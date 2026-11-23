import { AlertCircle, CheckCircle2, RefreshCw, Rocket, TriangleAlert, Wrench } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { templatesApi } from "../../../api/templatesApi";
import { Alert, Button, Field, Modal, Textarea } from "../../../components/ui";
import { issueCopy } from "./templateReviewCopy";

function responseMessage(error) {
  const detail = error?.details?.detail;
  if (detail?.code === "stale_template_version") return "This draft changed in another session. Refresh it and check again.";
  if (detail?.code === "template_validation_failed") return detail.message || "The draft still has problems to fix.";
  if (typeof detail?.message === "string") return detail.message;
  if (typeof error?.message === "string") return error.message;
  return "The request could not be completed.";
}

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

function PublishModal({ initialNote, busy, error, onClose, onPublish }) {
  // Starts from the note written when the draft was created or cloned.
  const [changeNote, setChangeNote] = useState(initialNote || "");
  const [localError, setLocalError] = useState("");
  function submit() {
    const note = changeNote.trim();
    if (!note) {
      setLocalError("A change note is required before publishing.");
      return;
    }
    setLocalError("");
    onPublish(note);
  }
  return <Modal title="Publish this version?" subtitle="New projects will use this version." onClose={onClose} className="sm:max-w-xl">
    <div className="grid gap-5">
      <Alert tone="warning"><TriangleAlert size={18}/><div><strong>It can't be edited after publishing</strong><span className="mt-1 block">New projects will use it; existing projects don't change. To make more changes later, clone it into a new draft.</span></div></Alert>
      {(error || localError) && <Alert tone="danger" role="alert"><AlertCircle size={18}/><div><strong>Not published</strong><span className="mt-1 block">{localError || responseMessage(error)}</span></div></Alert>}
      <Field label="Change note" hint="What changed in this version.">
        <Textarea aria-label="Change note" value={changeNote} onChange={event => setChangeNote(event.target.value)} placeholder="Updated flooring sequence and Fire NOC timing."/>
      </Field>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button className="w-full sm:w-auto" loading={busy} onClick={submit}><Rocket size={16}/> Publish</Button>
      </div>
    </div>
  </Modal>;
}

function IssueList({ title, tone, issues, subjectOf, onFix }) {
  if (!issues.length) return null;
  return <section role="region" aria-label={title} className="grid gap-2">
    <h3 className={`text-sm font-black ${tone === "red" ? "text-rose-800" : "text-amber-800"}`}>{title}</h3>
    {issues.map((issue, index) => {
      const { problem, why } = issueCopy(issue);
      const subject = subjectOf(issue);
      return <article key={`${issue.code}-${issue.entity_id || index}`} className={`flex flex-col gap-3 rounded-xl border bg-white p-3 sm:flex-row sm:items-start sm:justify-between ${tone === "red" ? "border-rose-200" : "border-amber-200"}`}>
        <div className="min-w-0">
          <strong className="block text-sm text-slate-950">{problem}</strong>
          {subject && <span className="mt-0.5 block text-xs font-bold text-blue-700">{subject}</span>}
          {why && <p className="mt-1 text-xs font-semibold leading-5 text-slate-600">{why}</p>}
        </div>
        <Button size="sm" variant="secondary" className="shrink-0" aria-label={`Fix: ${problem}`} onClick={() => onFix(issue)}><Wrench size={14}/> Fix</Button>
      </article>;
    })}
  </section>;
}

export function TemplateValidationPublishPanel({ summary, active, tasks = [], gates = [], onFix, onRefresh, onPublished }) {
  const [validation, setValidation] = useState(null);
  const [validationState, setValidationState] = useState("idle");
  const [validationError, setValidationError] = useState(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishState, setPublishState] = useState("idle");
  const [publishError, setPublishError] = useState(null);
  const runningRef = useRef(false);

  const stale = validation && validation.draft_revision !== summary.revision_token;
  const canPublish = Boolean(validation?.can_publish && !stale && validationState === "passed" && publishState !== "running");
  const blocking = useMemo(() => (validation?.issues || []).filter(issue => issue.blocking), [validation]);
  const warnings = useMemo(() => (validation?.issues || []).filter(issue => !issue.blocking), [validation]);

  const taskById = useMemo(() => new Map(tasks.map(task => [task.id, task])), [tasks]);
  const gateById = useMemo(() => new Map(gates.map(gate => [gate.id, gate])), [gates]);
  const subjectOf = issue => {
    const task = issue.entity_type === "task" && taskById.get(issue.entity_id);
    if (task) return `${task.code} · ${task.title}`;
    const gate = issue.entity_type === "gate" && gateById.get(issue.entity_id);
    return gate ? gate.approval_name : "";
  };

  async function validate() {
    if (runningRef.current) return;
    runningRef.current = true;
    setValidationState("running");
    setValidationError(null);
    setPublishError(null);
    try {
      const result = await templatesApi.validateVersion(summary.version_id);
      setValidation(result);
      setValidationState(result.can_publish ? "passed" : "failed");
    } catch (error) {
      setValidationError(error);
      setValidationState(error?.details?.detail?.code === "stale_template_version" ? "stale" : "failed");
    } finally {
      runningRef.current = false;
    }
  }

  // Check automatically when Review is opened, unless the last check is for this same revision.
  useEffect(() => {
    if (active && validation?.draft_revision !== summary.revision_token) validate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  async function publish(changeNote) {
    if (!canPublish || publishState === "running") return;
    setPublishState("running");
    setPublishError(null);
    try {
      const result = await templatesApi.publishVersion(summary.version_id, {
        revision_token: summary.revision_token,
        change_note: changeNote,
      });
      setPublishState("success");
      setPublishOpen(false);
      onPublished(result);
    } catch (error) {
      setPublishError(error);
      setPublishState(error?.details?.detail?.code === "stale_template_version" ? "stale" : "failed");
    }
  }

  return <section className="grid gap-4" data-testid="template-validation-publish">
    <div className="flex flex-col gap-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div><strong className="text-emerald-950">Review & publish</strong><p className="mt-1 text-xs font-semibold leading-5 text-emerald-800">Problems marked "must fix" stop publishing. Warnings are worth a look but don't.</p></div>
      <Button className="w-full sm:w-auto" variant="secondary" loading={validationState === "running"} onClick={validate}><RefreshCw size={16}/> Check again</Button>
    </div>

    {validationState === "running" && !validation && <Alert tone="info"><RefreshCw className="animate-spin" size={18}/><span>Checking the draft…</span></Alert>}
    {validationError && <Alert tone="danger" role="alert"><AlertCircle size={18}/><div><strong>The check could not run</strong><span className="mt-1 block">{responseMessage(validationError)}</span></div></Alert>}
    {stale && <Alert tone="warning" role="alert" className="items-center"><TriangleAlert size={18}/><div className="flex-1"><strong>The draft changed since this check</strong><span className="mt-1 block">Check again before publishing.</span></div><Button size="sm" variant="secondary" onClick={async () => { await onRefresh(); validate(); }}>Check again</Button></Alert>}

    {validation && !stale && (blocking.length
      ? <Alert tone="danger" role="status"><TriangleAlert size={19}/><div><strong>Fix {plural(blocking.length, "problem")} before publishing</strong>{warnings.length > 0 && <span className="mt-1 block">Also {plural(warnings.length, "thing")} worth checking.</span>}</div></Alert>
      : warnings.length
        ? <Alert tone="success" role="status"><CheckCircle2 size={19}/><div><strong>Ready to publish</strong><span className="mt-1 block">{plural(warnings.length, "thing")} worth checking first.</span></div></Alert>
        : <Alert tone="success" role="status"><CheckCircle2 size={19}/><strong>Ready to publish. No problems found.</strong></Alert>)}

    {validation && <>
      <IssueList title="Must fix before publishing" tone="red" issues={blocking} subjectOf={subjectOf} onFix={onFix}/>
      <IssueList title="Worth checking" tone="amber" issues={warnings} subjectOf={subjectOf} onFix={onFix}/>
    </>}

    {publishError && !publishOpen && <Alert tone="danger" role="alert" className="items-center"><AlertCircle size={18}/><div className="flex-1"><strong>{publishState === "stale" ? "The draft changed" : "Not published"}</strong><span className="mt-1 block">{responseMessage(publishError)}</span></div><Button size="sm" variant="secondary" onClick={onRefresh}>Refresh draft</Button></Alert>}

    <footer className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><div><strong className="text-sm text-slate-950">Publish</strong><p className="mt-1 text-xs font-semibold text-slate-500">Available once there is nothing left to fix.</p></div><Button className="w-full sm:w-auto" disabled={!canPublish} onClick={() => { setPublishError(null); setPublishOpen(true); }}><Rocket size={16}/> Publish</Button></div>
    </footer>

    {publishOpen && <PublishModal initialNote={summary.change_note} busy={publishState === "running"} error={publishError} onClose={() => { if (publishState !== "running") setPublishOpen(false); }} onPublish={publish}/>}
  </section>;
}
