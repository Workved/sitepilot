/*
 * Pure helpers for the Team (Users & Access) page: what needs attention,
 * filtering, sorting and the header line. Kept out of the components so the
 * rules can be tested on their own.
 */

// Roles that can be put on a project, and so need an employee profile
// (projects_v2 refuses a PM/Supervisor without one).
export const PROJECT_ROLES = new Set(["project_manager", "supervisor", "internal_employee"]);

export const ROLE_ORDER = ["super_admin", "admin", "project_manager", "supervisor", "internal_employee"];

export const STATUS_FILTERS = [
  ["active", "Has access"],
  ["setup_pending", "Setup pending"],
  ["offboarded", "Offboarded"],
  ["all", "All"],
];

// Things an admin can fix. Only active people count: an offboarded account
// missing a phone number is not a problem anyone needs to solve.
export const ATTENTION = [
  ["not_signed_in", "haven't signed in", "hasn't signed in", person => person.active && person.activation_status === "setup_pending"],
  // WhatsApp carries task, gate and approval alerts - the people who run
  // projects need it; admins without a number are not a problem.
  ["no_phone", "no mobile number", "no mobile number", person => person.active && PROJECT_ROLES.has(person.role) && !person.phone],
  ["no_profile", "can't be put on a project", "can't be put on a project", person => person.active && PROJECT_ROLES.has(person.role) && !person.employee_profile],
];

export function attentionFor(person) {
  return ATTENTION.filter(([, , , test]) => test(person)).map(([key]) => key);
}

export function statusOf(person) {
  if (!person.active) return "offboarded";
  return person.activation_status === "setup_pending" ? "setup_pending" : "active";
}

export function matchesStatus(person, filter) {
  if (filter === "all") return true;
  const status = statusOf(person);
  // "Active" means "has access", so people still to sign in are included.
  if (filter === "active") return status !== "offboarded";
  return status === filter;
}

export function filterPeople(people, { query = "", role = "all", status = "active", attention = "" } = {}) {
  const needle = query.trim().toLowerCase();
  const test = attention ? ATTENTION.find(([key]) => key === attention)?.[3] : null;
  return people.filter(person => {
    if (role !== "all" && person.role !== role) return false;
    if (!matchesStatus(person, status)) return false;
    if (test && !test(person)) return false;
    if (!needle) return true;
    const profile = person.employee_profile || {};
    return [person.name, person.email, person.phone, profile.employee_code, profile.designation, profile.department]
      .some(value => String(value || "").toLowerCase().includes(needle));
  });
}

export function sortPeople(people, key = "name", direction = "asc") {
  const sign = direction === "desc" ? -1 : 1;
  const byName = (a, b) => a.name.localeCompare(b.name);
  return [...people].sort((a, b) => {
    if (key === "role") return (ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role)) * sign || byName(a, b);
    if (key === "last_active") {
      // Never signed in sorts as the oldest possible activity.
      const left = a.last_login_at ? new Date(a.last_login_at).getTime() : 0;
      const right = b.last_login_at ? new Date(b.last_login_at).getTime() : 0;
      return (left - right) * sign || byName(a, b);
    }
    return byName(a, b) * sign;
  });
}

export function summaryLine(people) {
  if (!people.length) return "No one here yet. Add your first team member.";
  const active = people.filter(person => statusOf(person) === "active").length;
  const pending = people.filter(person => statusOf(person) === "setup_pending").length;
  const offboarded = people.filter(person => statusOf(person) === "offboarded").length;
  const parts = [`${people.length} ${people.length === 1 ? "person" : "people"}`, `${active} active`];
  if (pending) parts.push(`${pending} ${pending === 1 ? "hasn't" : "haven't"} signed in yet`);
  if (offboarded) parts.push(`${offboarded} offboarded`);
  return parts.join(", ");
}
