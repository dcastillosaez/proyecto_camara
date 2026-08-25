"""API v2 — CRUD de reglas + POST /{id}/test (Fase 33, OPS-24, RULE-05, D-02).

La fuente de verdad de las reglas pasa de `config/rules.yaml` a la tabla `rules`
(`RuleRepo`), pero la validacion sigue apoyandose EXCLUSIVAMENTE en los modelos
Pydantic `Rule`/`When`/`Action` que el motor de reglas ya usa en produccion
(`backend/events/rules.py`) — nunca una validacion paralela que pudiera divergir.
`POST /{id}/test` (RULE-05) evalua una regla ya persistida contra los ultimos 500
eventos via `RuleEngine.would_match()`, puro, sin tocar el debounce real.

Auth y rate limiting: la app aplica auth globalmente (FastAPI(dependencies=[Depends(verify)])),
asi que este router la hereda automaticamente al incluirse con app.include_router() — no
hace falta Depends(verify) por ruta. El rate limit (SEC-16) usa el limiter/valor compartidos
de backend/api/v2/deps.py, mismo molde que config.py/events.py.

Shape de error 422: NUNCA el nativo de FastAPI (lista `[{"loc":...,"msg":...}]`) — el
parametro del POST es `body: dict[str, Any]` (JSON crudo), validado explicitamente contra
`RuleIn.model_validate()` dentro de un try/except ValidationError, relanzando
`HTTPException(422, detail={"errors": [{"field":..., "message":...}]})`, mismo patron ya
establecido en `backend/api/v2/config.py:219-220`. El frontend (`rules-editor.js`, Plan
33-12) mapea errores por `err.field` asumiendo exactamente este shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError, field_validator

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.database import get_session_factory
from backend.events.rules import Action, Rule, When
from backend.storage.repositories import EventRepo, RuleRepo

router = APIRouter(prefix="/api/v2/rules", tags=["rules"])

_rule_engine: Any = None


def configure(rule_engine: Any) -> None:
    """Wire the live RuleEngine instance. Called once from main.py's lifespan (Plan 33-08)."""
    global _rule_engine
    _rule_engine = rule_engine


def _rule_repo() -> RuleRepo:
    return RuleRepo(get_session_factory())


def _event_repo() -> EventRepo:
    return EventRepo(get_session_factory())


def rule_from_db_dict(row: dict[str, Any]) -> Rule:
    """Reconstruye el `Rule` Pydantic completo a partir de una fila de `rules` — `definition`
    es JSON crudo persistido, nunca se asume ya valido sin pasar por esta validacion
    (33-RESEARCH.md Pitfall 3)."""
    return Rule.model_validate({
        "name": row["name"],
        "enabled": row["enabled"],
        **row["definition"],
    })


async def _reload_engine(rule_repo: RuleRepo) -> None:
    """Recarga el motor de reglas en vivo tras cada mutacion. Cada fila corrupta se
    descarta individualmente (mismo espiritu defensivo que `load_rules()`), aunque en
    teoria no deberia ocurrir porque este router valida en escritura."""
    if _rule_engine is None:
        return
    rows = await rule_repo.list()
    valid: list[Rule] = []
    invalid: list[tuple[str, str]] = []
    for row in rows:
        try:
            valid.append(rule_from_db_dict(row))
        except ValidationError as exc:
            reason = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            invalid.append((row.get("name", row.get("id", "<sin nombre>")), reason))
    _rule_engine.reload(valid, invalid=invalid)


class RuleIn(BaseModel):
    id: str
    name: str
    enabled: bool = True
    when: When
    debounce_secs: float = 0.0
    actions: list[Action]

    @field_validator("actions")
    @classmethod
    def _at_least_one_action(cls, v: list[Action]) -> list[Action]:
        if not v:
            raise ValueError("at least one action required")
        return v


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_rules(request: Request) -> dict[str, Any]:
    return {"rules": await _rule_repo().list()}


@router.post("")
@limiter.limit(V2_RATE_LIMIT)
async def upsert_rule(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = RuleIn.model_validate(body)
    except ValidationError as e:
        errors = [
            {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in e.errors()
        ]
        raise HTTPException(422, detail={"errors": errors})

    rule_repo = _rule_repo()
    definition = {
        "when": parsed.when.model_dump(),
        "debounce_secs": parsed.debounce_secs,
        "actions": [a.model_dump() for a in parsed.actions],
    }
    await rule_repo.upsert(parsed.id, parsed.name, parsed.enabled, definition)
    await _reload_engine(rule_repo)
    return {"rules": await rule_repo.list()}


@router.delete("/{rule_id}")
@limiter.limit(V2_RATE_LIMIT)
async def delete_rule(request: Request, rule_id: str) -> dict[str, Any]:
    rule_repo = _rule_repo()
    deleted = await rule_repo.delete(rule_id)
    if not deleted:
        raise HTTPException(404, detail="Rule not found")
    await _reload_engine(rule_repo)
    return {"rules": await rule_repo.list()}


@router.post("/{rule_id}/test")
@limiter.limit(V2_RATE_LIMIT)
async def test_rule(request: Request, rule_id: str) -> dict[str, Any]:
    row = await _rule_repo().get(rule_id)
    if row is None:
        raise HTTPException(404, detail="Rule not found")
    rule = rule_from_db_dict(row)
    if _rule_engine is None:
        raise HTTPException(503, detail="Rule engine not available")
    items, _ = await _event_repo().query(limit=500)
    would_fire = sum(1 for e in items if _rule_engine.would_match(rule.when, e))
    return {"would_fire": would_fire, "total_checked": len(items)}
