import { api, fetchBinary } from "./client";

// Flat function-per-route client for execution_tasks_v2.py, mirroring
// projectsApi.js's pattern - kept as its own client since these endpoints
// live under a separate backend router.
export const taskExecutionApi = {
  list: projectId => api(`/api/v2/projects/${projectId}/tasks`),
  detail: (projectId, taskId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}`),
  transitionStatus: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/status`, { method: "POST", body: JSON.stringify(payload) }),
  submitProgress: (projectId, taskId, formData) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/progress`, { method: "POST", body: formData }),
  downloadEvidence: (projectId, taskId, fileId) => fetchBinary(`/api/v2/projects/${projectId}/tasks/${taskId}/evidence/${fileId}`),
  // Admin reference material from the pinned template version (not evidence).
  downloadTaskReference: (projectId, taskId, referenceId) => fetchBinary(`/api/v2/projects/${projectId}/tasks/${taskId}/reference-files/${referenceId}`),
  verify: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/verify`, { method: "POST", body: JSON.stringify(payload) }),
  approve: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/approve`, { method: "POST", body: JSON.stringify(payload) }),
  logBlocker: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/blockers`, { method: "POST", body: JSON.stringify(payload) }),
  resolveBlocker: (projectId, taskId, blockerId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/blockers/${blockerId}/resolve`, { method: "POST" }),
  logDelay: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/delays`, { method: "POST", body: JSON.stringify(payload) }),
  // U18: the EXECUTION-layer approvals, not projectsApi.externalGates. That
  // one reads the planning-layer gate and its Draft-time applicability
  // review; this one answers the runtime question the Execution tab asks -
  // has the approval been granted, does it still block, and which tasks does
  // it cover. Read access is any active project member; deciding is PM/Admin.
  // Formal change to a task's planned dates; a reason is required and it is audited.
  reschedule: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/reschedule`, { method: "POST", body: JSON.stringify(payload) }),
  listExternalApprovals: projectId => api(`/api/v2/projects/${projectId}/external-approvals`),
  decideExternalApproval: (projectId, approvalId, payload) => api(`/api/v2/projects/${projectId}/external-approvals/${approvalId}/decision`, { method: "POST", body: JSON.stringify(payload) }),
  assignExternalApproval: (projectId, approvalId, payload) => api(`/api/v2/projects/${projectId}/external-approvals/${approvalId}/assign`, { method: "POST", body: JSON.stringify(payload) }),
  reassignExternalApproval: (projectId, approvalId, payload) => api(`/api/v2/projects/${projectId}/external-approvals/${approvalId}/reassign`, { method: "POST", body: JSON.stringify(payload) }),
  unassignExternalApproval: (projectId, approvalId) => api(`/api/v2/projects/${projectId}/external-approvals/${approvalId}/unassign`, { method: "POST" }),
  submitExternalApprovalEvidence: (projectId, approvalId, formData) => api(`/api/v2/projects/${projectId}/external-approvals/${approvalId}/submission`, { method: "POST", body: formData }),
  downloadExternalApprovalEvidence: (projectId, approvalId, fileId) => fetchBinary(`/api/v2/projects/${projectId}/external-approvals/${approvalId}/evidence/${fileId}`),
  downloadApprovalReference: (projectId, approvalId, referenceId) => fetchBinary(`/api/v2/projects/${projectId}/external-approvals/${approvalId}/reference-files/${referenceId}`),
  assignSupport: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/support-assignments`, { method: "POST", body: JSON.stringify(payload) }),
  endSupportAssignment: (projectId, taskId, assignmentId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/support-assignments/${assignmentId}/end`, { method: "POST", body: JSON.stringify(payload) }),
};
