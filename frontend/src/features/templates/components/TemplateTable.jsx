import { Archive, CheckCircle2, ChevronRight, Trash2 } from "lucide-react";
import { Button, Pill, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui";
import { formatTemplateDate, statusTone } from "./TemplateCard";

export function TemplateTable({ items, selectedTemplateVersionId, onSelect, onArchive, onDeleteDraft }) {
  return <div className="hidden overflow-hidden rounded-[22px] border border-slate-200 bg-white lg:block">
    <Table>
      <TableHead><TableRow className="hover:bg-transparent"><TableHeader>Template</TableHeader><TableHeader>Version</TableHeader><TableHeader>Status</TableHeader><TableHeader>Duration</TableHeader><TableHeader className="text-center">Tasks</TableHeader><TableHeader className="text-center">Dependencies</TableHeader><TableHeader className="text-center">Gates</TableHeader><TableHeader>Published</TableHeader><TableHeader className="text-right">Action</TableHeader></TableRow></TableHead>
      <TableBody>{items.map(item => {
        const selected = selectedTemplateVersionId === item.version_id;
        return <TableRow key={item.version_id} data-selected={selected || undefined} className={selected ? "bg-blue-50/70 hover:bg-blue-50/70" : ""}>
          <TableCell><div className="max-w-[280px]"><strong className="block truncate font-black text-slate-950">{item.template_name}</strong><span className="mt-1 block text-xs font-bold text-slate-500">{item.template_code}</span></div></TableCell>
          <TableCell><div className="flex items-center gap-2"><strong>v{item.version_no}</strong>{item.is_current_published && <span title="Current published version" className="text-emerald-600"><CheckCircle2 size={16}/></span>}</div></TableCell>
          <TableCell><Pill tone={statusTone(item.status)}>{item.status}</Pill></TableCell>
          <TableCell>{item.duration_days} days</TableCell><TableCell className="text-center font-black text-slate-900">{item.task_count}</TableCell><TableCell className="text-center font-black text-slate-900">{item.dependency_count}</TableCell><TableCell className="text-center font-black text-slate-900">{item.gate_count}</TableCell><TableCell className="whitespace-nowrap">{formatTemplateDate(item.published_at)}</TableCell>
          <TableCell className="text-right"><div className="inline-flex flex-wrap justify-end gap-1">
            <Button size="sm" variant="ghost" aria-pressed={selected} onClick={() => onSelect(item.version_id)}>View Details <ChevronRight size={15}/></Button>
            {onArchive && item.status === "published" && <Button size="sm" variant="ghost" aria-label={`Archive version ${item.version_no}`} onClick={() => onArchive(item)}><Archive size={15}/> Archive</Button>}
            {onDeleteDraft && item.status === "draft" && <Button size="sm" variant="ghost" aria-label={`Delete draft version ${item.version_no}`} onClick={() => onDeleteDraft(item)}><Trash2 size={15}/> Delete</Button>}
          </div></TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
  </div>;
}
