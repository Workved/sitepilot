/** A labelled set of radio cards: each option carries a plain-language explanation. */
export function TemplateChoiceGroup({ label, name, value, options, onChange, columns = 2 }) {
  return <div role="radiogroup" aria-label={label} className="grid gap-2">
    <span className="text-sm font-bold text-slate-700">{label}</span>
    <div className={`grid gap-2 ${columns === 2 ? "sm:grid-cols-2" : ""}`}>
      {options.map(option => {
        const checked = value === option.value;
        return <label key={option.value} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm ${checked ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white"}`}>
          <input type="radio" name={name} value={option.value} checked={checked} onChange={() => onChange(option.value)} aria-label={option.label} className="mt-1 size-4 shrink-0 accent-blue-700"/>
          <span className="min-w-0"><strong className="block text-slate-950">{option.label}</strong>{option.detail && <span className="mt-1 block text-xs font-semibold leading-5 text-slate-600">{option.detail}</span>}</span>
        </label>;
      })}
    </div>
  </div>;
}

/** A titled block of fields in the task and approval dialogs. */
export function TemplateEditorSection({ title, children }) {
  return <section className="grid gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:p-5"><h3 className="text-xs font-medium text-slate-500">{title}</h3>{children}</section>;
}
