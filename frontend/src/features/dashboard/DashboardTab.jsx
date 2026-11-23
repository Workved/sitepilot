import { LoadingSpinner } from "../../components/ui";
import { AdminProjectsOverview } from "../admin/AdminProjectsOverview";
import { CommunicationPage } from "../broadcasts/CommunicationPage";
import { CommunicationHubPage } from "../communication/CommunicationHubPage";
import { ExecutionPage } from "../execution/ExecutionPage";
import { OverviewPage } from "../overview/OverviewPage";
import { ProjectsPage } from "../projects/ProjectsPage";
import { TemplatesPage } from "../templates/TemplatesPage";
import { UsersPage } from "../users/UsersPage";

const TAB_COMPONENTS = {
  overview: OverviewPage,
  projects: ProjectsPage,
  admin_overview: AdminProjectsOverview,
  templates: TemplatesPage,
  execution: ExecutionPage,
  communication: CommunicationHubPage,
  broadcasts: CommunicationPage,
  users: UsersPage,
};

export function DashboardTab({ tab, loading, data, user, tabs, action, onOpenProject, onTabChange, onRefresh }) {
  if (loading) {
    return <section className="rounded-[22px] border border-line bg-white p-6"><LoadingSpinner label="Loading workspace..." /></section>;
  }
  const Component = TAB_COMPONENTS[tab];
  if (!Component) return null;
  const identityKey = `${user?.id || user?.email || "anonymous"}:${user?.role || "unknown"}`;
  return <Component key={`${tab}:${identityKey}`} data={data} user={user} tabs={tabs} action={action} onOpenProject={onOpenProject} onTabChange={onTabChange} onRefresh={onRefresh} />;
}
