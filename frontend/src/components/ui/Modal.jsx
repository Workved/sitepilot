import { useEffect } from "react";
import { X } from "lucide-react";
import { createPortal } from "react-dom";
import { cn } from "../../utils/cn";

// Portaled straight to <body> - every Modal usage in this app renders inline
// as a normal descendant of whatever page/tab is open, and `position: fixed`
// is only reliably relative to the viewport when NO ancestor between here
// and <body> establishes its own containing block (transform, filter,
// backdrop-filter, contain, will-change, or in some browsers an overflow
// clip further complicating it). AppLayout's tab content wrapper is exactly
// such an ancestor. A portal sidesteps the question of which ancestor
// property is responsible entirely - the dialog becomes a direct child of
// <body>, so no ancestor of the page it was opened from can ever affect its
// position again.
export function Modal({ title, subtitle, children, footer, onClose, className, hideHeader = false, bodyClassName }) {
  useEffect(() => {
    // The page behind the modal was never prevented from scrolling. A
    // checkbox toggled deep inside a long form (e.g. the vendor category
    // picker) can trigger the browser's own "scroll the changed/focused
    // element into view" heuristic against the DOCUMENT, not just the
    // modal's own internal `overflow-y-auto` area - dragging the whole
    // fixed-position overlay's visual reference point with it and making
    // the header scroll out of reach. Locking body scroll for as long as
    // any modal is mounted removes that path entirely.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, []);

  return createPortal(
    // No `overflow-hidden` here: an `overflow` value other than `visible`
    // still makes an element a scroll container the browser can
    // programmatically `scrollTop` during its own focus-into-view handling,
    // even with no visible scrollbar. A visually-hidden (`sr-only`) checkbox
    // deep inside (e.g. the category picker) has a ~0px focus target, so the
    // browser's visibility check kept escalating up to this backdrop div and
    // nudging its scrollTop to "reveal" it - dragging the whole centered
    // dialog, header included, out of view with no scrollbar to bring it
    // back. The dialog's own max-height + internal overflow-y-auto already
    // handle real overflow, so this div never needed to clip anything.
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-0 backdrop-blur-[2px] sm:p-4" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose?.()}>
      {/* `overflow-clip`, not `overflow-hidden`: hidden still lets the
          browser's own focus-into-view heuristic silently rewrite this
          box's scrollTop to "reveal" a focused descendant (e.g. the
          sr-only category checkbox) - no visible scrollbar, but it drags
          the header up behind this box's own clipped top edge. `clip`
          renders identically but is excluded from scrolling entirely,
          manual or programmatic. */}
      <section className={cn("flex h-dvh w-full flex-col overflow-clip bg-white shadow-[0_24px_80px_rgba(21,23,26,.18)] sm:h-auto sm:max-h-[min(92dvh,920px)] sm:max-w-2xl sm:rounded-[26px] sm:border sm:border-line", className)} role="dialog" aria-modal="true" aria-label={title}>
        {!hideHeader && <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line bg-white px-4 py-4 sm:px-6 sm:py-5"><div className="min-w-0"><h2 className="text-xl font-normal tracking-[-0.01em] text-slate-950 sm:text-[22px]">{title}</h2>{subtitle && <p className="mt-1 max-w-2xl text-sm leading-5 text-slate-500 sm:leading-6">{subtitle}</p>}</div><button type="button" className="grid size-11 shrink-0 place-items-center rounded-xl border border-slate-200 bg-white text-slate-700 transition hover:bg-slate-50 hover:text-slate-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600" onClick={onClose} aria-label="Close modal"><X aria-hidden="true" size={20} strokeWidth={2}/></button></header>}
        <div className={cn("min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 sm:p-6", hideHeader && "p-0 sm:p-0", bodyClassName)}>{children}</div>
        {/* A real flex sibling, not a `position: sticky` element living inside
            the scrollable body above - sticky-inside-a-blurred-scroll-container
            is fragile (breaks when the body's content height changes) and
            previously caused the modal to visibly misalign once its content
            grew past a certain height. */}
        {footer && <footer className="shrink-0 border-t border-line bg-slate-50 px-4 py-4 sm:px-6">{footer}</footer>}
      </section>
    </div>,
    document.body,
  );
}