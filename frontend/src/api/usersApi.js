import { api } from "./client";

export const usersApi = {
  access: () => api("/api/users/access"),
  events: userId => api(`/api/users/${userId}/events`),
  invite: payload => api("/api/users/invite", { method: "POST", body: JSON.stringify(payload) }),
  update: (userId, payload) => api(`/api/users/${userId}`, { method: "PUT", body: JSON.stringify(payload) }),
  setPassword: (userId, password) => api(`/api/users/${userId}/password`, { method: "PUT", body: JSON.stringify({ password }) }),
  updateMe: payload => api("/api/users/me/profile", { method: "PUT", body: JSON.stringify(payload) }),
  setActive: (userId, active) => api(`/api/users/${userId}/active?active=${active}`, { method: "PATCH" }),
  offboard: (userId, reason) => api(`/api/users/${userId}/offboard`, { method: "POST", body: JSON.stringify({ reason }) }),
  restore: (userId, reason) => api(`/api/users/${userId}/restore`, { method: "POST", body: JSON.stringify({ reason }) }),
  remove: (userId, payload) => api(`/api/users/${userId}`, { method: "DELETE", body: JSON.stringify(payload) }),
};

