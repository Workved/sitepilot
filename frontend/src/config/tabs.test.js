import { describe, expect, it } from "vitest";
import { visibleTabs } from "./tabs";

const modules = ["projects", "execution", "communication", "users"];
const keysFor = role => visibleTabs(modules, role).map(([key]) => key);

describe("template navigation visibility", () => {
  it.each(["super_admin", "admin", "project_manager"])("shows Templates for %s", role => {
    expect(keysFor(role)).toContain("templates");
  });

  it.each(["supervisor", "internal_employee"])("hides Templates for %s", role => {
    expect(keysFor(role)).not.toContain("templates");
  });
});

describe("Phase 3 Portfolio (admin_overview) navigation visibility", () => {
  // The backend only puts "admin_overview" in module_permissions for
  // super_admin/admin (see backend/app/routes/dashboard.py), so these
  // cases mirror that contract rather than handing every role the key.
  const adminModules = ["projects", "admin_overview", "execution", "communication", "users"];

  it.each(["super_admin", "admin"])("shows Portfolio for %s when the backend grants it", role => {
    expect(visibleTabs(adminModules, role).map(([key]) => key)).toContain("admin_overview");
  });

  it("labels the admin_overview tab \"Portfolio\", not \"Dashboard\"", () => {
    const entry = visibleTabs(adminModules, "admin").find(([key]) => key === "admin_overview");
    expect(entry?.[1]).toBe("Portfolio");
  });

  it.each(["project_manager", "supervisor", "internal_employee"])(
    "hides Portfolio for %s, whose module_permissions never include it",
    role => {
      expect(keysFor(role)).not.toContain("admin_overview");
    },
  );
});

describe("Communication (broadcasts) navigation visibility", () => {
  // Admin-only, same rationale and backend contract as admin_overview above.
  const adminModules = ["projects", "admin_overview", "execution", "communication", "broadcasts", "users"];

  it.each(["super_admin", "admin"])("shows Communication for %s when the backend grants it", role => {
    expect(visibleTabs(adminModules, role).map(([key]) => key)).toContain("broadcasts");
  });

  it("labels the broadcasts tab \"Communication\"", () => {
    const entry = visibleTabs(adminModules, "admin").find(([key]) => key === "broadcasts");
    expect(entry?.[1]).toBe("Communication");
  });

  it.each(["project_manager", "supervisor", "internal_employee"])(
    "hides Communication for %s, whose module_permissions never include it",
    role => {
      expect(keysFor(role)).not.toContain("broadcasts");
    },
  );
});

describe("Overview home tab", () => {
  it.each(["super_admin", "admin", "project_manager", "supervisor", "internal_employee"])("leads the navigation for %s", role => {
    expect(keysFor(role)[0]).toBe("overview");
  });

  it("is not duplicated if the backend ever grants it too", () => {
    expect(visibleTabs(["overview", ...modules], "admin").filter(([key]) => key === "overview")).toHaveLength(1);
  });
});
