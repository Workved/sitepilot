import { useMemo, useState } from "react";
import { Boxes, Check, Info, PackageOpen, Search, X } from "lucide-react";

export function CategorySelector({ categories = [], selected = [], onChange, error }) {
  const [query, setQuery] = useState("");
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const availableCategories = useMemo(() => categories.filter(category => category.active !== false || selected.includes(category.id)), [categories, selected]);
  const categoryById = useMemo(() => Object.fromEntries(categories.map(category => [category.id, category])), [categories]);
  const childrenByParent = useMemo(() => availableCategories.reduce((result, category) => {
    if (category.parent_id) (result[category.parent_id] ||= []).push(category);
    return result;
  }, {}), [availableCategories]);

  const roots = useMemo(() => availableCategories
    .filter(category => !category.parent_id)
    .filter(category => {
      const needle = query.trim().toLowerCase();
      if (!needle) return true;
      return category.name.toLowerCase().includes(needle)
        || (childrenByParent[category.id] || []).some(child => child.name.toLowerCase().includes(needle));
    }), [availableCategories, childrenByParent, query]);

  const selectedSummary = useMemo(() => selected
    .map(id => categoryById[id])
    .filter(Boolean)
    .filter(category => category.parent_id || !(childrenByParent[category.id] || []).some(child => selectedSet.has(child.id))),
  [categoryById, childrenByParent, selected, selectedSet]);

  function commit(next) {
    onChange?.([...next]);
  }

  function toggle(category) {
    const next = new Set(selectedSet);
    if (next.has(category.id)) {
      next.delete(category.id);
      if (!category.parent_id) (childrenByParent[category.id] || []).forEach(child => next.delete(child.id));
      if (category.parent_id && !(childrenByParent[category.parent_id] || []).some(child => next.has(child.id))) next.delete(category.parent_id);
    } else {
      next.add(category.id);
      if (category.parent_id) next.add(category.parent_id);
    }
    commit(next);
  }

  return (
    <section className={`col-span-full overflow-hidden rounded-2xl border bg-white ${error ? "border-rose-300 ring-4 ring-rose-50" : "border-slate-200"}`}>
      {selected.map(id => <input key={id} type="hidden" name="category_ids" value={id}/>) }
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-slate-950"><Boxes size={18} className="text-blue-700"/> Categories and capabilities</div>
          <p className="mt-1 text-xs leading-5 text-slate-500">Choose a main capability or a more precise subcategory.</p>
        </div>
        <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-medium text-white">{selectedSummary.length} selected</span>
      </header>

      <div className="grid gap-4 p-5">
        <label className="flex min-h-11 min-w-56 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 text-slate-500 focus-within:border-blue-400 focus-within:bg-white"><Search size={16}/><input className="min-h-0 w-full border-0 bg-transparent p-0 text-sm outline-none" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search categories"/></label>

        {selectedSummary.length > 0 && <div className="flex flex-wrap gap-2 rounded-xl bg-slate-50 p-3">{selectedSummary.map(category => <button type="button" key={category.id} onClick={() => toggle(category)} className="flex items-center gap-1.5 rounded-full bg-blue-100 px-3 py-1.5 text-xs font-medium text-blue-900">{category.name}<X size={13}/></button>)}</div>}

        <div className="grid grid-cols-2 gap-3 max-[720px]:grid-cols-1">
          {roots.map(root => {
            const children = (childrenByParent[root.id] || []).filter(child => !query.trim() || child.name.toLowerCase().includes(query.trim().toLowerCase()) || root.name.toLowerCase().includes(query.trim().toLowerCase()));
            const rootSelected = selectedSet.has(root.id);
            return <article key={root.id} className={`rounded-2xl border p-4 transition ${rootSelected ? "border-blue-300 bg-blue-50/70" : "border-slate-200 bg-white hover:border-slate-300"}`}>
              <label className="flex cursor-pointer items-start gap-3">
                <input type="checkbox" className="sr-only" checked={rootSelected} onChange={() => toggle(root)}/>
                <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-lg border ${rootSelected ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white text-transparent"}`}><Check size={15}/></span>
                <span className="min-w-0"><strong className="block text-sm text-slate-950">{root.name}</strong><small className="mt-1 block text-xs leading-4 text-slate-500">{root.description || (children.length ? `${children.length} available subcategories` : "Select this capability")}</small></span>
              </label>
              {children.length > 0 && <div className="mt-4 flex flex-wrap gap-2 border-t border-black/5 pt-3">{children.map(child => <label key={child.id} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs font-bold transition ${selectedSet.has(child.id) ? "border-blue-300 bg-white text-blue-900" : "border-slate-200 bg-white/70 text-slate-600 hover:border-slate-300"}`}><input type="checkbox" checked={selectedSet.has(child.id)} onChange={() => toggle(child)} className="size-4 rounded border-slate-300 accent-blue-700"/>{child.name}</label>)}</div>}
            </article>;
          })}
        </div>

        {!roots.length && <div className="grid min-h-28 place-items-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 text-center"><div><PackageOpen className="mx-auto text-slate-400"/><p className="mt-2 text-sm font-bold text-slate-600">No matching categories</p></div></div>}
        {error && <p className="text-sm font-bold text-rose-700">{error}</p>}
      </div>
    </section>
  );
}
