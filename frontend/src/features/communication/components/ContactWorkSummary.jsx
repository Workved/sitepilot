import { ClipboardList, FolderKanban } from "lucide-react";

// Which projects (and trades) a vendor's person is assigned to, and which
// tasks they are the point person for. Assigning happens from the project's
// Vendors tab and the task's vendor delegation.
export function ContactWorkSummary({ projects = [], tasks = [] }) {
  if (!projects.length && !tasks.length) {
    return <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-400">Not assigned to any project yet. Assign people from a project's Vendors tab.</p>;
  }

  const byProject = new Map();
  for (const row of projects) {
    const entry = byProject.get(row.project_id) || { name: row.project_name, trades: [], note: null };
    entry.trades.push(row.category_name || "All work");
    entry.note = entry.note || row.note;
    byProject.set(row.project_id, entry);
  }

  return <div className="mt-3 grid gap-2 border-t border-slate-100 pt-3">
    {byProject.size > 0 && <div>
      <span className="text-[10px] font-black uppercase tracking-[0.14em] text-slate-400">Projects</span>
      <ul className="mt-1 grid gap-1">{[...byProject.entries()].map(([projectId, entry]) => <li key={projectId} className="flex flex-wrap items-center gap-1.5 text-sm">
        <FolderKanban size={13} className="text-slate-400"/><strong className="text-slate-800">{entry.name}</strong>
        {entry.trades.map(trade => <span key={trade} className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-black text-blue-900">{trade}</span>)}
        {entry.note && <span className="text-xs text-slate-500">· {entry.note}</span>}
      </li>)}</ul>
    </div>}
    {tasks.length > 0 && <div>
      <span className="text-[10px] font-black uppercase tracking-[0.14em] text-slate-400">Point person for</span>
      <ul className="mt-1 grid gap-1">{tasks.map(task => <li key={task.assignment_id} className="flex flex-wrap items-center gap-1.5 text-sm">
        <ClipboardList size={13} className="text-slate-400"/><span className="text-slate-800">{task.task_title}</span><span className="text-xs text-slate-500">· {task.project_name}</span>
      </li>)}</ul>
    </div>}
  </div>;
}
