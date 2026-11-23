import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Pill, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui";
import { formatPlannedDays } from "./TemplateTaskCard";

export function TemplateTaskTable({ tasks }) {
  return <div className="hidden overflow-hidden rounded-[20px] border border-line bg-white lg:block">
    <Table>
      <TableHead><TableRow className="hover:bg-transparent"><TableHeader>Code</TableHeader><TableHeader>Task</TableHeader><TableHeader>Phase</TableHeader><TableHeader>Category</TableHeader><TableHeader>Planned days</TableHeader><TableHeader>Applicability</TableHeader></TableRow></TableHead>
      <TableBody>{tasks.map(task => {
        const invalid = task.validation_state === "invalid";
        return <TableRow key={task.id} data-testid={`task-row-${task.code}`} className={invalid ? "bg-orange-50/60 hover:bg-orange-50" : ""}>
          <TableCell className="align-top tabular-nums text-xs font-medium text-slate-600">{task.code}</TableCell>
          <TableCell className="max-w-[420px] align-top"><div className="flex items-start gap-2"><span className={`mt-0.5 ${invalid ? "text-amber-600" : "text-emerald-600"}`}>{invalid ? <AlertTriangle size={15}/> : <CheckCircle2 size={15}/>}</span><div><strong className="block text-slate-950">{task.title || "Untitled task"}</strong>{task.description && <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{task.description}</p>}{invalid && <p className="mt-1 text-xs font-bold text-orange-700">{task.validation_issues.join(", ").replaceAll("_", " ")}</p>}</div></div></TableCell>
          <TableCell className="align-top">{task.phase || "-"}</TableCell>
          <TableCell className="align-top">{task.category || "-"}</TableCell>
          <TableCell className="whitespace-nowrap align-top font-bold text-slate-900">{formatPlannedDays(task)}</TableCell>
          <TableCell className="align-top"><Pill tone={task.applicability === "conditional" ? "orange" : "blue"}>{task.applicability || "Unknown"}</Pill></TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
  </div>;
}