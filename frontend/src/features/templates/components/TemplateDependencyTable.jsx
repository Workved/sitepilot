import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Pill, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui";
import { DependencyTaskLink, dependencyTypeLabel } from "./TemplateDependencyCard";

export function TemplateDependencyTable({ dependencies, onFocusTask }) {
  return <div className="hidden overflow-hidden rounded-[20px] border border-line bg-white lg:block">
    <Table>
      <TableHead><TableRow className="hover:bg-transparent"><TableHeader>First</TableHeader><TableHeader>Link</TableHeader><TableHeader>Then</TableHeader><TableHeader>Enforced</TableHeader><TableHeader>Note</TableHeader><TableHeader>Check</TableHeader></TableRow></TableHead>
      <TableBody>{dependencies.map(dependency => {
        const invalid = dependency.validation_state === "invalid";
        return <TableRow key={dependency.id} data-testid={`dependency-row-${dependency.id}`} className={invalid ? "bg-orange-50/60 hover:bg-orange-50" : ""}>
          <TableCell className="max-w-[260px] align-top"><DependencyTaskLink task={dependency.predecessor} onFocusTask={onFocusTask}/></TableCell>
          <TableCell className="whitespace-nowrap align-top"><Pill tone="blue">{dependencyTypeLabel(dependency.dependency_type)}</Pill></TableCell>
          <TableCell className="max-w-[260px] align-top"><DependencyTaskLink task={dependency.successor} onFocusTask={onFocusTask}/></TableCell>
          <TableCell className="align-top"><Pill tone={dependency.blocking ? "red" : "gray"}>{dependency.blocking ? "Enforced" : "Advisory"}</Pill></TableCell>
          <TableCell className="max-w-[320px] align-top text-xs leading-5 text-slate-600">{dependency.rule_text || "-"}</TableCell>
          <TableCell className="align-top"><span className={`inline-flex items-start gap-1.5 text-xs font-medium ${invalid ? "text-amber-700" : "text-emerald-700"}`}>{invalid ? <AlertTriangle className="mt-0.5 shrink-0" size={15}/> : <CheckCircle2 className="mt-0.5 shrink-0" size={15}/>}<span>{invalid ? dependency.validation_issues.join(", ").replaceAll("_", " ") : "Valid"}</span></span></TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
  </div>;
}
