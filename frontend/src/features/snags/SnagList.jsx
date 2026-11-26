import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, ClipboardList, Flag, Plus, Search } from "lucide-react";
import { snagsApi } from "../../api/snagsApi";
import { cn } from "../../utils/cn";
import { PersonPicker, SnagItem } from "./SnagItem";
import { filterSnags, snagSummary, sortSnags } from "./snagHelpers";

// Type a title, press Enter: the snag exists. Area, tag and urgency can be
// set right here too, or later from the snag itself.
function QuickAdd({ projectId, onAdded }) {
  const [title, setTitle] = useState("");
  const [area, setArea] = useState("");
  const [assignee, setAssignee] = useState(null);
  const [urgent, setUrgent] = useState(false);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef(null);

  async function submit(event) {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const created = await snagsApi.create(projectId, { title: title.trim(), area: area.trim() || null, urgent, assignee_user_id: assignee?.id || null });
      onAdded(created);
      setTitle("");
      // Area and tag often repeat while walking a site: keep them.
      setUrgent(false);
      input.current?.focus();
    } catch (caught) {
      setError(caught?.message || "That snag wasn't added. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return <form onSubmit={submit} className="rounded-2xl border border-line bg-white p-2">
    <div className="flex items-center gap-2">
      <Plus size={18} className="ml-1.5 shrink-0 text-blue-700" aria-hidden="true"/>
      <input ref={input} value={title} onChange={event => setTitle(event.target.value)} placeholder="Add a snag, e.g. Touch up paint near cabin 3 door" aria-label="New snag" autoComplete="off" maxLength={200}
        className="h-10 min-w-0 flex-1 bg-transparent text-sm text-slate-950 outline-none placeholder:text-slate-400"/>
      <button type="button" onClick={() => setMore(value => !value)} aria-expanded={more} className="h-8 shrink-0 rounded-lg px-2 text-xs text-slate-600 hover:bg-slate-100">{more ? "Fewer options" : "More options"}</button>
      <button type="submit" disabled={!title.trim() || busy} className="h-8 shrink-0 rounded-lg bg-slate-950 px-3 text-xs font-medium text-white disabled:opacity-30">{busy ? "Adding…" : "Add"}</button>
    </div>
    {more && <div className="mt-2 grid gap-2 border-t border-line px-1.5 pt-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
      <input value={area} onChange={event => setArea(event.target.value)} placeholder="Area, e.g. Cabin 3" aria-label="Area" className="h-9 rounded-lg border border-slate-200 px-2.5 text-sm outline-none focus:border-blue-600"/>
      <PersonPicker value={assignee} onChange={setAssignee}/>
      <button type="button" role="switch" aria-checked={urgent} aria-label="Urgent" onClick={() => setUrgent(value => !value)}
        className={cn("flex h-9 items-center gap-2 rounded-lg px-2.5 text-sm", urgent ? "bg-rose-50 text-rose-800" : "bg-slate-100 text-slate-600")}><Flag size={14}/>{urgent ? "Urgent" : "Not urgent"}</button>
    </div>}
    {error && <p role="alert" className="px-2 pt-1 text-sm text-rose-700">{error}</p>}
  </form>;
}

export function SnagList({ projectId, user, onOpenProject }) {
  const [state, setState] = useState({ loading: true, error: "", items: [], canAdd: false, readOnly: false });
  const [view, setView] = useState("open");
  const [mine, setMine] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    setState(current => ({ ...current, loading: true, error: "" }));
    snagsApi.list(projectId)
      .then(data => alive && setState({ loading: false, error: "", items: data.items || [], canAdd: data.can_add, readOnly: data.read_only }))
      .catch(error => alive && setState({ loading: false, error: error?.message || "The snag list couldn't be loaded.", items: [], canAdd: false, readOnly: false }));
    return () => { alive = false; };
  }, [projectId]);

  const replace = updated => setState(current => ({ ...current, items: current.items.map(item => item.id === updated.id ? updated : item) }));
  const removeItem = removed => setState(current => ({ ...current, items: current.items.filter(item => item.id !== removed.id) }));
  const addItem = created => setState(current => ({ ...current, items: [created, ...current.items] }));

  const summary = snagSummary(state.items);
  const filtered = useMemo(() => filterSnags(state.items, { query, mine, userId: user?.id }), [state.items, query, mine, user?.id]);
  const { open, done } = sortSnags(filtered);
  const mineCount = state.items.filter(item => item.status === "open" && item.assignee?.id === user?.id).length;

  const line = [
    `${summary.open} open`,
    summary.urgent && `${summary.urgent} urgent`,
    summary.overdue && `${summary.overdue} overdue`,
    summary.done && `${summary.done} done`,
  ].filter(Boolean).join(" · ");

  if (state.loading) return <p className="rounded-[20px] border border-line bg-white p-8 text-center text-sm text-slate-500">Loading snags…</p>;
  if (state.error) return <p className="rounded-[20px] border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">{state.error}</p>;

  const list = view === "open" ? open : done;

  return <div className="grid gap-4">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-[17px] font-medium text-slate-950">Snags</h3>
        <p className="mt-0.5 text-sm text-slate-500">{state.items.length ? line : "The small things left to fix. They don't affect the schedule."}</p>
      </div>
    </header>

    {state.canAdd && <QuickAdd projectId={projectId} onAdded={addItem}/>}
    {state.readOnly && <p className="text-sm text-slate-500">This project is archived, so its snag list is read-only.</p>}

    {state.items.length > 0 && <div className="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Show" className="flex gap-0.5 rounded-[10px] bg-slate-100 p-[3px]">
        {[["open", `Open ${summary.open}`], ["done", `Done ${summary.done}`]].map(([value, label]) => <button key={value} type="button" aria-pressed={view === value} onClick={() => setView(value)}
          className={cn("h-8 rounded-lg px-3 text-[13px] transition", view === value ? "bg-white text-slate-950 shadow-[0_1px_3px_rgba(21,23,26,.12)]" : "text-slate-500 hover:text-slate-950")}>{label}</button>)}
      </div>
      <button type="button" aria-pressed={mine} onClick={() => setMine(value => !value)}
        className={cn("h-9 rounded-lg px-3 text-[13px] transition", mine ? "bg-slate-950 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:text-slate-950")}>
        Tagged to me{mineCount ? ` ${mineCount}` : ""}
      </button>
      <label className="relative min-w-[200px] flex-1">
        <span className="sr-only">Search snags</span>
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"/>
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search title, area, notes or person" autoComplete="off"
          className="h-9 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:border-blue-600"/>
      </label>
    </div>}

    <section aria-label={view === "open" ? "Open snags" : "Done snags"} className="rounded-[20px] border border-line bg-canvas/60 p-1.5">
      {list.length
        ? <ul className="grid gap-0.5">{list.map(snag => <SnagItem key={snag.id} snag={snag} onChange={replace} onRemove={removeItem} onOpenProject={onOpenProject}/>)}</ul>
        : <div className="grid justify-items-center gap-2 px-4 py-10 text-center">
            <ClipboardList size={26} className="text-slate-300" aria-hidden="true"/>
            <p className="text-sm text-slate-950">{query || mine ? "No snags match" : view === "open" ? (state.items.length ? "Nothing left open" : "No snags yet") : "Nothing done yet"}</p>
            <p className="max-w-sm text-sm text-slate-500">{query || mine ? "Try a different search, or turn off Tagged to me." : view === "open" ? (state.items.length ? "Every snag on this project is done." : "Add the small jobs left on site above, tag who should fix them, and tick them off as they're done.") : "Ticked-off snags collect here."}</p>
          </div>}
    </section>

    {view === "open" && done.length > 0 && <button type="button" onClick={() => setView("done")} className="flex w-fit items-center gap-1 text-sm text-slate-500 hover:text-slate-950">
      <ChevronRight size={15} aria-hidden="true"/> {done.length} done
    </button>}
  </div>;
}
