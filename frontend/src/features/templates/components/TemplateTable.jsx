import { Archive, ChevronRight, Trash2 } from "lucide-react";
import { Button, Pill, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui";
import { formatTemplateDate, statusTone } from "./TemplateCard";

// Whole rows open the version; the action buttons stop the click so they
// keep doing only their own job. The version new projects are created from
// is labelled in words, and archived history is quietened.
export function TemplateTable({ items, selectedTemplateVersionId, onSelect, onArchive, onDeleteDraft }) {
  return <div className="hidden overflow-hidden rounded-[20px] border border-line bg-white lg:block">
    <Table>
      <TableHead><TableRow className="hover:bg-transparent"><TableHeader>Template</TableHeader><TableHeader>Version</TableHeader><TableHeader>Status</TableHeader><TableHeader>Duration</TableHeader><TableHeader className="text-right">Tasks</TableHeader><TableHeader className="text-right">Dependencies</TableHeader><TableHeader className="text-right">Gates</TableHeader><TableHeader>Published</TableHeader><TableHeader className="text-right"><span className="sr-only">Actions</span></TableHeader></TableRow></TableHead>
      <TableBody>{items.map(item => {
        const selected = selectedTemplateVersionId === item.version_id;
        const archived = item.status === "archived";
        const stop = handler => event => { event.stopPropagation(); handler(); };
        return <TableRow key={item.version_id} data-selected={selected || undefined} onClick={() => onSelect(item.version_id)} className={`cursor-pointer ${selected ? "bg-blue-50/60 hover:bg-blue-50/60" : ""} ${archived ? "text-slate-500" : ""}`}>
          <TableCell><div className="max-w-[300px]"><strong className={`block truncate font-normal ${archived ? "text-slate-500" : "text-slate-950"}`}>{item.template_name}</strong><span className="mt-0.5 block text-xs text-slate-500">{item.template_code}</span></div></TableCell>
          <TableCell><div className="flex flex-wrap items-center gap-2"><span className="tabular-nums">v{item.version_no}</span>{item.is_current_published && <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-800" title="New projects are created from this version">In use</span>}</div></TableCell>
          <TableCell><Pill tone={statusTone(item.status)}>{item.status}</Pill></TableCell>
          <TableCell className="whitespace-nowrap">{item.duration_days} days</TableCell>
          <TableCell className="text-right tabular-nums text-slate-950">{item.task_count}</TableCell>
          <TableCell className="text-right tabular-nums text-slate-950">{item.dependency_count}</TableCell>
          <TableCell className="text-right tabular-nums text-slate-950">{item.gate_count}</TableCell>
          <TableCell className="whitespace-nowrap">{formatTemplateDate(item.published_at)}</TableCell>
          <TableCell className="text-right"><div className="inline-flex flex-wrap justify-end gap-1">
            {onArchive && item.status === "published" && <Button size="sm" variant="ghost" aria-label={`Archive version ${item.version_no}`} onClick={stop(() => onArchive(item))}><Archive size={15}/> Archive</Button>}
            {onDeleteDraft && item.status === "draft" && <Button size="sm" variant="ghost" className="hover:!bg-rose-50 hover:!text-rose-700" aria-label={`Delete draft version ${item.version_no}`} onClick={stop(() => onDeleteDraft(item))}><Trash2 size={15}/> Delete</Button>}
            <Button size="sm" variant="ghost" aria-pressed={selected} onClick={stop(() => onSelect(item.version_id))}>View Details <ChevronRight size={15}/></Button>
          </div></TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
  </div>;
}
