import { Copy, FilePlus2, Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { templatesApi } from "../../../api/templatesApi";
import { Alert, Button, Field, Input, Modal, Textarea } from "../../../components/ui";
import { TemplateChoiceGroup } from "./TemplateChoiceGroup";

const emptyCreate = {
  code: "",
  name: "",
  description: "",
  duration_days: "45",
  change_note: "Initial draft version created.",
};

function apiMessage(error, fallback) {
  const detail = error?.details?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && detail.message) return detail.message;
  if (typeof error?.message === "string" && error.message !== "[object Object]") return error.message;
  return fallback;
}

function suggestTemplateCode(name, duration) {
  const slug = String(name || "").trim().toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-|-$/g, "");
  return slug && Number(duration) > 0 ? `${slug}-${Number(duration)}` : "";
}

function validateCreate(values) {
  const errors = {};
  if (!values.code.trim()) errors.code = "Template code is required.";
  if (!values.name.trim()) errors.name = "Template name is required.";
  const duration = Number(values.duration_days);
  if (!Number.isInteger(duration) || duration <= 0) errors.duration_days = "Duration must be a positive whole number.";
  return errors;
}

function validateClone(values, cloneMode) {
  const errors = {};
  if (cloneMode === "template") {
    if (!values.name.trim()) errors.name = "Give the new template a name.";
    if (!values.code.trim()) errors.code = "Template code is required.";
  }
  if (!values.change_note.trim()) errors.change_note = "A change note is required for the new draft.";
  return errors;
}

function clonePayload(values, cloneMode) {
  const payload = { change_note: values.change_note.trim() };
  if (cloneMode === "template") {
    payload.new_template = { code: values.code.trim(), name: values.name.trim() };
    if (values.description.trim()) payload.new_template.description = values.description.trim();
  }
  return payload;
}


function requireNewDraftResponse(response, { isClone, sourceVersionId }) {
  const versionId = typeof response?.version_id === "string" ? response.version_id.trim() : "";
  if (!versionId || response?.status !== "draft") {
    throw new Error("The server did not confirm the new draft. Nothing was opened.");
  }
  if (isClone && versionId === sourceVersionId) {
    throw new Error("The server did not return a separate cloned draft. The source remains unchanged.");
  }
  if (isClone && response?.source_version_id && response.source_version_id !== sourceVersionId) {
    throw new Error("The clone response did not match the selected source version.");
  }
}

