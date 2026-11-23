import { BookOpenCheck, BriefcaseBusiness, CalendarCheck, FolderKanban, Gauge, LayoutDashboard, Megaphone, UsersRound } from "lucide-react";

export const TAB_REGISTRY = {
  overview: { label: "Overview", help: "Today across your sites", icon: LayoutDashboard },
  projects: { label: "Projects", help: "Project setup, ownership and lifecycle", icon: FolderKanban },
  admin_overview: { label: "Portfolio", help: "Cross-project rollup and activity", icon: Gauge },
  templates: { label: "Templates", help: "Approved project schedule library", icon: BookOpenCheck },
  execution: { label: "Execution", help: "Drive task execution on activated projects", icon: CalendarCheck },
  communication: { label: "Vendor Hub", help: "Vendors, contacts & quick actions", icon: BriefcaseBusiness },
  broadcasts: { label: "Communication", help: "Project messages & broadcasts", icon: Megaphone },
  users: { label: "Users & Access", help: "People, access and your account", icon: UsersRound },
};

export const labels = Object.fromEntries(Object.entries(TAB_REGISTRY).map(([key, item]) => [key, item.label]));

export function getTabDefinition(key) {
  return TAB_REGISTRY[key];
}

export function visibleTabs(modulePermissions, role) {
  const templateRoles = ["super_admin", "admin", "project_manager"];
  const permitted = modulePermissions.filter(key => key !== "templates" || templateRoles.includes(role));
  if (templateRoles.includes(role) && !permitted.includes("templates")) {
    const projectIndex = permitted.indexOf("projects");
    permitted.splice(projectIndex >= 0 ? projectIndex + 1 : 0, 0, "templates");
  }
  // Overview is a client-side home built from read models every signed-in
  // role can already reach (/projects/timeline, /projects/attention), so it
  // needs no backend module grant and always leads the list.
  const withHome = ["overview", ...permitted.filter(key => key !== "overview")];
  return withHome.filter(key => TAB_REGISTRY[key]).map(key => {
    const label = key === "users" && !["super_admin", "admin"].includes(role) ? "My Profile" : TAB_REGISTRY[key].label;
    return [key, label];
  });
}
