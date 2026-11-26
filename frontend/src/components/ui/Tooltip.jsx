import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../utils/cn";
import { LAYER } from "./layers";

/*
 * A short label shown on hover or keyboard focus, drawn in <body> so nothing
 * on the page can cover or clip it (see layers.js). It's visual only: give
 * the trigger its own accessible name (aria-label).
 */
export function Tooltip({ label, side = "right", className, children }) {
  const ref = useRef(null);
  const [box, setBox] = useState(null);
  const show = () => setBox(ref.current?.getBoundingClientRect() || null);
  const hide = () => setBox(null);

  useEffect(() => {
    if (!box) return undefined;
    window.addEventListener("scroll", hide, true);
    return () => window.removeEventListener("scroll", hide, true);
  }, [box]);

  const style = !box ? null : side === "right"
    ? { left: box.right + 8, top: box.top + box.height / 2, transform: "translateY(-50%)" }
    : { left: box.left + box.width / 2, top: box.bottom + 8, transform: "translateX(-50%)" };

  return <span ref={ref} className={cn("inline-flex", className)} onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} onClick={hide}>
    {children}
    {box && createPortal(
      <span role="tooltip" style={style} className={cn("pointer-events-none fixed whitespace-nowrap rounded-lg bg-slate-950 px-2.5 py-1.5 text-xs font-medium text-white shadow-sm", LAYER.tooltip)}>{label}</span>,
      document.body,
    )}
  </span>;
}
