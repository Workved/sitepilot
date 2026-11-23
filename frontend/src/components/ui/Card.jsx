import { cn } from "../../utils/cn";
export function Card({ children, className }) { return <section className={cn("rounded-[22px] border border-line bg-white p-5", className)}>{children}</section>; }
