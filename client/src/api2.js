import axios from 'axios'

const BASE = process.env.VITE_API_BASE || 'http://localhost:4000'

export default {
  register: async (data) => { const r = await axios.post(`${BASE}/auth/register`, data); return r.data },
  login: async (data) => { const r = await axios.post(`${BASE}/auth/login`, data); return r.data },
  getMe: async (token) => { const r = await axios.get(`${BASE}/me`, { headers: { Authorization: `Bearer ${token}` } }); return r.data },
  getLeads: async (token) => { const r = await axios.get(`${BASE}/leads`, { headers: { Authorization: `Bearer ${token}` } }); return r.data },
  createLead: async (token, data) => { const r = await axios.post(`${BASE}/leads`, data, { headers: { Authorization: `Bearer ${token}` } }); return r.data },
  sendWhatsApp: async (token, data) => { const r = await axios.post(`${BASE}/send/whatsapp`, data, { headers: { Authorization: `Bearer ${token}` } }); return r.data },
  exportLeads: async (token) => { const r = await axios.get(`${BASE}/leads/export`, { headers: { Authorization: `Bearer ${token}` }, responseType: 'blob' }); return r.data },
  changePassword: async (token, data) => { const r = await axios.put(`${BASE}/auth/password`, data, { headers: { Authorization: `Bearer ${token}` } }); return r.data },
  adminChangePassword: async (token, id, data) => { const r = await axios.put(`${BASE}/users/${id}/password`, data, { headers: { Authorization: `Bearer ${token}` } }); return r.data }
}
