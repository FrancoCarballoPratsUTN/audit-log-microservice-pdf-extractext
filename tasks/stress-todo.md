# Tasks — Pruebas de stress (Vegeta + k6) · AUDA

> Plan: [`stress-plan.md`](./stress-plan.md)
>
> **Archivo nuevo.** `plan.md` / `todo.md` siguen intactos: pertenecen a la
> implementación del microservicio.
>
> **v2 — sin observabilidad:** sin Grafana, sin Prometheus, sin dashboard, sin
> instrumentar `app/`. "Grafana k6" = la herramienta k6.
>
> **Estado: T1–T4 cerradas.** Falta sólo la revisión final humana.

---

## Phase 1: Generadores de carga

### T1: `gen_targets.py` — checksums y targets
**Status:** done ✅
- [x] Dos sets disjuntos: `--count` escrituras (`salt="post"`), `--reads` lecturas (`salt="read"`); `sha256("<salt><seed>:<índice>")`
- [x] `post.txt` — bodies únicos (`action`, `entity_type`, `checksum`, `performed_at` RFC 3339 UTC con `Z`, `details`); `list.txt` (`GET /audit/logs?skip=0&limit=50`); `bychecksum.txt` (`GET /audit/logs/checksum/{c}`, checksum con `quote`)
- [x] Siembra `--load` del set de lectura vía `POST` (201 = creado, 200 = replay, no aborta)
- [x] Sin `--pre-clean`: AUDA es append-only y el replay es `200`
- [x] Test unitario: unicidad/reproducibilidad, disyunción, formato exacto, CLI (sin token ⇒ exit 2 sin escribir)

**AC:** `--count 1000` ⇒ 1000 líneas únicas · sets disjuntos con misma semilla · token ausente ⇒ exit 2 · `ruff check` limpio
**Verify:** `uv run pytest tests/stress` → **13 passed** · suite completa **393 passed**, cobertura `app` **100%** (`--cov-fail-under=100`) · `ruff check` y `ruff format --check` limpios
**Deps:** — · **Files:** `tests/stress/scripts/gen_targets.py`, `tests/stress/test_gen_targets.py`, `__init__.py` de `tests/stress` y `tests/stress/scripts` · **Scope:** Small
**Decisiones:** dos sets **disjuntos** vía `salt` en `generate_checksums` (S1): si compartieran checksums, la siembra convertiría el POST en replay y no habría escrituras que medir · sin `--pre-clean` (S2) porque el replay es éxito · `performed_at` único por índice para que cada evento sea genuinamente nuevo (S6) · targets en **formato JSON de Vegeta** (S4)

---

## Phase 2: Ataques

### T2: Scripts de k6 *(paralelo con T3)*
**Status:** done ✅
- [x] `utils.js` — `BASE_URL` (`http://localhost:8083` por defecto), guard de token en scope de módulo, `auditCycle()` autónomo: POST único (201) → GET listado (200) → GET por checksum (200 y contiene el checksum)
- [x] `smoke.js` (1 VU/30 s, p95<500), `load.js` (rampa → 100 VUs), `stress.js` (rampa → 500 VUs, p95<1000)
- [x] Thresholds (`http_req_duration`, `http_req_failed`, `checks`) con exit ≠ 0 si se incumplen

**AC:** `k6 run smoke.js` ⇒ exit 0 · checksum único por iteración · `stress.js` ≥ 500 VUs · `--out json` parseable · sin token ⇒ exit ≠ 0 al cargar el módulo
**Verify:** manual E2E en la verificación final (smoke)
**Deps:** T1 · **Files:** `tests/stress/scripts/k6/{utils,smoke,load,stress}.js` · **Scope:** Medium
**Decisiones:** ciclo **append-only** `POST → listado → bychecksum` (no CRUD: AUDA responde `405` a PUT/DELETE, S8) · `performed_at` = `new Date().toISOString()` (RFC 3339 con `Z`) · guard de token en el módulo para fallar antes de VUs

