// frontend/js/websocket.js
import { updateStat, setWsConnected, renderPersonList, showToast } from './views/dashboard.js';
import { updateChart, addEvent, hourlyToArray, bumpHourBar } from './views/dashboard-events.js';
import { addRecording, updateRecordingStatus } from './components/eventCard.js';
import { setRecBadge, drawTracks } from './components/videoCanvas.js';

let _ws = null;
let _wsRetry = 1000;
let _wsCloseCount = 0;

function setWsStatus(connected) {
  const badge = document.getElementById('ws-badge');
  const label = document.getElementById('ws-label');
  const icon  = document.getElementById('ws-icon');
  if (connected) {
    badge.className = 'flex-shrink-0 text-xs px-2.5 py-1 rounded-full bg-green-500/10 text-green-400 border border-green-500/30 font-medium';
    badge.textContent = 'Activo';
    label.textContent = 'Eventos en tiempo real';
    icon.className = icon.className.replace('border-slate-700', 'border-green-500/30');
  } else {
    badge.className = 'flex-shrink-0 text-xs px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30 font-medium';
    badge.textContent = 'Reconectando';
    label.textContent = 'Intentando reconectar…';
    icon.className = icon.className.replace('border-green-500/30', 'border-slate-700');
  }
}

export async function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let wsUrl = `${proto}//${location.host}/ws`;
  try {
    const res = await fetch('/api/ws-token');
    if (res.ok) {
      const { token } = await res.json();
      if (token) wsUrl += `?token=${token}`;
    }
  } catch (_) {}
  _ws = new WebSocket(wsUrl);

  _ws.onopen = () => {
    _wsRetry = 1000;
    setWsStatus(true);
    _wsCloseCount = 0;
    setWsConnected(true, 0);
  };

  _ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'init') {
      updateChart(hourlyToArray(msg.hourly));
      updateStat('stat-total', msg.total_today ?? 0);
    } else if (msg.type === 'detection') {
      const ts = new Date(msg.timestamp).toLocaleTimeString('es-ES', { hour12: false });
      addEvent(ts, msg.direction, msg.total_today, msg.person_name ?? null, msg.is_intrusion ?? false);
      updateStat('stat-total', msg.total_today);
      bumpHourBar(new Date(msg.timestamp).getHours());
      const who = msg.person_name ? ` — ${msg.person_name}` : '';
      const intrusionSuffix = msg.is_intrusion ? ' ⚠ INTRUSIÓN' : '';
      showToast(`Cruce ${msg.direction.toUpperCase()} detectado${who}${intrusionSuffix}`, msg.is_intrusion ? 'error' : 'success', 2000);
    } else if (msg.type === 'recording_started') {
      addRecording({ id: msg.id, filename: msg.filename, upload_status: 'pending', created_at: new Date().toISOString() });
      setRecBadge(true);
      showToast(`Grabando: ${msg.filename}`, 'info', 3000);
    } else if (msg.type === 'recording_uploaded') {
      updateRecordingStatus(msg.filename, 'uploaded', msg.gdrive_id);
      setRecBadge(false);
    } else if (msg.type === 'recording_failed') {
      updateRecordingStatus(msg.filename, 'failed');
      setRecBadge(false);
    } else if (msg.type === 'tracks') {
      drawTracks(msg.tracks);
      renderPersonList(msg.tracks);
    }
  };

  _ws.onclose = () => {
    _wsCloseCount += 1;
    setWsConnected(false, _wsCloseCount);
    setWsStatus(false);
    setTimeout(connectWS, _wsRetry);
    _wsRetry = Math.min(_wsRetry * 2, 30000);
  };

  _ws.onerror = () => _ws.close();
}
