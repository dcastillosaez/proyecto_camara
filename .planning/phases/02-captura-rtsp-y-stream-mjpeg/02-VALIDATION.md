---
phase: 2
slug: captura-rtsp-y-stream-mjpeg
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-16
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | none — ya instalado en Phase 1 |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/ -q --tb=short` |
| **Full suite command** | `.venv/Scripts/python -m pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/Scripts/python -m pytest tests/ -q --tb=short`
- **After every plan wave:** Run `.venv/Scripts/python -m pytest tests/ -v --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | CAP-01 | unit | `pytest tests/test_stream.py -q` | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 1 | CAP-02 | unit | `pytest tests/test_stream.py::test_reconnection -q` | ❌ W0 | ⬜ pending |
| 2-02-01 | 02 | 2 | CAP-03 | integration | `python -c "import httpx; r=httpx.get('http://localhost:8000/video_feed',timeout=5); print(r.status_code)"` | manual | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_stream.py` — stubs para CAP-01, CAP-02 (drain thread, reconexión)
- [ ] `tests/conftest.py` — fixtures compartidos (mock de cv2.VideoCapture)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Stream MJPEG visible en navegador con <2s latencia | CAP-03 | Requiere cámara real o navegador | Abrir http://localhost:8000/video_feed en Chrome, verificar video en directo |
| Reconexión tras desconectar cámara | CAP-02 | Requiere hardware real | Desconectar cámara, esperar mensaje de reconexión en logs, reconectar |
| Sin acumulación de latencia tras 10 min | CAP-01 | Requiere prueba temporal | Correr stream 10 min, verificar que latencia no aumenta progresivamente |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
