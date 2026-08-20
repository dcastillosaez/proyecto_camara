// frontend/js/views/dashboard-observability.js

// ── Phase 16: health metrics ──────────────────────────────────────
function _fmtUptime(secs) {
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export async function loadHealth() {
  try {
    const res = await fetch('/api/health');
    if (!res.ok) return;
    const d = await res.json();
    document.getElementById('health-cpu').textContent    = d.cpu_percent >= 0 ? `${d.cpu_percent.toFixed(1)}%` : '–';
    document.getElementById('health-ram').textContent    = d.ram_percent >= 0 ? `${d.ram_percent.toFixed(1)}%` : '–';
    document.getElementById('health-fps').textContent    = `${d.fps}`;
    document.getElementById('health-uptime').textContent = _fmtUptime(d.uptime_secs);
    document.getElementById('health-updated').textContent = new Date().toLocaleTimeString();
  } catch {}
}

// ── Fase 21: métricas de observabilidad ───────────────────────────
function _gaugeValue(snapshot, name, labelKey) {
  const series = snapshot.gauges && snapshot.gauges[name];
  if (!series) return null;
  if (labelKey !== undefined) return series[labelKey];
  const values = Object.values(series);
  return values.length ? values[0] : null;
}

function _counterSum(snapshot, name) {
  const series = snapshot.counters && snapshot.counters[name];
  if (!series) return null;
  return Object.values(series).reduce((a, b) => a + b, 0);
}

export async function loadObservability() {
  try {
    const res = await fetch('/api/v2/metrics');
    if (!res.ok) return;
    const d = await res.json();

    const cam = _gaugeValue(d, 'capture_fps', "{'camera': 'cam1'}");
    const det = _gaugeValue(d, 'detection_fps', "{'camera': 'cam1'}");
    const face = _gaugeValue(d, 'face_fps', "{'camera': 'cam1'}");
    const dropped = _counterSum(d, 'frames_dropped_total');
    const recQ = _gaugeValue(d, 'recording_queue_depth');
    const upQ = _gaugeValue(d, 'upload_queue_depth');

    document.getElementById('obs-capture-fps').textContent = cam != null ? `${cam.toFixed(1)} FPS` : '–';
    document.getElementById('obs-detection-fps').textContent = det != null ? `${det.toFixed(1)} FPS` : '–';
    document.getElementById('obs-face-fps').textContent = face != null ? `${face.toFixed(1)} FPS` : '–';
    document.getElementById('obs-dropped').textContent = dropped != null ? `${dropped}` : '–';
    document.getElementById('obs-queues').textContent = (recQ != null && upQ != null) ? `${recQ} / ${upQ}` : '–';

    const pct = d.e2e_percentiles;
    document.getElementById('obs-latency').textContent = pct
      ? `${pct.p50.toFixed(2)}s / ${pct.p95.toFixed(2)}s`
      : '–';

    document.getElementById('obs-updated').textContent = new Date().toLocaleTimeString();
  } catch {}
}
