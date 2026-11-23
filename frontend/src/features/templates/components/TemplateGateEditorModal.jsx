import { AlertTriangle, Info, Save, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Field, Input, Modal, Select, Textarea } from "../../../components/ui";
import { EXTERNAL_PARTIES, WHEN_NEEDED_OPTIONS, whenNeededFor } from "./templateAuthoringOptions";
import { TemplateChoiceGroup, TemplateEditorSection as Section } from "./TemplateChoiceGroup";
import { TemplateReferenceFiles } from "./TemplateReferenceFiles";

// The saved shape the parent diffs against, so an untouched field - including
// an imported rule or wording - is never re-sent or converted.
function savedShape(gate, nextSequence, suggestedCode) {
  if (!gate) return { code:suggestedCode ?? "", approval_name:"", description:null, external_party:null, required_by_type:"before_linked_tasks", required_by_value:null, impact:null, evidence_instructions:null, sequence_no:nextSequence ?? null, mapping_classification:"unmapped", broad_mapping_text:null, task_ids:[] };
  return { code:gate.code || "", approval_name:gate.approval_name || "", description:gate.description || null, external_party:gate.external_party || null, required_by_type:gate.required_by_type ?? null, required_by_value:gate.required_by_value ?? null, impact:gate.impact || null, evidence_instructions:gate.evidence_instructions || null, sequence_no:gate.sequence_no ?? nextSequence ?? null, mapping_classification:gate.mapping_classification || "unmapped", broad_mapping_text:gate.broad_mapping_text ?? null, task_ids:(gate.task_ids || gate.affected_tasks?.map(task => task.id) || []).map(String) };
}

function asForm(saved) {
  return { code:saved.code, approval_name:saved.approval_name, description:saved.description || "", external_party:saved.external_party || "", impact:saved.impact || "", evidence_instructions:saved.evidence_instructions || "", when:whenNeededFor(saved.required_by_type), day:saved.required_by_type === "project_day" ? saved.required_by_value || "" : "", task_ids:saved.task_ids };
}

function message(error){const d=error?.details?.detail;if(d?.code==="stale_template_version")return"This draft changed in another session. Refresh before retrying.";return d?.message||error?.message||"The approval could not be saved.";}

