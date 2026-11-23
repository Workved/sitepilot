import { ChevronDown, LogOut, MoreHorizontal, RefreshCw, Search, UserRoundCog } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";
import { getTabDefinition } from "../../config/tabs";
import { Alert, IconButton } from "../ui";
import { BrandMark } from "./BrandMark";

export function tabHelp(tab) {
  return getTabDefinition(tab)?.help || "Workspace";
}

function TabIcon({ tab, size = 20 }) {
  const Icon = getTabDefinition(tab)?.icon || UserRoundCog;
  return <Icon aria-hidden="true" size={size} strokeWidth={1.75} />;
}

// Desktop navigation is an icon rail: the module name lives in the top bar
// and in a hover/focus label beside each icon, so the rail stays 84px wide
// and the page gets the width back.
function DesktopRail({ tabs, activeTab, onTabChange, onLogout }) {
  return <aside className="sticky top-3 hidden h-[calc(100dvh-1.5rem)] w-[84px] shrink-0 flex-col items-center gap-2 border-r border-line bg-slate-50 py-5 lg:flex">
    <div className="mb-5 grid size-11 place-items-center"><BrandMark /></div>
    <nav aria-label="Primary navigation" className="so-scroll flex min-h-0 flex-1 flex-col items-center gap-2 overflow-y-auto overflow-x-visible px-2">
      {tabs.map(([key, label]) => {
        const active = activeTab === key;
        return <button type="button" key={key} onClick={() => onTabChange(key)} aria-current={active ? "page" : undefined} aria-label={label} className={`group relative grid size-12 shrink-0 place-items-center rounded-[14px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${active ? "bg-slate-950 text-white" : "text-slate-500 hover:bg-white hover:text-slate-950"}`}>
          <TabIcon tab={key} />
          <span role="tooltip" className="pointer-events-none fixed left-[92px] z-50 hidden whitespace-nowrap rounded-lg bg-slate-950 px-2.5 py-1.5 text-xs font-medium text-white group-hover:block group-focus-visible:block">{label}</span>
        </button>;
      })}
    </nav>
    <button type="button" onClick={onLogout} aria-label="Logout" title="Log out" className="grid size-12 shrink-0 place-items-center rounded-[14px] text-slate-500 transition-colors hover:bg-white hover:text-slate-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600">
      <LogOut aria-hidden="true" size={20} strokeWidth={1.75} />
    </button>
  </aside>;
}

