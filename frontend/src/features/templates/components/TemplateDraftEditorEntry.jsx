import { AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookOpenCheck, CalendarDays, GitBranch, GripVertical, PencilLine, Plus, RefreshCw, Rocket, Save, ShieldAlert, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { templatesApi } from "../../../api/templatesApi";
import { Alert, Button, EmptyState, LoadingSpinner, Modal, Pill } from "../../../components/ui";
import { formatTemplateDate, statusTone } from "./TemplateCard";
import { formatPlannedDays } from "./TemplateTaskCard";
import { TemplateTaskEditorModal } from "./TemplateTaskEditorModal";
import { uploadChosenFiles } from "../../../components/ReferenceFilePicker";
import { TemplateDependencyEditorModal } from "./TemplateDependencyEditorModal";
import { dependencyTypeLabel } from "./TemplateDependencyCard";
import { TemplateGateEditorModal } from "./TemplateGateEditorModal";
import { TemplateValidationPublishPanel } from "./TemplateValidationPublishPanel";
import { ORG_ADMIN_ROLES } from "../../../utils/constants";
import { gateDueDateText, nextStructuredCode, TASK_KIND_LABELS, whenNeededFor } from "./templateAuthoringOptions";

function apiMessage(error) {
  const detail = error?.details?.detail;
  if (detail?.code === "stale_template_version") return "This draft changed in another session. Refresh before trying again.";
  if (typeof detail?.message === "string") return detail.message;
  if (typeof error?.message === "string") return error.message;
  return "The draft could not be updated.";
}

function linkErrorCopy(error) {
  const code = error?.details?.detail?.code;
  if (code === "template_dependency_cycle") return "that would make tasks wait for each other in a loop.";
  if (code === "template_dependency_exists") return "that link already exists.";
  return apiMessage(error);
}

async function loadEveryDependency(versionId) {
  const first = await templatesApi.listDependencies(versionId, { page:1, page_size:100 });
  if ((first.pagination?.total_pages || 1) <= 1) return first.items;
  const pages = await Promise.all(Array.from({ length:first.pagination.total_pages - 1 }, (_, index) =>
    templatesApi.listDependencies(versionId, { page:index + 2, page_size:100 })
  ));
  return [first, ...pages].flatMap(page => page.items);
}

async function loadEveryGate(versionId) {
  const first = await templatesApi.listGates(versionId, { page:1, page_size:100 });
  if ((first.pagination?.total_pages || 1) <= 1) return first.items;
  const pages = await Promise.all(Array.from({ length:first.pagination.total_pages - 1 }, (_, index) => templatesApi.listGates(versionId, { page:index + 2, page_size:100 })));
  return [first, ...pages].flatMap(page => page.items);
}

async function loadEveryTask(versionId) {
  const first = await templatesApi.listTasks(versionId, { page:1, page_size:100 });
  if ((first.pagination?.total_pages || 1) <= 1) return first.items;
  const pages = await Promise.all(Array.from({ length:first.pagination.total_pages - 1 }, (_, index) =>
    templatesApi.listTasks(versionId, { page:index + 2, page_size:100 })
  ));
  return [first, ...pages].flatMap(page => page.items);
}

// The pill on a task card: its class, or its older task type.
function taskTypePill(task) {
  if (task.task_kind === "approval_gate" || task.task_kind === "milestone") return { label: TASK_KIND_LABELS[task.task_kind], tone: "violet" };
  return task.task_class === "class_a" ? { label: "Class A", tone: "red" } : { label: "Standard", tone: "gray" };
}

function TaskRow({ task, index, count, disableMove, onEdit, onDelete, onMove }) {
  const typePill = taskTypePill(task);
  return <article data-testid={"draft-task-" + task.code} className="rounded-[20px] border border-line bg-white p-4">
    <div className="flex items-start gap-3">
      <span className="mt-0.5 hidden text-slate-300 sm:block"><GripVertical size={18}/></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="tabular-nums text-xs font-medium text-slate-600">{task.code}</span><Pill tone={typePill.tone}>{typePill.label}</Pill>{task.applicability === "conditional" && <Pill tone="orange">Only when it applies</Pill>}</div>
        <h3 className="mt-2 text-sm font-medium leading-5 text-slate-950">{task.title}</h3>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs font-semibold text-slate-500"><span>{formatPlannedDays(task)}</span><span>{task.phase || "No phase"}</span><span>{task.category || "No category"}</span></div>
      </div>
      <div className="hidden items-center gap-1 sm:flex">
        <Button size="icon" variant="ghost" aria-label={"Move " + task.code + " up"} disabled={disableMove || index===0} onClick={() => onMove(index,-1)}><ArrowUp size={16}/></Button>
        <Button size="icon" variant="ghost" aria-label={"Move " + task.code + " down"} disabled={disableMove || index===count-1} onClick={() => onMove(index,1)}><ArrowDown size={16}/></Button>
        <Button size="icon" variant="secondary" aria-label={"Edit " + task.code} onClick={() => onEdit(task)}><PencilLine size={16}/></Button>
        <Button size="icon" variant="danger" aria-label={"Delete " + task.code} onClick={() => onDelete(task)}><Trash2 size={16}/></Button>
      </div>
    </div>
    <div className="mt-4 grid grid-cols-4 gap-2 border-t border-slate-100 pt-3 sm:hidden">
      <Button size="sm" variant="ghost" aria-label={"Move " + task.code + " up"} disabled={disableMove || index===0} onClick={() => onMove(index,-1)}><ArrowUp size={15}/></Button>
      <Button size="sm" variant="ghost" aria-label={"Move " + task.code + " down"} disabled={disableMove || index===count-1} onClick={() => onMove(index,1)}><ArrowDown size={15}/></Button>
      <Button size="sm" variant="secondary" aria-label={"Edit " + task.code} onClick={() => onEdit(task)}><PencilLine size={15}/></Button>
      <Button size="sm" variant="danger" aria-label={"Delete " + task.code} onClick={() => onDelete(task)}><Trash2 size={15}/></Button>
    </div>
  </article>;
}

function DeleteTaskModal({ task, busy, error, onClose, onConfirm }) {
  const detail = error?.details?.detail;
  const dependencies = detail?.dependencies || [];
  const gates = detail?.gate_mappings || [];
  const referenced = detail?.code === "template_task_referenced";
  return <Modal title={"Delete " + task.code + "?"} subtitle="Draft task deletion is permanent." onClose={onClose} className="sm:max-w-lg">
    <div className="grid gap-5">
      {error && <Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>{referenced ? "Task is still referenced" : "Task was not deleted"}</strong><span className="mt-1 block">{referenced ? "Other tasks or approvals still point to it. Remove those links first." : apiMessage(error)}</span></div></Alert>}
      {referenced && <div className="grid gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-950">
        {dependencies.length > 0 && <div><strong>"Can't start until" links ({dependencies.length})</strong><ul className="mt-2 list-disc space-y-1 pl-5">{dependencies.map((item,index) => <li key={item.id || index}>{item.predecessor_code && item.successor_code ? item.predecessor_code + " → " + item.successor_code : (item.relationship || "dependency").replaceAll("_"," ") + " · related task " + item.other_task_id}</li>)}</ul></div>}
        {gates.length > 0 && <div><strong>Prerequisite approvals ({gates.length})</strong><ul className="mt-2 list-disc space-y-1 pl-5">{gates.map((item,index) => <li key={item.id || index}>{item.gate_code || item.code || "Mapped gate"}</li>)}</ul></div>}
      </div>}
      {!referenced && <p className="text-sm leading-6 text-slate-600">This will remove <strong className="text-slate-950">{task.title}</strong> from the draft. Published versions are not affected.</p>}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><Button variant="secondary" onClick={onClose}>Cancel</Button>{!referenced && <Button variant="danger" loading={busy} onClick={onConfirm}><Trash2 size={16}/> Delete task</Button>}</div>
    </div>
  </Modal>;
}


function DependencyRow({ dependency, onEdit, onDelete }) {
  return <article data-testid={"draft-dependency-" + dependency.id} className="rounded-[20px] border border-line bg-white p-4">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-slate-500">Link {dependency.sequence_no}</span><Pill tone="blue">{dependencyTypeLabel(dependency.dependency_type)}</Pill><Pill tone={dependency.blocking ? "red" : "gray"}>{dependency.blocking ? "Enforced" : "Advisory only"}</Pill></div>
        <div className="mt-4 grid grid-cols-[minmax(0,1fr)_32px_minmax(0,1fr)] items-center gap-2">
          <div><b className="tabular-nums text-xs text-slate-600">{dependency.predecessor?.code || "Missing"}</b><p className="mt-1 text-sm font-bold text-slate-950">{dependency.predecessor?.title || "Missing task"}</p></div>
          <span className="grid size-8 place-items-center rounded-full bg-slate-100 text-slate-500"><ArrowRight size={16}/></span>
          <div><b className="tabular-nums text-xs text-slate-600">{dependency.successor?.code || "Missing"}</b><p className="mt-1 text-sm font-bold text-slate-950">{dependency.successor?.title || "Missing task"}</p></div>
        </div>
        <p className="mt-4 border-t border-slate-100 pt-3 text-xs font-semibold leading-5 text-slate-600">{dependency.rule_text || "No note."}</p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:flex">
        <Button size="sm" variant="secondary" aria-label={"Edit dependency " + dependency.sequence_no} onClick={() => onEdit(dependency)}><PencilLine size={15}/> Edit</Button>
        <Button size="sm" variant="danger" aria-label={"Delete dependency " + dependency.sequence_no} onClick={() => onDelete(dependency)}><Trash2 size={15}/> Delete</Button>
      </div>
    </div>
  </article>;
}

function DeleteDependencyModal({ dependency, busy, error, onClose, onConfirm }) {
  return <Modal title="Delete this link?" subtitle="The two tasks stay; only the link between them is removed." onClose={onClose} className="sm:max-w-lg">
    <div className="grid gap-5">
      {error && <Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>Link was not deleted</strong><span className="mt-1 block">{apiMessage(error)}</span></div></Alert>}
      <p className="text-sm leading-6 text-slate-600"><strong className="text-slate-950">{dependency.predecessor?.code || "Task"}</strong> → <strong className="text-slate-950">{dependency.successor?.code || "Task"}</strong> will no longer be linked.</p>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="danger" loading={busy} onClick={onConfirm}><Trash2 size={16}/> Delete link</Button></div>
    </div>
  </Modal>;
}

function GateRow({ gate, onEdit, onDelete }) {
  const linkedCount = gate.mapping_classification === "exact" ? (gate.affected_tasks?.length || gate.task_ids?.length || 0) : 0;
  const imported = gate.mapping_classification === "broad_text";
  const dueDate = gateDueDateText(gate);
  // An older fixed-date rule with a date still gives a real due date.
  const noDueDate = whenNeededFor(gate.required_by_type) === "none" && !(gate.required_by_type === "date" && gate.required_by_value);
  const actions = size => <>
    <Button size={size} variant="secondary" aria-label={`Edit approval ${gate.code}`} onClick={() => onEdit(gate)}><PencilLine size={15}/>{size === "sm" && " Edit"}</Button>
    <Button size={size} variant="danger" aria-label={`Delete approval ${gate.code}`} onClick={() => onDelete(gate)}><Trash2 size={15}/>{size === "sm" && " Delete"}</Button>
  </>;
  return <article data-testid={`draft-gate-${gate.id}`} className="rounded-[20px] border border-line bg-white p-4">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-sm font-medium text-slate-950">{gate.approval_name}</h3>
        <p className="mt-1 text-xs font-semibold text-slate-500">{gate.external_party ? `Approved by ${gate.external_party}` : "Who approves is not set"}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {linkedCount > 0 ? <Pill tone="blue">Required before {linkedCount} task{linkedCount === 1 ? "" : "s"}</Pill> : <Pill tone="orange">Not linked to any task</Pill>}
          <Pill tone={noDueDate ? "orange" : "gray"}>{dueDate}</Pill>
        </div>
        {imported && <div className="mt-3 rounded-xl border border-orange-200 bg-orange-50 p-3 text-xs text-orange-900"><strong>Imported wording</strong><p className="mt-1 font-semibold">{gate.broad_mapping_text}</p></div>}
      </div>
      <div className="hidden gap-1 sm:flex">{actions("icon")}</div>
    </div>
    <div className="mt-4 grid grid-cols-2 gap-2 border-t border-slate-100 pt-3 sm:hidden">{actions("sm")}</div>
  </article>;
}
function DeleteGateModal({gate,busy,error,onClose,onConfirm}){return <Modal title={`Delete ${gate.code}?`} subtitle="Only this prerequisite approval is removed." onClose={onClose} className="sm:max-w-lg"><div className="grid gap-5">{error&&<Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>Approval was not deleted</strong><span className="mt-1 block">{apiMessage(error)}</span></div></Alert>}<Alert tone="warning"><ShieldAlert size={18}/><span>Tasks are not deleted or changed by this action.</span></Alert><p className="text-sm text-slate-600"><strong className="text-slate-950">{gate.approval_name}</strong></p><div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="danger" loading={busy} onClick={onConfirm}><Trash2 size={16}/> Delete approval</Button></div></div></Modal>}

export function TemplateDraftEditorEntry({ summary: initialSummary, user, onBack, onPublished }) {
  const [summary, setSummary] = useState(initialSummary);
  const [activeEditorTab, setActiveEditorTab] = useState("tasks");
  const [taskKindFilter, setTaskKindFilter] = useState("all");
  const [tasks, setTasks] = useState([]);
  const [dependencies, setDependencies] = useState([]);
  const [gates, setGates] = useState([]);
  const [savedOrder, setSavedOrder] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [mutationError, setMutationError] = useState(null);
  const [editorTask, setEditorTask] = useState(undefined);
  const [editorOpen, setEditorOpen] = useState(false);
  const [formDirty, setFormDirty] = useState(false);
  // Reference uploads/removals are draft changes of their own: keep the newest
  // revision for the next save, and reload the lists once the dialog closes.
  const referencesChangedRef = useRef(false);
  const [deleteTask, setDeleteTask] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [savingOrder, setSavingOrder] = useState(false);
  const [dependencyEditorOpen, setDependencyEditorOpen] = useState(false);
  const [editorDependency, setEditorDependency] = useState(undefined);
  const [deleteDependency, setDeleteDependency] = useState(null);
  const [dependencyDeleteError, setDependencyDeleteError] = useState(null);
  const [deletingDependency, setDeletingDependency] = useState(false);
  const [gateEditorOpen,setGateEditorOpen]=useState(false);
  const [editorGate,setEditorGate]=useState(undefined);
  const [deleteGate,setDeleteGate]=useState(null);
  const [gateDeleteError,setGateDeleteError]=useState(null);
  const [deletingGate,setDeletingGate]=useState(false);
  const refreshPromiseRef = useRef(null);
  const editable = ORG_ADMIN_ROLES.includes(user?.role) && summary?.status === "draft";
  const reorderDirty = useMemo(() => tasks.map(task => task.id).join("|") !== savedOrder.join("|"), [savedOrder,tasks]);
  const dirty = formDirty || reorderDirty;
  const gateTaskCount = useMemo(() => tasks.filter(task => task.task_kind === "approval_gate").length, [tasks]);
  const standardTaskCount = tasks.length - gateTaskCount;
  const visibleTasks = useMemo(() => taskKindFilter === "all" ? tasks
    : tasks.filter(task => (task.task_kind === "approval_gate") === (taskKindFilter === "approval_gate")), [tasks,taskKindFilter]);

  const refresh = useCallback(() => {
    if (refreshPromiseRef.current) return refreshPromiseRef.current;
    setLoading(true); setLoadError(null); setMutationError(null);
    const request = Promise.all([templatesApi.getVersion(initialSummary.version_id),loadEveryTask(initialSummary.version_id),loadEveryDependency(initialSummary.version_id),loadEveryGate(initialSummary.version_id)])
      .then(([nextSummary,nextTasks,nextDependencies,nextGates]) => {
        setSummary(nextSummary);
        const ordered=[...nextTasks].sort((a,b)=>a.sequence_no-b.sequence_no || a.code.localeCompare(b.code));
        setTasks(ordered); setSavedOrder(ordered.map(task=>task.id));
        setDependencies([...nextDependencies].sort((a,b)=>a.sequence_no-b.sequence_no || String(a.id).localeCompare(String(b.id))));
        setGates([...nextGates].sort((a,b)=>a.sequence_no-b.sequence_no || String(a.id).localeCompare(String(b.id))));
      })
      .catch(error => { setLoadError(error); })
      .finally(() => { setLoading(false); refreshPromiseRef.current=null; });
    refreshPromiseRef.current=request;
    return request;
  }, [initialSummary.version_id]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    setSummary(current => current?.version_id === initialSummary.version_id
      ? { ...current, ...initialSummary }
      : initialSummary);
  }, [
    initialSummary.version_id, initialSummary.revision_token,
    initialSummary.status, initialSummary.updated_at,
  ]);

  useEffect(() => {
    if (!dirty) return undefined;
    const warn = event => { event.preventDefault(); event.returnValue=""; };
    window.addEventListener("beforeunload",warn);
    return () => window.removeEventListener("beforeunload",warn);
  }, [dirty]);

  function leave() { if (!dirty || window.confirm("You have unsaved draft changes. Leave without saving?")) onBack(); }
  function move(index,direction) {
    const target=index+direction;
    if(target<0 || target>=tasks.length) return;
    setTasks(current => { const next=[...current]; [next[index],next[target]]=[next[target],next[index]]; return next; });
  }
  function openAdd(){setEditorTask(null);setEditorOpen(true);}
  function openEdit(task){setEditorTask(task);setEditorOpen(true);}

  // Saves the task, then its "can't start until" links, each call carrying the
  // revision the previous one returned. A link that fails after anything was
  // saved closes the dialog (its link list would be stale) and is reported on
  // the page; when nothing was saved, the error stays in the dialog.
  async function saveTask(payload,task,links={}) {
    const { taskChanged=true, addPredecessorIds=[], removeDependencyIds=[], pendingFiles=[] }=links;
    let token=summary.revision_token, saved=task, taskSaved=false, linkSaved=false, linkFailure=null;
    if(taskChanged){
      const response=task ? await templatesApi.updateTask(summary.version_id,task.id,payload) : await templatesApi.createTask(summary.version_id,payload);
      token=response.revision_token; saved=response.task||task; taskSaved=true;
      setSummary(current=>({...current,revision_token:token}));
    }
    const byId=new Map(tasks.map(item=>[item.id,item]));
    let nextSequence=Math.max(0,...dependencies.map(dependency=>dependency.sequence_no||0));
    try {
      for(const predecessorId of addPredecessorIds){
        nextSequence+=1;
        const response=await templatesApi.createDependency(summary.version_id,{
          predecessor_task_id:predecessorId, successor_task_id:saved.id, dependency_type:"finish_to_start", blocking:true,
          rule_text:`${saved.code} can't start until ${byId.get(predecessorId)?.code} is finished.`, sequence_no:nextSequence, revision_token:token,
        });
        token=response.revision_token; linkSaved=true;
      }
      for(const dependencyId of removeDependencyIds){
        const response=await templatesApi.deleteDependency(summary.version_id,dependencyId,token);
        token=response.revision_token; linkSaved=true;
      }
    } catch(error) {
      if(!taskSaved&&!linkSaved) throw error;
      linkFailure={message:taskSaved
        ? `The task was saved, but its "can't start until" links were not all saved: ${linkErrorCopy(error)}`
        : `Some changes were saved, but not all "can't start until" links were: ${linkErrorCopy(error)}`};
    } finally {
      setSummary(current=>({...current,revision_token:token}));
    }
    // Reference files chosen while creating the task, uploaded as part of the
    // same Save. Each upload is a draft change, so the token is chained.
    if(saved&&pendingFiles.length){
      const failed=await uploadChosenFiles(pendingFiles, async item=>{
        const response=await templatesApi.addReferenceFile(summary.version_id,"tasks",saved.id,{file:item.file,description:item.description.trim(),revisionToken:token});
        token=response.revision_token;
      });
      setSummary(current=>({...current,revision_token:token}));
      if(failed.length){
        const message=`The task was saved, but these reference files weren't uploaded: ${failed.join(", ")}. Open the task to add them again.`;
        linkFailure=linkFailure?{message:`${linkFailure.message} ${message}`}:{message};
      }
    }
    setEditorOpen(false);setFormDirty(false);
    await refresh();
    // After the refresh, which clears page errors.
    if(linkFailure) setMutationError(linkFailure);
  }

  async function confirmDelete() {
    if(deleting) return;
    setDeleting(true);setDeleteError(null);
    try {
      const response=await templatesApi.deleteTask(summary.version_id,deleteTask.id,summary.revision_token);
      setSummary(current=>({...current,revision_token:response.revision_token}));
      setDeleteTask(null);
      await refresh();
    } catch(error){setDeleteError(error);}
    finally{setDeleting(false);}
  }

  async function saveOrder() {
    if(!reorderDirty || savingOrder) return;
    setSavingOrder(true);setMutationError(null);
    try {
      const response=await templatesApi.reorderTasks(summary.version_id,{revision_token:summary.revision_token,items:tasks.map((task,index)=>({task_id:task.id,sequence_no:index+1}))});
      setSummary(current=>({...current,revision_token:response.revision_token}));
      setSavedOrder(tasks.map(task=>task.id));
      await refresh();
    } catch(error){setMutationError(error);}
    finally{setSavingOrder(false);}
  }

  function openAddDependency(){setEditorDependency(null);setDependencyEditorOpen(true);}
  function openEditDependency(dependency){setEditorDependency(dependency);setDependencyEditorOpen(true);}

  async function saveDependency(payload, dependency) {
    const response = dependency
      ? await templatesApi.updateDependency(summary.version_id, dependency.id, payload)
      : await templatesApi.createDependency(summary.version_id, payload);
    setSummary(current => ({ ...current, revision_token:response.revision_token }));
    setDependencyEditorOpen(false); setFormDirty(false);
    await refresh();
  }

  async function confirmDependencyDelete() {
    if (deletingDependency) return;
    setDeletingDependency(true); setDependencyDeleteError(null);
    try {
      const response = await templatesApi.deleteDependency(summary.version_id, deleteDependency.id, summary.revision_token);
      setSummary(current => ({ ...current, revision_token:response.revision_token }));
      setDeleteDependency(null);
      await refresh();
    } catch (error) { setDependencyDeleteError(error); }
    finally { setDeletingDependency(false); }
  }


  // Review "Fix": open the task or approval an issue is about, else its tab.
  function fixIssue(issue){
    const task=issue.entity_type==="task"&&tasks.find(item=>item.id===issue.entity_id);
    if(task){setActiveEditorTab("tasks");openEdit(task);return;}
    const gate=issue.entity_type==="gate"&&gates.find(item=>item.id===issue.entity_id);
    if(gate){setActiveEditorTab("gates");openEditGate(gate);return;}
    setActiveEditorTab(issue.group==="dependencies"?"dependencies":issue.group==="gates"||issue.group==="mappings"?"gates":"tasks");
  }

  function referencesChanged(token){referencesChangedRef.current=true;setSummary(current=>({...current,revision_token:token}));}
  function reloadAfterReferenceChanges(){if(referencesChangedRef.current){referencesChangedRef.current=false;refresh();}}

  function openAddGate(){setEditorGate(null);setGateEditorOpen(true);}
  function openEditGate(gate){setEditorGate(gate);setGateEditorOpen(true);}
  async function saveGate(payload,gate,initialJson){
    if(!gate){const response=await templatesApi.createGate(summary.version_id,payload);setSummary(c=>({...c,revision_token:response.revision_token}));}
    else {
      const initial=JSON.parse(initialJson); const metadataKeys=["code","approval_name","description","external_party","required_by_type","required_by_value","impact","evidence_instructions","sequence_no"];
      const changes={revision_token:summary.revision_token}; metadataKeys.forEach(key=>{const old=initial[key]??null,newValue=payload[key]??null;if(old!==newValue)changes[key]=newValue;});
      let token=summary.revision_token;
      if(Object.keys(changes).length>1){const updated=await templatesApi.updateGate(summary.version_id,gate.id,changes);token=updated.revision_token;}
      const oldIds=[...(initial.task_ids||[])].map(String).sort(); const newIds=[...(payload.task_ids||[])].map(String).sort();
      const mappingChanged=initial.mapping_classification!==payload.mapping_classification||initial.broad_mapping_text!==payload.broad_mapping_text||JSON.stringify(oldIds)!==JSON.stringify(newIds);
      if(mappingChanged){const mapped=await templatesApi.configureGateMappings(summary.version_id,gate.id,{mapping_classification:payload.mapping_classification,broad_mapping_text:payload.broad_mapping_text,task_ids:payload.task_ids,revision_token:token});token=mapped.revision_token;}
      setSummary(c=>({...c,revision_token:token}));
    }
    setGateEditorOpen(false);setFormDirty(false);await refresh();
  }
  async function confirmGateDelete(){if(deletingGate)return;setDeletingGate(true);setGateDeleteError(null);try{const response=await templatesApi.deleteGate(summary.version_id,deleteGate.id,summary.revision_token);setSummary(c=>({...c,revision_token:response.revision_token}));setDeleteGate(null);await refresh();}catch(error){setGateDeleteError(error)}finally{setDeletingGate(false)}}


  if(!editable) return <Alert tone="danger"><AlertTriangle size={18}/><div><strong>Draft authoring is unavailable</strong><span className="mt-1 block">Only Super Admin or Admin can edit a draft template version.</span></div></Alert>;

  return <section className="grid gap-5" data-testid="template-draft-editor">
    <Button variant="ghost" size="sm" className="-ml-2 w-fit" onClick={leave}><ArrowLeft size={16}/> Back to draft details</Button>
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 rounded-[20px] border border-line bg-white p-5">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="min-w-0 text-[24px] font-normal leading-tight tracking-[-0.02em] text-slate-950">{summary.template_name}</h2>
          <Pill tone={statusTone(summary.status)}>{summary.status}</Pill>
        </div>
        <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-slate-500">
          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{summary.template_code}</span>
          <span>Version {summary.version_no}, draft you can edit</span>
          <span>{summary.duration_days} days planned</span>
          <span>Last updated {summary.updated_at ? formatTemplateDate(summary.updated_at) : "not available"}</span>
        </p>
      </div>
    </header>

    <nav aria-label="Draft editor sections" className="grid grid-cols-1 gap-1 rounded-[20px] border border-line bg-white p-1.5 sm:grid-cols-2 lg:grid-cols-4">
      <Button variant={activeEditorTab === "tasks" ? "primary" : "ghost"} onClick={() => setActiveEditorTab("tasks")}><BookOpenCheck size={17}/> Tasks ({tasks.length})</Button>
      <Button variant={activeEditorTab === "dependencies" ? "primary" : "ghost"} onClick={() => setActiveEditorTab("dependencies")}><GitBranch size={17}/> Dependencies · advanced ({dependencies.length})</Button>
      <Button variant={activeEditorTab === "gates" ? "primary" : "ghost"} onClick={() => setActiveEditorTab("gates")}><ShieldAlert size={17}/> Prerequisite approvals ({gates.length})</Button>
      <Button variant={activeEditorTab === "validation" ? "primary" : "ghost"} onClick={() => setActiveEditorTab("validation")}><Rocket size={17}/> Review & publish</Button>
    </nav>

    {activeEditorTab === "tasks" ? <>
      <div className="flex flex-col gap-3 rounded-2xl border border-orange-200 bg-orange-50 p-4 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-3"><BookOpenCheck className="mt-0.5 shrink-0 text-orange-700" size={19}/><div><strong className="text-orange-950">Tasks</strong><p className="mt-1 text-xs font-semibold leading-5 text-orange-800">Add, edit and order the tasks. Use the arrows to change the order, then save it.</p></div></div><Button className="w-full sm:w-auto" onClick={openAdd}><Plus size={17}/> Add task</Button></div>
      {mutationError && <Alert tone="danger" role="alert" className="items-center"><div><strong>Draft update failed</strong><span className="mt-1 block">{apiMessage(mutationError)}</span></div><Button variant="secondary" size="sm" onClick={refresh}><RefreshCw size={15}/> Refresh draft</Button></Alert>}
      {/* Approval tasks are an older task type; the filter only appears while one exists. */}
      {gateTaskCount > 0 && <div className="grid grid-cols-1 gap-2 rounded-[20px] border border-line bg-white p-2 sm:grid-cols-3" role="tablist" aria-label="Filter tasks by type">
        <Button variant={taskKindFilter === "all" ? "primary" : "ghost"} size="sm" onClick={() => setTaskKindFilter("all")}>All ({tasks.length})</Button>
        <Button variant={taskKindFilter === "work" ? "primary" : "ghost"} size="sm" onClick={() => setTaskKindFilter("work")}>Site work ({standardTaskCount})</Button>
        <Button variant={taskKindFilter === "approval_gate" ? "primary" : "ghost"} size="sm" onClick={() => setTaskKindFilter("approval_gate")}>Approval tasks ({gateTaskCount})</Button>
      </div>}
      {gateTaskCount > 0 && taskKindFilter !== "all" && <p className="text-xs font-semibold text-slate-500">Switch to "All" to change the task order.</p>}
      {loading ? <div className="grid min-h-64 place-items-center rounded-[20px] border border-line bg-white"><LoadingSpinner label="Loading draft tasks..."/></div> : loadError ? <Alert tone="danger" className="items-center"><div><strong>Draft tasks unavailable</strong><span className="mt-1 block">{apiMessage(loadError)}</span></div><Button variant="secondary" size="sm" onClick={refresh}><RefreshCw size={15}/> Retry</Button></Alert> : tasks.length===0 ? <EmptyState className="min-h-64 bg-white" title="This draft has no tasks" description="Add the first task." action={<Button onClick={openAdd}><Plus size={16}/> Add first task</Button>}/> : visibleTasks.length===0 ? <EmptyState className="min-h-64 bg-white" title="No tasks of this kind yet" description="Switch tabs or add a task and set its kind."/> : <div className="grid gap-3">{visibleTasks.map(task=>{const index=tasks.indexOf(task);return <TaskRow key={task.id} task={task} index={index} count={tasks.length} disableMove={taskKindFilter !== "all"} onEdit={openEdit} onDelete={task=>{setDeleteTask(task);setDeleteError(null);}} onMove={move}/>;})}</div>}
      {!loading && tasks.length>0 && <footer className="sticky bottom-3 z-10 flex flex-col gap-3 rounded-[20px] border border-line bg-white/95 p-3 shadow-[0_18px_50px_rgba(15,23,42,.16)] backdrop-blur sm:flex-row sm:items-center sm:justify-between"><div className="px-1"><strong className="text-sm text-slate-950">{tasks.length} draft task{tasks.length===1?"":"s"}</strong><p className="mt-0.5 text-xs font-semibold text-slate-500">{reorderDirty ? "Order changed — save to create a new revision." : "Sequence is saved."}</p></div><div className="grid grid-cols-2 gap-2"><Button variant="secondary" disabled={!reorderDirty||savingOrder} onClick={()=>{const restored=savedOrder.map(id=>tasks.find(task=>task.id===id)).filter(Boolean);setTasks(restored);}}>Cancel order</Button><Button loading={savingOrder} disabled={!reorderDirty} onClick={saveOrder}><Save size={16}/> Save order</Button></div></footer>}
    </> : activeEditorTab === "dependencies" ? <>
      <div className="flex flex-col gap-3 rounded-2xl border border-cyan-200 bg-slate-100 p-4 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-3"><GitBranch className="mt-0.5 shrink-0 text-slate-500" size={19}/><div><strong className="text-cyan-950">Dependencies (advanced)</strong><p className="mt-1 text-xs font-semibold leading-5 text-cyan-800">Every link between tasks. Most are easier to set with "Can't start until" in each task. Use this list for start-together or advisory links.</p></div></div><Button className="w-full sm:w-auto" onClick={openAddDependency} disabled={tasks.length < 2}><Plus size={17}/> Add link</Button></div>
      {loading ? <div className="grid min-h-64 place-items-center rounded-[20px] border border-line bg-white"><LoadingSpinner label="Loading draft dependencies..."/></div> : loadError ? <Alert tone="danger" className="items-center"><div><strong>Draft dependencies unavailable</strong><span className="mt-1 block">{apiMessage(loadError)}</span></div><Button variant="secondary" size="sm" onClick={refresh}><RefreshCw size={15}/> Retry</Button></Alert> : dependencies.length===0 ? <EmptyState className="min-h-64 bg-white" title="No links between tasks yet" description="Tasks can start on their planned day." action={tasks.length >= 2 ? <Button onClick={openAddDependency}><Plus size={16}/> Add first link</Button> : null}/> : <div className="grid gap-3">{dependencies.map(dependency => <DependencyRow key={dependency.id} dependency={dependency} onEdit={openEditDependency} onDelete={item=>{setDeleteDependency(item);setDependencyDeleteError(null);}}/>)}</div>}
       </> : activeEditorTab === "gates" ? <>
      <div className="flex flex-col gap-3 rounded-2xl border border-violet-200 bg-violet-50 p-4 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-3"><ShieldAlert className="mt-0.5 shrink-0 text-violet-700" size={19}/><div><strong className="text-violet-950">Prerequisite approvals</strong><p className="mt-1 text-xs font-semibold leading-5 text-violet-800">Outside approvals, such as a Fire NOC, that related work needs first. Link each one to the tasks it is required before.</p></div></div><Button className="w-full sm:w-auto" onClick={openAddGate}><Plus size={17}/> Add approval</Button></div>
      {loading ? <div className="grid min-h-64 place-items-center rounded-[20px] border border-line bg-white"><LoadingSpinner label="Loading prerequisite approvals..."/></div> : loadError ? <Alert tone="danger"><strong>Prerequisite approvals unavailable</strong><span>{apiMessage(loadError)}</span></Alert> : gates.length===0 ? <EmptyState className="min-h-64 bg-white" title="No prerequisite approvals yet" description="Add an outside approval that related work needs first." action={<Button onClick={openAddGate}><Plus size={16}/> Add first approval</Button>}/> : <div className="grid gap-3">{gates.map(gate=><GateRow key={gate.id} gate={gate} onEdit={openEditGate} onDelete={item=>{setDeleteGate(item);setGateDeleteError(null)}}/>)}</div>}
    </> : null}
    <div className={activeEditorTab === "validation" ? "block" : "hidden"} aria-hidden={activeEditorTab !== "validation"}><TemplateValidationPublishPanel summary={summary} active={activeEditorTab === "validation"} tasks={tasks} gates={gates} onFix={fixIssue} onRefresh={refresh} onPublished={onPublished}/></div>

    {editorOpen && <TemplateTaskEditorModal task={editorTask} tasks={tasks} dependencies={dependencies} versionId={summary.version_id} durationDays={summary.duration_days} revisionToken={summary.revision_token} nextSequence={tasks.length+1} suggestedCode={nextStructuredCode(tasks, "T")} onClose={()=>{setEditorOpen(false);setFormDirty(false);reloadAfterReferenceChanges();}} onSaved={saveTask} onDirtyChange={setFormDirty} onReferencesChanged={referencesChanged}/>}
    {deleteTask && <DeleteTaskModal task={deleteTask} busy={deleting} error={deleteError} onClose={()=>{setDeleteTask(null);setDeleteError(null);}} onConfirm={confirmDelete}/>}
    {dependencyEditorOpen && <TemplateDependencyEditorModal dependency={editorDependency} tasks={tasks} revisionToken={summary.revision_token} nextSequence={dependencies.length+1} onClose={()=>{setDependencyEditorOpen(false);setFormDirty(false);}} onSaved={saveDependency} onDirtyChange={setFormDirty}/>} 
    {deleteDependency && <DeleteDependencyModal dependency={deleteDependency} busy={deletingDependency} error={dependencyDeleteError} onClose={()=>{setDeleteDependency(null);setDependencyDeleteError(null);}} onConfirm={confirmDependencyDelete}/>} 
    {gateEditorOpen && <TemplateGateEditorModal gate={editorGate} tasks={tasks} versionId={summary.version_id} durationDays={summary.duration_days} revisionToken={summary.revision_token} nextSequence={gates.length+1} suggestedCode={nextStructuredCode(gates, "E")} onClose={()=>{setGateEditorOpen(false);setFormDirty(false);reloadAfterReferenceChanges();}} onSaved={saveGate} onDirtyChange={setFormDirty} onReferencesChanged={referencesChanged}/>} 
    {deleteGate && <DeleteGateModal gate={deleteGate} busy={deletingGate} error={gateDeleteError} onClose={()=>{setDeleteGate(null);setGateDeleteError(null)}} onConfirm={confirmGateDelete}/>} 
  </section>;
}