export function TemplateGateEditorModal({ gate, tasks, versionId, durationDays, revisionToken, nextSequence, suggestedCode, onClose, onSaved, onDirtyChange, onReferencesChanged }) {
  const saved=useMemo(()=>savedShape(gate,nextSequence,suggestedCode),[gate,nextSequence,suggestedCode]);
  const [form,setForm]=useState(()=>asForm(saved));const [errors,setErrors]=useState({});const [requestError,setRequestError]=useState("");const [saving,setSaving]=useState(false);const [taskFilter,setTaskFilter]=useState("");
  const dirty=JSON.stringify(form)!==JSON.stringify(asForm(saved));
  const importedRule=Boolean(gate&&saved.required_by_type&&whenNeededFor(saved.required_by_type)==="none");
  const importedWording=saved.mapping_classification==="broad_text";
  const visibleTasks=useMemo(()=>{const term=taskFilter.trim().toLowerCase();return term?tasks.filter(task=>`${task.code} ${task.title}`.toLowerCase().includes(term)):tasks;},[taskFilter,tasks]);
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false)},[dirty,onDirtyChange]);
  function change(name,value){setForm(current=>({...current,[name]:value}));setErrors(current=>({...current,[name]:""}));setRequestError("");}
  function toggleTask(id){change("task_ids",form.task_ids.includes(id)?form.task_ids.filter(x=>x!==id):[...form.task_ids,id]);setErrors(current=>({...current,when:""}));}
  function validate(){const e={};if(!form.code.trim())e.code="Code is required.";if(!form.approval_name.trim())e.approval_name="Give the approval a name.";if(form.when==="before_tasks"&&!form.task_ids.length)e.when="Pick the tasks it's required before, or choose another option.";const day=Number(form.day);if(form.when==="project_day"&&(!Number.isInteger(day)||day<1||day>durationDays))e.day=`Use Day 1-${durationDays}.`;setErrors(e);return!Object.keys(e).length;}
  function rule(){
    if(form.when==="before_tasks")return{required_by_type:"before_linked_tasks",required_by_value:null};
    if(form.when==="project_day")return{required_by_type:"project_day",required_by_value:String(Number(form.day))};
    // "No due date" keeps an imported rule exactly as it was; nothing is converted.
    return importedRule?{required_by_type:saved.required_by_type,required_by_value:saved.required_by_value}:{required_by_type:null,required_by_value:null};
  }
  function links(){
    if(form.task_ids.length)return{mapping_classification:"exact",broad_mapping_text:null,task_ids:form.task_ids};
    // Imported wording stays until tasks are linked.
    if(importedWording)return{mapping_classification:"broad_text",broad_mapping_text:saved.broad_mapping_text,task_ids:[]};
    return{mapping_classification:"unmapped",broad_mapping_text:null,task_ids:[]};
  }
  async function submit(event){event.preventDefault();if(saving||!validate())return;setSaving(true);setRequestError("");try{await onSaved({code:form.code.trim(),approval_name:form.approval_name.trim(),description:form.description.trim()||null,external_party:form.external_party||null,...rule(),impact:form.impact.trim()||null,evidence_instructions:form.evidence_instructions.trim()||null,sequence_no:saved.sequence_no,...links(),revision_token:revisionToken},gate,JSON.stringify(saved))}catch(error){setRequestError(message(error));setSaving(false)}}
  function close(){if(!dirty||window.confirm("Discard unsaved approval changes?"))onClose();}
  return <Modal title={gate?"Edit prerequisite approval":"Add prerequisite approval"} subtitle="An outside approval the related work needs first. Changes apply to projects created after this version is published." onClose={close} className="sm:max-w-4xl"><form className="grid gap-5" onSubmit={submit} noValidate>
    {requestError&&<Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>Approval was not saved</strong><span className="mt-1 block">{requestError}</span></div></Alert>}
    <Section title="What">
      <Field label="Approval name" error={errors.approval_name}><Input aria-label="Approval name" value={form.approval_name} onChange={e=>change("approval_name",e.target.value)} placeholder="Fire NOC"/></Field>
      <Field label="Description"><Textarea aria-label="Approval description" value={form.description} onChange={e=>change("description",e.target.value)}/></Field>
      <Field label="Who approves"><Select aria-label="Who approves" value={form.external_party} onChange={e=>change("external_party",e.target.value)}><option value="">Select who approves</option>{EXTERNAL_PARTIES.map(value=><option key={value}>{value}</option>)}</Select></Field>
    </Section>
    <Section title="When">
      <TemplateChoiceGroup label="When is it needed?" name="approval-when" value={form.when} options={WHEN_NEEDED_OPTIONS} columns={1} onChange={value=>{change("when",value);setErrors(current=>({...current,day:""}));}}/>
      {errors.when&&<p className="text-sm font-bold text-rose-600" role="alert">{errors.when}</p>}
      {form.when==="project_day"&&<Field label="Needed by day" error={errors.day}><Input aria-label="Needed by day" type="number" min="1" max={durationDays} value={form.day} onChange={e=>change("day",e.target.value)}/></Field>}
      {importedRule&&form.when==="none"&&<Alert tone="info"><Info size={18}/><div><strong>{saved.required_by_type==="date"?"Older fixed date kept":"Imported wording kept, no due date"}</strong><span className="mt-1 block">{saved.required_by_value}</span></div></Alert>}
    </Section>
    <Section title="Required before">
      <p className="text-sm font-bold text-slate-700">This approval is required before these tasks</p>
      {importedWording&&<div className="rounded-xl border border-orange-200 bg-orange-50 p-3 text-xs text-orange-900"><strong>Imported wording</strong><p className="mt-1 font-semibold">{saved.broad_mapping_text}</p>{form.task_ids.length>0?<p className="mt-2 font-bold">Saving replaces the imported wording with the tasks you picked.</p>:<p className="mt-1">Not linked to specific tasks. Pick tasks below to link them.</p>}</div>}
      {!form.task_ids.length&&!importedWording&&<p className="text-xs font-semibold text-slate-500">Not linked to any task yet, so no task will list it as a prerequisite.</p>}
      {tasks.length>8&&<label className="relative"><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16}/><Input aria-label="Find a task" value={taskFilter} onChange={e=>setTaskFilter(e.target.value)} className="pl-9" placeholder="Find a task"/></label>}
      <div className="grid max-h-72 gap-2 overflow-auto sm:grid-cols-2">{visibleTasks.map(task=><label key={task.id} className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm"><input aria-label={`Required before ${task.code}`} type="checkbox" checked={form.task_ids.includes(String(task.id))} onChange={()=>toggleTask(String(task.id))} className="mt-0.5 size-4 accent-blue-700"/><span><b className="tabular-nums text-xs text-slate-600">{task.code}</b><span className="block text-xs font-semibold text-slate-700">{task.title}</span></span></label>)}</div>
      {form.task_ids.length>0&&<p className="text-xs font-bold text-slate-600">{form.task_ids.length} task{form.task_ids.length===1?"":"s"} selected</p>}
    </Section>
    <Section title="Proof and reference material">
      <Field label="What proof is needed?" hint="Guidance for whoever handles the approval, for example a stamped NOC copy. It is guidance only and is never required to submit."><Textarea aria-label="What proof is needed?" value={form.evidence_instructions} maxLength={2000} onChange={e=>change("evidence_instructions",e.target.value)}/></Field>
      {gate
        ? <TemplateReferenceFiles versionId={versionId} kind="gates" ownerId={gate.id} files={gate.reference_files} revisionToken={revisionToken} onChanged={onReferencesChanged}/>
        : <p className="text-sm font-semibold text-slate-500">Save the approval first, then add reference files such as an application form.</p>}
    </Section>
    <details className="rounded-[20px] border border-line bg-white p-4 sm:p-5">
      <summary className="cursor-pointer text-sm font-medium text-slate-700">Advanced</summary>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Approval code" error={errors.code} hint="Filled in automatically. Must be unique in this template."><Input aria-label="Approval code" value={form.code} onChange={e=>change("code",e.target.value)}/></Field>
        <Field label="What's affected if it's late" hint="Shown to the team with the approval."><Textarea aria-label="What's affected if it's late" value={form.impact} onChange={e=>change("impact",e.target.value)}/></Field>
      </div>
    </details>
    <footer className="sticky -bottom-4 -mx-4 flex flex-col-reverse gap-2 border-t border-slate-100 bg-white/95 px-4 py-4 backdrop-blur sm:-bottom-6 sm:-mx-6 sm:flex-row sm:justify-end sm:px-6"><Button variant="secondary" className="w-full sm:w-auto" onClick={close}>Cancel</Button><Button type="submit" loading={saving} className="w-full sm:w-auto"><Save size={17}/>{gate?"Save approval":"Add approval"}</Button></footer>
  </form></Modal>;
}
