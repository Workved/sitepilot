import { cn } from "../../utils/cn";
export function Table({ children, className }) { return <div className="so-scroll w-full overflow-x-auto"><table className={cn("w-full border-collapse text-left text-sm", className)}>{children}</table></div>; }
export function TableHead({ children, className }) { return <thead className={cn("border-b border-line bg-slate-50 text-[13px] font-normal text-slate-500", className)}>{children}</thead>; }
export function TableBody({ children, className }) { return <tbody className={cn("divide-y divide-line", className)}>{children}</tbody>; }
export function TableRow({ children, className, ...props }) { return <tr className={cn("transition-colors hover:bg-slate-50", className)} {...props}>{children}</tr>; }
export function TableHeader({ children, className, ...props }) { return <th className={cn("px-5 py-3 font-normal", className)} {...props}>{children}</th>; }
export function TableCell({ children, className, ...props }) { return <td className={cn("px-5 py-4 text-slate-700", className)} {...props}>{children}</td>; }
