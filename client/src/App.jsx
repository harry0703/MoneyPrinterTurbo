import React, { useState, useEffect } from 'react'
import api from './api2'

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '')
  const [me, setMe] = useState(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [leads, setLeads] = useState([])
  const [name, setName] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [changing, setChanging] = useState(false)

  useEffect(() => { if (token) { fetchMe(); fetchLeads() } }, [token])

  const [adminSecret, setAdminSecret] = useState('')

  async function register() {
    await api.register({ email, password, name, adminSecret })
    alert('Registro creado — ahora inicia sesión')
  }

  async function login() {
    const res = await api.login({ email, password })
    if (res.token) { localStorage.setItem('token', res.token); setToken(res.token); }
  }

  async function fetchMe() {
    try {
      const info = await api.getMe(token)
      setMe(info)
    } catch (e) { setMe(null) }
  }

  async function fetchLeads() {
    const res = await api.getLeads(token)
    setLeads(res || [])
  }

  async function addLead() {
    await api.createLead(token, { name, source: 'web' })
    setName('')
    fetchLeads()
  }

  async function sendWA(lead) {
    await api.sendWhatsApp(token, { to: lead.whatsapp || lead.phone, message: `Hola ${lead.name}, te contacto sobre nuestras páginas web profesionales.` })
    alert('Mensaje enviado (mock)')
  }

  async function exportCSV() {
    try {
      const blob = await api.exportLeads(token)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'leads.csv'
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) { alert('Error exporting CSV') }
  }

  async function changePassword() {
    if (!currentPassword || !newPassword) { alert('Rellena ambos campos'); return }
    setChanging(true)
    try {
      await api.changePassword(token, { currentPassword, newPassword })
      alert('Contraseña cambiada')
      setCurrentPassword('')
      setNewPassword('')
    } catch (e) {
      alert('Error cambiando contraseña')
    } finally { setChanging(false) }
  }

  if (!token) return (
    <div style={{ padding: 20 }}>
      <h2>Telemarketing MVP — Login / Register</h2>
      <input placeholder="Nombre" value={name} onChange={e => setName(e.target.value)} />
      <input placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} />
      <input placeholder="Password" type="password" value={password} onChange={e => setPassword(e.target.value)} />
      <input placeholder="Admin secret (opcional, para crear admin)" value={adminSecret} onChange={e => setAdminSecret(e.target.value)} />
      <div style={{ marginTop: 10 }}>
        <button onClick={register}>Registrar</button>
        <button onClick={login}>Iniciar sesión</button>
      </div>
    </div>
  )

  return (
    <div style={{ padding: 20 }}>
      <h2>Pipeline — Leads</h2>
      <div>
        <input placeholder="Nuevo lead (nombre)" value={name} onChange={e => setName(e.target.value)} />
        <button onClick={addLead}>Agregar</button>
        <button onClick={() => { localStorage.removeItem('token'); setToken(''); setLeads([]); setMe(null) }}>Cerrar sesión</button>
        {me && me.role === 'admin' && (
          <button onClick={exportCSV} style={{ marginLeft: 8 }}>Exportar CSV (admin)</button>
        )}
      </div>

      <div style={{ marginTop: 12 }}>
        <h4>Cambiar contraseña</h4>
        <input placeholder="Contraseña actual" type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} />
        <input placeholder="Nueva contraseña" type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} />
        <button onClick={changePassword} disabled={changing}>{changing ? 'Cambiando...' : 'Cambiar contraseña'}</button>
      </div>

      <ul>
        {leads.map(l => (
          <li key={l.id} style={{ margin: '8px 0' }}>
            <strong>{l.name}</strong> — {l.stage}
            <button onClick={() => sendWA(l)} style={{ marginLeft: 8 }}>Enviar WhatsApp</button>
          </li>
        ))}
      </ul>
    </div>
  )
}
