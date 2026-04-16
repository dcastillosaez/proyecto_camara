---
phase: 1
slug: scaffolding-y-entorno
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-16
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (a instalar en esta fase) |
| **Config file** | none — Wave 0 installs |
| **Quick run command** | `pytest tests/ -v` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -v`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | SC-01 (venv) | smoke | `python -c "import fastapi, cv2, ultralytics, supervision"` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | SC-02 (dirs) | smoke | `ls backend/main.py frontend/index.html tests/test_detector.py data/.gitkeep` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | SC-03 (.env) | smoke | `grep -c '=' .env.example` (expect 5) | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 1 | config | smoke | `python -c "from backend.config import get_settings"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pytest` y `httpx` en requirements.txt
- [ ] Archivos test placeholder en `tests/`

*Existing infrastructure covers remaining phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Venv activation | SC-01 | Shell-dependent activation path | Run `.venv/Scripts/activate` (Windows) and verify `python --version` shows 3.12.x |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
