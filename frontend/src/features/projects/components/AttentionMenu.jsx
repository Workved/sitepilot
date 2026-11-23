import { Bell, CircleAlert, Clock3, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const severityStyle = {
  critical: { wrap: "bg-rose-50 text-rose-700", Icon: CircleAlert },
  warning: { wrap: "bg-orange-50 text-orange-700", Icon: Clock3 },
  decision: { wrap: "bg-violet-50 text-violet-700", Icon: ShieldCheck },
};

function AttentionItem({ item, onOpen }) {
  const { wrap, Icon } = severityStyle[item.severity] || severityStyle.warning;
  return <button
    type="button"
    onClick={() => onOpen(item)}
    className="grid w-full grid-cols-[28px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-xl px-2 py-2 text-left transition hover:bg-slate-50"
  >
    <span className={`grid size-7 place-items-center rounded-lg ${wrap}`}><Icon size={14} aria-hidden="true"/></span>
    <span className="min-w-0">
      <span className="block truncate text-sm text-slate-950">{item.title}</span>
      <span className="block truncate text-xs text-slate-500">{item.subtitle}</span>
    </span>
    {item.due_label && <span className="shrink-0 pt-0.5 text-xs text-slate-500">{item.due_label}</span>}
  </button>;
}

export function AttentionMenu({ items, onOpen }) {
  const [open, setOpen] = useState(false);
  const holder = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onDocument(event) {
      if (!holder.current?.contains(event.target)) setOpen(false);
    }
    function onKey(event) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocument);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocument);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // The attention read model has not shipped yet, or genuinely returned
  // nothing. Either way there is no counter worth showing.
  if (!items?.length) return null;

  const groups = [...new Set(items.map(item => item.group))];

  return <div className="relative" ref={holder}>
    <button
      type="button"
      onClick={() => setOpen(value => !value)}
      aria-expanded={open}
      aria-haspopup="true"
      className={`inline-flex min-h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border px-2.5 text-[13px] font-medium transition ${open ? "border-slate-300 bg-slate-50 text-slate-950" : "border-slate-200 bg-white text-slate-800 hover:border-slate-300 hover:bg-slate-50"}`}
    >
      <Bell size={15} aria-hidden="true"/>
      <span className="grid h-5 min-w-5 place-items-center rounded-md bg-rose-600 px-1 text-xs text-white">{items.length}</span>
      <span>Needs attention</span>
    </button>

    {open && <div
      role="menu"
      className="absolute left-0 top-[calc(100%+6px)] z-40 max-h-96 w-[min(24rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-line bg-white p-2 shadow-[0_18px_50px_rgba(21,23,26,.12)]"
    >
      {groups.map(group => <div key={group}>
        <p className="flex items-center gap-2 px-2 pb-1 pt-2 text-xs text-slate-500">
          {group}<span className="h-px flex-1 bg-line"/>
        </p>
        {items.filter(item => item.group === group).map(item => <AttentionItem
          key={item.id}
          item={item}
          onOpen={selected => { setOpen(false); onOpen(selected); }}
        />)}
      </div>)}
    </div>}
  </div>;
}
