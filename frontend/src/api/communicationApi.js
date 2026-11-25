import { api } from "./client";
export const communicationApi = {
  get: () => api("/api/communication-hub"),
  updateContractor: (contractorId, payload) => api(`/api/communication-hub/contractors/${contractorId}`, { method: "PUT", body: JSON.stringify(payload) }),
  addContact: (payload) => api("/api/communication-hub/contacts", { method: "POST", body: JSON.stringify(payload) }),
  // The only vendor status: blacklisted (reason required). Removing it is Admin-only.
  blacklistVendor: (vendorId, reason) => api(`/api/communication-hub/vendors/${vendorId}/blacklist`, { method: "POST", body: JSON.stringify({ reason }) }),
  unblacklistVendor: (vendorId, reason) => api(`/api/communication-hub/vendors/${vendorId}/unblacklist`, { method: "POST", body: JSON.stringify({ reason }) }),
  // Work history: past projects entered by hand on a vendor's profile.
  addPastProject: (vendorId, payload) => api(`/api/communication-hub/vendors/${vendorId}/past-projects`, { method: "POST", body: JSON.stringify(payload) }),
  updatePastProject: (pastProjectId, payload) => api(`/api/communication-hub/past-projects/${pastProjectId}`, { method: "PUT", body: JSON.stringify(payload) }),
  deletePastProject: (pastProjectId) => api(`/api/communication-hub/past-projects/${pastProjectId}`, { method: "DELETE" }),
  // Feedback on a vendor's work on a finished SiteOps project.
  addFeedback: (vendorId, projectId, payload) => api(`/api/communication-hub/vendors/${vendorId}/projects/${projectId}/feedback`, { method: "POST", body: JSON.stringify(payload) }),
  updateFeedback: (feedbackId, payload) => api(`/api/communication-hub/feedback/${feedbackId}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteFeedback: (feedbackId) => api(`/api/communication-hub/feedback/${feedbackId}`, { method: "DELETE" }),
  pendingFeedback: () => api("/api/communication-hub/feedback/pending"),
  // Capability categories are the flat siteops_v2 list seeded from template
  // phases - they are read through get() and are not hand-managed here, so
  // the legacy category create/update/delete endpoints no longer exist.
  linkSubcontractor: (payload) => api("/api/communication-hub/relationships", { method: "POST", body: JSON.stringify(payload) }),
  unlinkSubcontractor: (relationshipId) => api(`/api/communication-hub/relationships/${relationshipId}`, { method: "DELETE" }),
};