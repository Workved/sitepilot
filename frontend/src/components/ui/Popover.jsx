import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../utils/cn";
import { LAYER } from "./layers";

const MARGIN = 8;

/*
 * A menu or panel anchored to a trigger, drawn in <body> above everything
 * (see layers.js). It sits below the trigger, or above when there's more room
 * there; it stays inside the screen, follows the trigger on scroll and
 * resize, and closes on Escape or a click outside both the trigger and itself.
 *
 *   <div ref={anchor}><button onClick={toggle}>…</button></div>
 *   <Popover anchorRef={anchor} open={open} onClose={close} className="w-56">…</Popover>
 *
 * align: "end" lines up right edges, "start" left edges. matchWidth makes it
 * as wide as the trigger (e.g. a picker under a field). Padding is the
 * caller's (cn joins classes, it does not merge them).
 */
export function Popover({ anchorRef, open, onClose, align = "end", matchWidth = false, offset = 6, className, style, children, ...rest }) {
  const panelRef = useRef(null);
  const [position, setPosition] = useState(null);
  const capRef = useRef(null); // the panel's own CSS max-height (e.g. max-h-64), if any
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });

  const place = useCallback(() => {
    const anchor = anchorRef.current;
    const panel = panelRef.current;
    if (!anchor || !panel) return;
    const box = anchor.getBoundingClientRect();
    const viewWidth = window.innerWidth;
    const viewHeight = window.innerHeight;
    if (capRef.current === null) {
      const own = parseFloat(window.getComputedStyle(panel).maxHeight);
      capRef.current = Number.isFinite(own) ? own : Infinity;
    }
    const width = matchWidth ? box.width : panel.offsetWidth;
    const height = Math.min(panel.scrollHeight, capRef.current);
    const below = viewHeight - box.bottom - offset - MARGIN;
    const above = box.top - offset - MARGIN;
    const flip = height > below && above > below;
    const wanted = align === "start" ? box.left : box.right - width;
    setPosition({
      left: Math.max(MARGIN, Math.min(wanted, viewWidth - width - MARGIN)),
      top: flip ? Math.max(MARGIN, box.top - offset - Math.min(height, above)) : box.bottom + offset,
      maxHeight: Math.min(capRef.current, Math.max(120, flip ? above : below)),
      width: matchWidth ? box.width : undefined,
    });
  }, [anchorRef, align, matchWidth, offset]);

  useLayoutEffect(() => {
    if (!open) { setPosition(null); capRef.current = null; return undefined; }
    place();
    let frame = 0;
    const follow = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(place); };
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", follow, true); window.removeEventListener("resize", follow); };
  }, [open, place]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = event => {
      if (anchorRef.current?.contains(event.target) || panelRef.current?.contains(event.target)) return;
      closeRef.current?.();
    };
    const onKey = event => { if (event.key === "Escape") closeRef.current?.(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, anchorRef]);

  if (!open) return null;
  return createPortal(
    <div ref={panelRef} {...rest}
      className={cn("fixed overflow-y-auto overscroll-contain rounded-2xl border border-line bg-white shadow-[0_18px_50px_rgba(21,23,26,.12)]", LAYER.popover, className)}
      style={{ ...style, top: position?.top ?? 0, left: position?.left ?? 0, maxHeight: position?.maxHeight, width: position?.width, visibility: position ? undefined : "hidden" }}>
      {children}
    </div>,
    document.body,
  );
}
