import { Search, SlidersHorizontal } from "lucide-react";
import { Button } from "./Button";
import { Card } from "./Card";
import { Input } from "./Field";
import { Pill } from "./Pill";
import { Table } from "./Table";

export function ManagementTable({ countLabel, count, searchPlaceholder, tableClassName = "", mobileContent, children }) {
  return <Card className="overflow-hidden p-0"><div className="flex flex-col gap-3 border-b border-line p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5"><div className="flex items-center gap-2 text-[15px] font-medium text-slate-900">{countLabel}<Pill tone="gray">{count}</Pill></div><div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:flex"><div className="relative"><Search aria-hidden="true" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/><Input className="bg-slate-50 pl-9 sm:w-64" placeholder={searchPlaceholder} readOnly/></div><Button size="icon" variant="secondary" aria-label="Filters"><SlidersHorizontal size={17}/><span className="sr-only">Filters</span></Button></div></div>{mobileContent && <div className="divide-y divide-line md:hidden">{mobileContent}</div>}<div className={mobileContent ? "hidden md:block" : ""}><Table className={tableClassName}>{children}</Table></div></Card>;
}
