import { api } from "./client";

function referenceForm(file, description) {
  const body = new FormData();
  body.append("file", file);
  if (description?.trim()) body.append("description", description.trim());
  return body;
}

function query(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  return search.toString() ? `?${search}` : "";
}

export const projectsApi = {
  list: params => api(`/api/v2/projects${query(params)}`),
  // Both of these are additive read models the list view degrades without:
  // ProjectsPage treats a rejection as "no data yet" and hides the progress,
  // phase and attention affordances rather than failing the page. Remove the
  // fallbacks once the endpoints ship.
  summaries: () => api("/api/v2/projects/summaries"),
  // Portfolio calendar: one row per visible project (dates, progress, health).
  timeline: () => api("/api/v2/projects/timeline"),
  attention: () => api("/api/v2/projects/attention"),
  references: () => api("/api/v2/projects/reference-data"),
  publishedTemplates: () => api("/api/v2/projects/published-template-versions"),
  detail: projectId => api(`/api/v2/projects/${projectId}`),
  activity: projectId => api(`/api/v2/projects/${projectId}/activity`),
  dashboard: projectId => api(`/api/v2/projects/${projectId}/dashboard`),
  generateReport: (projectId, payload) => api(`/api/v2/projects/${projectId}/reports`, { method: "POST", body: JSON.stringify(payload) }),
  reports: (projectId, params = {}) => api(`/api/v2/projects/${projectId}/reports${query(params)}`),
  executionTasks: projectId => api(`/api/v2/projects/${projectId}/execution-tasks`),
  create: payload => api("/api/v2/projects", { method: "POST", body: JSON.stringify(payload) }),
  generateTasks: projectId => api(`/api/v2/projects/${projectId}/generate-tasks`, { method: "POST" }),
  generateGates: projectId => api(`/api/v2/projects/${projectId}/generate-gates`, { method: "POST" }),
  generateDependencies: projectId => api(`/api/v2/projects/${projectId}/generate-dependencies`, { method: "POST" }),
  dependencies: (projectId, params = {}) => api(`/api/v2/projects/${projectId}/dependencies${query(params)}`),
  createDependency: (projectId, payload) => api(`/api/v2/projects/${projectId}/dependencies`, { method: "POST", body: JSON.stringify(payload) }),
  externalGates: projectId => api(`/api/v2/projects/${projectId}/external-gates`),
  decideGateApplicability: (projectId, gateId, payload) => api(`/api/v2/projects/${projectId}/gates/${gateId}/applicability-decisions`, { method: "POST", body: JSON.stringify(payload) }),
  gateApplicabilityHistory: (projectId, gateId) => api(`/api/v2/projects/${projectId}/gates/${gateId}/applicability-decisions`),
  templateReviewTasks: (projectId, params = {}) => api(`/api/v2/projects/${projectId}/template-review/tasks${query(params)}`),
  templateReviewSummary: projectId => api(`/api/v2/projects/${projectId}/template-review/summary`),
  taskClassification: projectId => api(`/api/v2/projects/${projectId}/task-classification`),
  updateTaskClassification: (projectId, items) => api(`/api/v2/projects/${projectId}/task-classification`, { method: "PUT", body: JSON.stringify({ items }) }),
  decideTaskApplicability: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/applicability-decisions`, { method: "POST", body: JSON.stringify(payload) }),
  taskApplicabilityHistory: (projectId, taskId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/applicability-decisions`),
  createManualTask: (projectId, payload) => api(`/api/v2/projects/${projectId}/tasks`, { method: "POST", body: JSON.stringify(payload) }),
  addRunningTask: (projectId, payload) => api(`/api/v2/projects/${projectId}/running-tasks`, { method: "POST", body: JSON.stringify(payload) }),
  // Reference material added on the project (not the template).
  addTaskReference: (projectId, taskId, { file, description }) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/reference-files`, { method: "POST", body: referenceForm(file, description) }),
  addProjectTaskReference: (projectId, projectTaskId, { file, description }) => api(`/api/v2/projects/${projectId}/project-tasks/${projectTaskId}/reference-files`, { method: "POST", body: referenceForm(file, description) }),
  removeTaskReference: (projectId, referenceId) => api(`/api/v2/projects/${projectId}/task-reference-files/${referenceId}`, { method: "DELETE" }),
  createManualGate: (projectId, payload) => api(`/api/v2/projects/${projectId}/gates`, { method: "POST", body: JSON.stringify(payload) }),
  update: (projectId, payload) => api(`/api/v2/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  setMembership: (projectId, payload) => api(`/api/v2/projects/${projectId}/memberships`, { method: "POST", body: JSON.stringify(payload) }),
  team: projectId => api(`/api/v2/projects/${projectId}/team`),
  updateTeam: (projectId, payload) => api(`/api/v2/projects/${projectId}/team`, { method: "PATCH", body: JSON.stringify(payload) }),
  endMembership: (projectId, membershipId, reason) => api(`/api/v2/projects/${projectId}/memberships/${membershipId}/end`, { method: "POST", body: JSON.stringify({ reason }) }),
  // U6: PM/Supervisor changes are a two-step request/approval flow
  // (BR-007) - requesting no longer takes immediate effect.
  requestRoleChange: (projectId, payload) => api(`/api/v2/projects/${projectId}/role-changes`, { method: "POST", body: JSON.stringify(payload) }),
  roleChanges: (projectId, status) => api(`/api/v2/projects/${projectId}/role-changes${status ? `?status=${status}` : ""}`),
  approveRoleChange: (projectId, changeId) => api(`/api/v2/projects/${projectId}/role-changes/${changeId}/approve`, { method: "POST" }),
  rejectRoleChange: (projectId, changeId, reason) => api(`/api/v2/projects/${projectId}/role-changes/${changeId}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  reassignmentRequired: projectId => api(`/api/v2/projects/${projectId}/role-changes/reassignment-required`),
  setStatus: (projectId, status, reason) => api(`/api/v2/projects/${projectId}/status`, { method: "POST", body: JSON.stringify({ status, reason }) }),
  // Draft -> active must go through the dedicated /activate route, not
  // /status: only /activate emits the project.activated outbox event that
  // drives the WhatsApp notification (backend/app/routes/projects_v2.py).
  // /status's own draft->active branch flips the same fields but was left
  // deliberately unmodified when /activate was added, so it never notifies.
  activate: (projectId, reason) => api(`/api/v2/projects/${projectId}/activate`, { method: "POST", body: JSON.stringify({ reason }) }),
  // Archived is terminal in setStatus; this is the only way back out of it.
  restore: (projectId, reason) => api(`/api/v2/projects/${projectId}/restore`, { method: "POST", body: JSON.stringify({ reason }) }),
  remove: (projectId, payload) => api(`/api/v2/projects/${projectId}`, { method: "DELETE", body: JSON.stringify(payload) }),
};