// "Jump to" search over the modules this user can open. There is no global
// record search on the backend yet; when one lands it plugs in here.
function ModuleSearch({ tabs, onTabChange }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef(null);
  const boxRef = useRef(null);

  const results = useMemo(() => {
    const term = query.trim().toLowerCase();
    return tabs.filter(([key, label]) => !term || label.toLowerCase().includes(term) || tabHelp(key).toLowerCase().includes(term));
  }, [query, tabs]);

  useEffect(() => {
    function onKey(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    }
    function onDown(event) {
      if (boxRef.current && !boxRef.current.contains(event.target)) setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { window.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, []);

  useEffect(() => { setHighlight(0); }, [query]);

  function go(key) {
    onTabChange(key);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  }

  function onKeyDown(event) {
    if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setHighlight(h => Math.min(h + 1, results.length - 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setHighlight(h => Math.max(h - 1, 0)); }
    else if (event.key === "Enter" && results[highlight]) { event.preventDefault(); go(results[highlight][0]); }
    else if (event.key === "Escape") { setOpen(false); inputRef.current?.blur(); }
  }

  return <div ref={boxRef} className="relative w-full max-w-[460px]">
    <label className="flex h-11 items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50 pl-3.5 pr-2 transition focus-within:border-blue-600 focus-within:bg-white focus-within:ring-4 focus-within:ring-blue-600/10">
      <Search aria-hidden="true" size={17} className="text-slate-500" />
      <span className="sr-only">Jump to a module</span>
      <input ref={inputRef} type="search" name="siteops-module-search" autoComplete="off" spellCheck={false} role="combobox" aria-expanded={open} aria-controls="module-search-results" aria-autocomplete="list" value={query} onChange={event => { setQuery(event.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKeyDown} placeholder="Jump to a module" className="min-w-0 flex-1 bg-transparent text-sm text-slate-950 outline-none placeholder:text-slate-400" />
      <kbd className="hidden items-center gap-1 font-sans text-xs text-slate-500 sm:flex"><span className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5">⌘</span><span className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5">K</span></kbd>
    </label>
    {open && <ul id="module-search-results" role="listbox" aria-label="Modules" className="absolute inset-x-0 top-[calc(100%+6px)] z-40 grid gap-0.5 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      {results.length === 0 && <li className="px-3 py-3 text-sm text-slate-500">No module matches “{query}”.</li>}
      {results.map(([key, label], index) => <li key={key} role="option" aria-selected={index === highlight}>
        <button type="button" onMouseEnter={() => setHighlight(index)} onClick={() => go(key)} className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left ${index === highlight ? "bg-slate-100" : ""}`}>
          <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-white text-slate-700"><TabIcon tab={key} size={17} /></span>
          <span className="min-w-0"><span className="block text-sm text-slate-950">{label}</span><span className="block truncate text-xs text-slate-500">{tabHelp(key)}</span></span>
        </button>
      </li>)}
    </ul>}
  </div>;
}

function UserMenu({ user, onLogout }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    function onDown(event) { if (ref.current && !ref.current.contains(event.target)) setOpen(false); }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);
  return <div ref={ref} className="relative">
    <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} aria-haspopup="true" aria-label={`Account: ${user.name}`} className="flex h-11 items-center gap-2.5 rounded-xl border border-slate-200 bg-white pl-1 pr-2 text-left transition hover:border-slate-300 sm:pr-2.5">
      <span className="grid size-9 place-items-center rounded-[10px] bg-blue-100 text-[13px] font-medium text-blue-800">{initials(user.name)}</span>
      <span className="hidden min-w-0 leading-tight sm:block"><span className="block max-w-40 truncate text-[13px] font-medium text-slate-950">{user.name}</span><span className="block max-w-40 truncate text-xs text-slate-500">{roles[user.role] || user.role}</span></span>
      <ChevronDown aria-hidden="true" size={16} className="text-slate-500" />
    </button>
    {open && <div className="absolute right-0 top-[calc(100%+6px)] z-40 w-64 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(21,23,26,.12)]">
      <div className="px-3 py-2.5"><p className="truncate text-sm font-medium text-slate-950">{user.name}</p><p className="truncate text-xs text-slate-500">{user.email}</p></div>
      <div className="my-1 h-px bg-line" />
      <button type="button" onClick={onLogout} className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-100 hover:text-slate-950"><LogOut aria-hidden="true" size={17} />Log out</button>
    </div>}
  </div>;
}

function TopBar({ title, tabs, onTabChange, user, onLogout, onRefresh }) {
  return <header className="sticky top-0 z-30 flex min-h-[76px] items-center gap-3 border-b border-line bg-white/90 px-4 backdrop-blur-xl sm:gap-4 sm:px-6 lg:px-7">
    <div className="grid size-10 shrink-0 place-items-center lg:hidden"><BrandMark className="size-8" /></div>
    <h1 className="min-w-0 shrink truncate text-2xl font-normal tracking-[-0.02em] text-slate-950 sm:text-[30px]">{title}</h1>
    <div className="hidden min-w-0 flex-1 justify-center md:flex"><ModuleSearch tabs={tabs} onTabChange={onTabChange} /></div>
    <div className="ml-auto flex shrink-0 items-center gap-2 md:ml-0">
      <IconButton variant="secondary" aria-label="Refresh workspace" onClick={onRefresh}><RefreshCw size={18} strokeWidth={1.75} /></IconButton>
      <UserMenu user={user} onLogout={onLogout} />
    </div>
  </header>;
}

// Beyond this many items, an equal-width single row squeezes every label
// down to 2-3 letters ("Pro...", "Por...") on a real phone - the crowded
// bottom nav a wide-permission role (Admin/Super Admin, up to 7 tabs) hits.
// Standard mobile nav guidance caps a bottom bar at 5 slots; past that, the
// last slot becomes "More" instead of a 6th/7th squeezed button.
const MAX_VISIBLE_MOBILE_TABS = 5;

function MobileTabButton({ tab, label, active, onClick }) {
  return <button type="button" onClick={onClick} aria-current={active ? "page" : undefined} className={`grid min-h-[58px] min-w-0 place-items-center content-center gap-1 rounded-2xl px-1 text-[11px] font-medium transition ${active ? "bg-slate-950 text-white" : "text-slate-500 hover:bg-slate-100 hover:text-slate-950"}`}>
    <TabIcon tab={tab} size={20}/><span className="max-w-full truncate">{label}</span>
  </button>;
}

function MoreTabsSheet({ tabs, activeTab, onSelect, onClose }) {
  return createPortal(
    <div className="fixed inset-0 z-40 bg-slate-950/30 lg:hidden" role="presentation" onClick={onClose}>
      <div
        role="menu"
        aria-label="More navigation"
        className="fixed inset-x-2 bottom-[calc(6rem+env(safe-area-inset-bottom))] z-50 grid gap-1 rounded-[22px] border border-line bg-white p-2 shadow-[0_18px_55px_rgba(21,23,26,.18)]"
        onClick={event => event.stopPropagation()}
      >
        {tabs.map(([key, label]) => {
          const active = activeTab === key;
          return <button type="button" key={key} role="menuitem" onClick={() => onSelect(key)} aria-current={active ? "page" : undefined} className={`flex min-h-14 min-w-0 items-center gap-3 rounded-2xl px-3 text-left transition ${active ? "bg-slate-950 text-white" : "text-slate-700 hover:bg-slate-100"}`}>
            <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${active ? "bg-white/10" : "bg-slate-100"}`}><TabIcon tab={key} size={19}/></span>
            <span className="min-w-0"><span className="block truncate text-sm font-medium">{label}</span><small className={`mt-0.5 block truncate text-xs ${active ? "text-slate-300" : "text-slate-500"}`}>{tabHelp(key)}</small></span>
          </button>;
        })}
      </div>
    </div>,
    document.body,
  );
}

function MobileNavigation({ tabs, activeTab, onTabChange }) {
  const [showMore, setShowMore] = useState(false);
  const hasOverflow = tabs.length > MAX_VISIBLE_MOBILE_TABS;
  const primaryTabs = hasOverflow ? tabs.slice(0, MAX_VISIBLE_MOBILE_TABS - 1) : tabs;
  const overflowTabs = hasOverflow ? tabs.slice(MAX_VISIBLE_MOBILE_TABS - 1) : [];
  const overflowActive = overflowTabs.some(([key]) => key === activeTab);

  function selectOverflowTab(key) {
    setShowMore(false);
    onTabChange(key);
  }

  return <>
    <nav aria-label="Mobile navigation" className="fixed inset-x-2 bottom-2 z-40 grid grid-flow-col auto-cols-fr gap-1 rounded-[22px] border border-line bg-white/95 p-1.5 pb-[max(.375rem,env(safe-area-inset-bottom))] shadow-[0_18px_55px_rgba(21,23,26,.14)] backdrop-blur-xl lg:hidden">
      {primaryTabs.map(([key, label]) => <MobileTabButton key={key} tab={key} label={label.replace("Vendor Hub", "Vendors").replace("Role Permissions", "Roles")} active={activeTab === key} onClick={() => onTabChange(key)}/>)}
      {hasOverflow && <button type="button" onClick={() => setShowMore(true)} aria-haspopup="true" aria-expanded={showMore} className={`grid min-h-[58px] min-w-0 place-items-center content-center gap-1 rounded-2xl px-1 text-[11px] font-medium transition ${overflowActive ? "bg-slate-950 text-white" : "text-slate-500 hover:bg-slate-100 hover:text-slate-950"}`}>
        <MoreHorizontal aria-hidden="true" size={20}/><span>More</span>
      </button>}
    </nav>
    {hasOverflow && showMore && <MoreTabsSheet tabs={overflowTabs} activeTab={activeTab} onSelect={selectOverflowTab} onClose={() => setShowMore(false)}/>}
  </>;
}

// Modals render via their own portal at z-50 and cover the full viewport, so a
// notice sitting inline in <main> (behind that backdrop) is invisible whenever
// an action is triggered from inside one - portal this above it instead.
function NoticeToast({ notice, onDismiss }) {
  if (!notice) return null;
  return createPortal(
    <div className="pointer-events-none fixed inset-x-0 top-0 z-[60] flex justify-center px-3 pt-3 sm:px-4">
      <div className="pointer-events-auto w-full max-w-xl rounded-2xl shadow-[0_18px_50px_rgba(21,23,26,.16)]">
        <Alert tone={notice.tone} onDismiss={onDismiss}>{notice.message}</Alert>
      </div>
    </div>,
    document.body,
  );
}

export function AppLayout({ user, tabs, activeTab, onTabChange, onLogout, onRefresh, notice, onClearNotice, children }) {
  const activeLabel = tabs.find(([key]) => key === activeTab)?.[1] || "Workspace";
  return <div className="flex min-h-dvh min-w-0 bg-canvas text-slate-950 lg:p-3">
    <div className="flex min-h-[calc(100dvh-1.5rem)] min-w-0 flex-1 bg-white lg:overflow-clip lg:rounded-[28px] lg:border lg:border-slate-200">
      <DesktopRail tabs={tabs} activeTab={activeTab} onTabChange={onTabChange} onLogout={onLogout} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar title={activeLabel} tabs={tabs} onTabChange={onTabChange} user={user} onLogout={onLogout} onRefresh={onRefresh} />
        <main className={`min-w-0 max-w-full flex-1 overflow-x-hidden bg-[#fbfbfc] px-3 pb-28 pt-4 sm:px-5 sm:pt-5 lg:px-7 lg:pb-8 lg:pt-6 tab-${activeTab}`}>
          {children}
        </main>
      </div>
    </div>
    <NoticeToast notice={notice} onDismiss={onClearNotice}/>
    <MobileNavigation tabs={tabs} activeTab={activeTab} onTabChange={onTabChange}/>
  </div>;
}
