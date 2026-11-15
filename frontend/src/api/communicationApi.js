import { api } from "./client";
export const communicationApi = {
  get: () => api("/api/communication-hub"),
  updateContractor: (contractorId, payload) => api(`/api/communication-hub/contractors/${contractorId}`, { method: "PUT", body: JSON.stringify(payload) }),
  addContact: (payload) => api("/api/communication-hub/contacts", { method: "POST", body: JSON.stringify(payload) }),
  // Work history: past projects entered by hand on a vendor's profile.
  addPastProject: (vendorId, payload) => api(`/api/communication-hub/vendors/${vendorId}/past-projects`, { method: "POST", body: JSON.stringify(payload) }),
  updatePastProject: (pastProjectId, payload) => api(`/api/communication-hub/past-projects/${pastProjectId}`, { method: "PUT", body: JSON.stringify(payload) }),
  deletePastProject: (pastProjectId) => api(`/api/communication-hub/past-projects/${pastProjectId}`, { method: "DELETE" }),
  // Capability categories are the flat siteops_v2 list seeded from template
  // phases - they are read through get() and are not hand-managed here, so
  // the legacy category create/update/delete endpoints no longer exist.
  linkSubcontractor: (payload) => api("/api/communication-hub/relationships", { method: "POST", body: JSON.stringify(payload) }),
  unlinkSubcontractor: (relationshipId) => api(`/api/communication-hub/relationships/${relationshipId}`, { method: "DELETE" }),
};