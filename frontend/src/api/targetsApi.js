import { api } from "./client";

const json = body => JSON.stringify(body);

export const targetsApi = {
  list: projectId => api(`/api/v2/projects/${projectId}/targets`),
  create: (projectId, payload) => api(`/api/v2/projects/${projectId}/targets`, { method: "POST", body: json(payload) }),
  update: (targetId, changes) => api(`/api/v2/targets/${targetId}`, { method: "PATCH", body: json(changes) }),
  clear: targetId => api(`/api/v2/targets/${targetId}/clear`, { method: "POST" }),
  setAchieved: (targetId, achieved) => api(`/api/v2/targets/${targetId}/achieved`, { method: "POST", body: json({ achieved }) }),
  scheduleChanges: projectId => api(`/api/v2/projects/${projectId}/schedule-changes`),
};