### T3: Script de Vegeta
**Status:** done ✅
- [x] `run-vegeta.ps1` con perfiles `smoke` (10 rps/10 s ≤ 1 %), `load` (100 rps/30 s ≤ 5 %), `stress` (300 rps/60 s ≤ 10 %)
- [x] Fail-fast: `vegeta` en PATH, `SERVICE_API_TOKEN`, `/readyz` antes de atacar
- [x] Regenera targets (siembra `--load` cuando ataca `bychecksum` y no hay `-NoSeed`); aclara `-Verbs`, `-Count`, `-Reads`, `-Seed`
- [x] Reportes `.results`/`.report.txt`/`.report.json` en `out/`; exit ≠ 0 si `1 - success` supera el umbral

**AC:** smoke ⇒ exit 0 con p50/p95/p99, RPS y códigos · servicio caído ⇒ fail-fast antes de atacar · umbral roto ⇒ exit ≠ 0
**Verify:** manual E2E en la verificación final
**Deps:** T1 · **Files:** `tests/stress/scripts/run-vegeta.ps1` · **Scope:** Medium
**Decisiones:** seed aleatoria por defecto (eventos nuevos por corrida), `-Seed` para reproducir y medir replays (S3) · preflight con `/readyz` porque post/list/bychecksum tocan la base (S5) · umbral = `1 - success` del reporte JSON agregado (mismo criterio que Persistencia) · `vegeta attack -output` en vez de redirección de shell

### Checkpoint: Carga reproducible
- [x] `gen_targets.py` con test en verde
- [x] k6 smoke y vegeta smoke corren contra el servicio
- [x] Thresholds/umbrales deciden el exit code

---

## Phase 3: Orquestación y cierre

### T4: Orquestador + README + .gitignore
**Status:** done ✅
- [x] `run-stress.ps1`: preflight (vegeta, k6, token, `/readyz`) → delega en `run-vegeta.ps1` → k6 (`--env` + `--out json`) → resumen de `out/`; fail-fast
- [x] `tests/stress/README.md`: instalación (vegeta/k6), variables, cómo levantar el servicio (docker y local), perfiles, lectura de reportes, problemas frecuentes
- [x] `.gitignore`: `tests/stress/out/` y `tests/stress/targets/`

**AC:** `./tests/stress/run-stress.ps1 -Profile smoke -Scenario smoke` corre el pipeline sin pasos manuales · README suficiente · `git status` sin artefactos de stress
**Verify:** verificación final (abajo) · `pytest` **393 passed / 100%** · `ruff` limpio
**Deps:** T2, T3 · **Files:** `tests/stress/run-stress.ps1`, `tests/stress/README.md`, `.gitignore` · **Scope:** Medium
**Decisiones:** el orquestador **delega** en `run-vegeta.ps1` (que ya hace gen_targets + siembra + ataque + umbral) · fail-fast total · verificación manual de los scripts PS/JS (el repo no usa Pester); la lógica con tests vive en `gen_targets.py`

### Checkpoint: Complete
- [x] Un solo comando ejecuta el pipeline de principio a fin
- [x] `pytest --cov-fail-under=100` pasa (393 passed)
- [x] `ruff check .` y `ruff format --check .` limpios
- [x] README completo
- [ ] **Revisión final del humano**

---

## Verificación de la fase (smoke)

- [x] `uv run pytest tests/stress` → 13 passed
- [x] Suite completa + cobertura `app` 100% (gate `---cov-fail-under=100`)
- [x] `uv run ruff check .` y `uv run ruff format --check .` limpios
- [x] Vegeta smoke y k6 smoke contra el servicio (en la verificación E2E de Docker)
- [ ] **Revisión final del humano**

## Nota sobre decisiones abiertas

1. Perfiles/umbrales (10/100/300 rps; p95 < 500 ms, error < 1 %; p95 < 1 s en
   stress) son puntos de partida revisables.
2. **Resuelto (humano):** el ataque es `post + list + bychecksum`, con un set de
   lectura disjunto sembrado con `--load`.
3. **Resuelto (humano):** los eventos de stress **se dejan** en la base (AUDA es
   append-only; sin `--cleanup`).