export function TemplateAuthoringModal({ mode, source, onClose, onSuccess }) {
  const isClone = mode === "clone";
  const [cloneMode, setCloneMode] = useState("version");
  const [values, setValues] = useState(emptyCreate);
  const [errors, setErrors] = useState({});
  const [requestError, setRequestError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);

  useEffect(() => {
    // A clone keeps the source's duration, so the suggested code uses it too.
    setValues(isClone ? { ...emptyCreate, duration_days: String(source?.duration_days ?? ""), change_note: "" } : { ...emptyCreate });
    setCloneMode("version");
    setErrors({});
    setRequestError("");
  }, [isClone, source?.version_id, source?.version_no, source?.duration_days]);

  function update(field, value) {
    setValues(current => {
      const next = { ...current, [field]: value };
      if (field === "name" || field === "duration_days") {
        const name = field === "name" ? value : current.name;
        const duration = field === "duration_days" ? value : current.duration_days;
        if (!current.code || current.code === suggestTemplateCode(current.name, current.duration_days)) next.code = suggestTemplateCode(name, duration);
      }
      return next;
    });
    setErrors(current => ({ ...current, [field]: "" }));
    setRequestError("");
  }

  async function submit(event) {
    event.preventDefault();
    const nextErrors = isClone ? validateClone(values, cloneMode) : validateCreate(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setSubmitting(true);
    setRequestError("");
    try {
      const response = isClone
        ? await templatesApi.cloneVersion(source.version_id, clonePayload(values, cloneMode))
        : await templatesApi.create({
            code: values.code.trim(),
            name: values.name.trim(),
            description: values.description.trim() || null,
            duration_days: Number(values.duration_days),
            change_note: values.change_note.trim() || null,
          });
      requireNewDraftResponse(response, { isClone, sourceVersionId: source?.version_id });
      await onSuccess(response);
    } catch (error) {
      setRequestError(apiMessage(
        error,
        isClone ? "The draft could not be cloned. Please try again." : "The template could not be created. Please try again.",
      ));
    } finally {
      setSubmitting(false);
    }
  }

  return <Modal
    title={isClone ? "Clone template" : "Create template"}
    subtitle={isClone
      ? "Start an editable draft from this version. The original is not changed."
      : "Name the template and start its first draft."}
    onClose={submitting ? undefined : onClose}
    className="sm:max-w-3xl"
  >
    <form className="grid gap-5" onSubmit={submit} data-testid="template-authoring-form">
      {isClone ? <section className="overflow-hidden rounded-[20px] border border-line bg-slate-50">
        <div className="flex items-start gap-3 border-b border-line bg-white p-4 sm:p-5">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-700"><Copy size={19}/></span>
          <div className="min-w-0">
            <span className="text-xs text-slate-500">Source remains unchanged</span>
            <h3 className="mt-0.5 truncate text-[17px] font-normal text-slate-950">{source.template_name}</h3>
            <p className="mt-0.5 text-xs text-slate-500">{source.template_code}, version {source.version_no}, {source.status}</p>
          </div>
        </div>
        <div className="grid gap-3 p-4 text-sm text-slate-600 sm:grid-cols-3 sm:p-5">
          <div><span className="block text-xs font-medium text-slate-500">Duration</span><strong className="mt-1 block text-slate-900">{source.duration_days} days</strong></div>
          <div><span className="block text-xs font-medium text-slate-500">Tasks</span><strong className="mt-1 block text-slate-900">{source.task_count}</strong></div>
          <div><span className="block text-xs font-medium text-slate-500">New version</span><strong className="mt-1 block text-slate-900">Separate draft</strong></div>
        </div>
      </section> : <section className="flex items-start gap-3 rounded-2xl border border-blue-100 bg-blue-50 p-4 text-blue-950">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-700 text-white"><FilePlus2 size={19}/></span>
        <div><h3 className="font-medium">Start with a clean draft</h3><p className="mt-1 text-sm leading-6 text-blue-800">No tasks are seeded automatically. The template identity and initial draft are created together.</p></div>
      </section>}

      {requestError && <Alert tone="danger"><div><strong className="block">{isClone ? "Draft could not be created" : "Template could not be created"}</strong><span className="mt-1 block font-medium">{requestError}</span></div></Alert>}

      {isClone && <TemplateChoiceGroup label="What do you want to create?" name="clone-mode" value={cloneMode} onChange={setCloneMode} options={[
        { value:"version", label:"New version", detail:`The next version of "${source.template_name}". Same name; projects use it once published.` },
        { value:"template", label:"New template", detail:`A separate template with its own name. "${source.template_name}" is not changed.` },
      ]}/>}

      {isClone && cloneMode === "template" && <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Template name" error={errors.name} className="sm:col-span-2">
          <Input aria-label="New template name" autoFocus value={values.name} onChange={event => update("name", event.target.value)} aria-invalid={Boolean(errors.name)} placeholder="Fitout - Retail"/>
        </Field>
        <Field label="Template code" error={errors.code} hint={!errors.code ? "Suggested from the name. Must be unique." : undefined}>
          <Input aria-label="New template code" value={values.code} onChange={event => update("code", event.target.value)} aria-invalid={Boolean(errors.code)}/>
        </Field>
        <Field label="Description (optional)" hint="Left empty, the original template's description is used.">
          <Input aria-label="New template description" value={values.description} onChange={event => update("description", event.target.value)}/>
        </Field>
      </div>}

      {!isClone && <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Template code" error={errors.code} hint={!errors.code ? "Suggested from name and duration; review before creation." : undefined}>
          <Input aria-label="Template code" autoFocus value={values.code} onChange={event => update("code", event.target.value)} aria-invalid={Boolean(errors.code)} placeholder="COMMERCIAL-INTERIOR-45"/>
        </Field>
        <Field label="Duration (days)" error={errors.duration_days}>
          <Input aria-label="Duration (days)" type="number" min="1" step="1" value={values.duration_days} onChange={event => update("duration_days", event.target.value)} aria-invalid={Boolean(errors.duration_days)}/>
        </Field>
        <Field label="Template name" error={errors.name} className="sm:col-span-2">
          <Input aria-label="Template name" value={values.name} onChange={event => update("name", event.target.value)} aria-invalid={Boolean(errors.name)} placeholder="Commercial Interior Delivery"/>
        </Field>
        <Field label="Description" className="sm:col-span-2" hint="Describe the intended project type and delivery scope.">
          <Textarea aria-label="Description" value={values.description} onChange={event => update("description", event.target.value)} placeholder="A delivery template for..."/>
        </Field>
      </div>}

      <Field
        label={isClone ? "Change note" : "Initial change note"}
        error={errors.change_note}
        hint={!errors.change_note ? (isClone ? "Required: a short note on what this draft changes." : "Optional context for the initial draft.") : undefined}
      >
        <Textarea
          aria-label={isClone ? "Change note" : "Initial change note"}
          autoFocus={isClone}
          value={values.change_note}
          onChange={event => update("change_note", event.target.value)}
          aria-invalid={Boolean(errors.change_note)}
          placeholder={isClone ? "Describe the planned revision..." : "Initial draft version created."}
        />
      </Field>

      {isClone && <div className="flex items-start gap-2 rounded-xl border border-orange-200 bg-orange-50 p-3 text-xs font-semibold leading-5 text-orange-900"><Info className="mt-0.5 shrink-0" size={16}/>All tasks, dependencies and prerequisite approvals are copied into the draft. Existing projects are not affected.</div>}

      <div className="sticky bottom-0 -mx-4 -mb-4 grid gap-2 border-t border-slate-100 bg-white/95 p-4 backdrop-blur sm:-mx-6 sm:-mb-6 sm:grid-cols-[auto_1fr] sm:p-6">
        <Button variant="secondary" onClick={onClose} disabled={submitting}>Cancel</Button>
        <Button type="submit" loading={submitting} className="sm:justify-self-end">
          {isClone ? <><Copy size={17}/> Create Draft</> : <><FilePlus2 size={17}/> Create Template</>}
        </Button>
      </div>
    </form>
  </Modal>;
}