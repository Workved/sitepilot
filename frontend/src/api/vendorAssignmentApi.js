import { api } from "./client";

// Flat function-per-route client for project_vendors_v2.py, mirroring
// projectsApi.js/taskExecutionApi.js's pattern - kept as its own client
// since these endpoints live under a separate backend router.
export const vendorAssignmentApi = {
  listVendors: () => api("/api/v2/vendors"),
  listCapabilityCategories: () => api("/api/v2/vendors/capability-categories"),
  setVendorCapabilities: (vendorId, categoryIds) => api(`/api/v2/vendors/${vendorId}/capabilities`, { method: "POST", body: JSON.stringify({ category_ids: categoryIds }) }),
  listProjectVendors: (projectId, { includeEnded = false } = {}) => api(`/api/v2/projects/${projectId}/vendors${includeEnded ? "?include_ended=true" : ""}`),
  mapVendor: (projectId, payload) => api(`/api/v2/projects/${projectId}/vendors`, { method: "POST", body: JSON.stringify(payload) }),
  removeProjectVendor: (projectId, vendorId, payload) => api(`/api/v2/projects/${projectId}/vendors/${vendorId}/remove`, { method: "POST", body: JSON.stringify(payload) }),
  listTaskVendorAssignments: (projectId, taskId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignments`),
  delegateTask: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignment`, { method: "POST", body: JSON.stringify(payload) }),
  unassignTask: (projectId, taskId, assignmentId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignment/${assignmentId}/unassign`, { method: "POST", body: JSON.stringify(payload) }),
  // A vendor's people on a project (optionally per trade) and a task's point person.
  attachContact: (projectId, payload) => api(`/api/v2/projects/${projectId}/vendor-contacts`, { method: "POST", body: JSON.stringify(payload) }),
  endContactAttachment: (projectId, attachmentId) => api(`/api/v2/projects/${projectId}/vendor-contacts/${attachmentId}/end`, { method: "POST" }),
  setTaskPointPerson: (projectId, taskId, assignmentId, contactId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignment/${assignmentId}/contact`, { method: "PUT", body: JSON.stringify({ contact_id: contactId }) }),
  acknowledge: (projectId, taskId, assignmentId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignment/${assignmentId}/acknowledge`, { method: "POST", body: JSON.stringify(payload) }),
};
