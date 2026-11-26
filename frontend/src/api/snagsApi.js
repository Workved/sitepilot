import { api, fetchBinary } from "./client";

const json = body => JSON.stringify(body);

export const snagsApi = {
  list: projectId => api(`/api/v2/projects/${projectId}/snags`),
  create: (projectId, payload) => api(`/api/v2/projects/${projectId}/snags`, { method: "POST", body: json(payload) }),
  update: (snagId, changes) => api(`/api/v2/snags/${snagId}`, { method: "PATCH", body: json(changes) }),
  setStatus: (snagId, status, closingNote) => api(`/api/v2/snags/${snagId}/status`, { method: "POST", body: json({ status, closing_note: closingNote || null }) }),
  remove: snagId => api(`/api/v2/snags/${snagId}`, { method: "DELETE" }),
  taggedToMe: () => api("/api/v2/snags/tagged-to-me"),
  people: () => api("/api/v2/snags/people"),
  addFile: (snagId, file) => {
    const body = new FormData();
    body.append("file", file);
    return api(`/api/v2/snags/${snagId}/files`, { method: "POST", body });
  },
  downloadFile: (snagId, fileId) => fetchBinary(`/api/v2/snags/${snagId}/files/${fileId}`),
  removeFile: (snagId, fileId) => api(`/api/v2/snags/${snagId}/files/${fileId}`, { method: "DELETE" }),
};
