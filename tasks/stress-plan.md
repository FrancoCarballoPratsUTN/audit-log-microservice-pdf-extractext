# Implementation Plan: Pruebas de stress con Vegeta y k6 (AUDA)

> **Archivo nuevo.** `tasks/plan.md` y `tasks/todo.md` pertenecen a la
> implementación del microservicio y **no se han tocado**.
>
> **Estado:** implementado y verificado (10-oct-2026).
>
> **v2 — sin observabilidad.** Decisión humana: **sin Grafana, sin Prometheus,
> sin dashboard, sin instrumentar `app/`.** Sólo la prueba de stress en sí
> (Vegeta + k6). "Grafana k6" = la herramienta k6 de Grafana Labs.

## Overview

Batería de pruebas de stress para AUDA alojada en `tests/stress/` con los
scripts en `tests/stress/scripts/`. Dos herramientas, cero infraestructura:

- **Vegeta** — ataque HTTP a tasa constante contra `post`, `list` y
  `bychecksum`, con targets pre-generados. Reporte de p50/p95/p99, RPS y códigos
  en `tests/stress/out/`.
- **k6** — escenarios con rampas (smoke/load/stress) y **thresholds** que hacen
  salir con código ≠ 0 si se incumplen.

No se toca `app/`. Los scripts viven en `tests/` porque la lógica pura
(`gen_targets.py`) tiene sus tests de pytest; los scripts PowerShell y JS se
verifican manualmente (el repo no usa Pester).

## Contrato que modela el arnés

AUDA es **append-only**: `PUT`/`DELETE` sobre `/audit/logs` responden `405` y el
`POST` es **idempotente** (misma pareja `checksum` + `performed_at` ⇒ `200` con
`X-Idempotent-Replay`). Las lecturas devuelven **un array vacío** (`[]`), nunca
`404`, cuando no hay coincidencias. Consecuencias:

- No existe ciclo `POST → … → DELETE`: el ataque es `post → list → bychecksum`.
- No hay `--pre-clean`: un evento repetido es `200` (éxito), no `409`.
- El `GET /audit/logs/checksum/{c}` necesita datos sembrados para medir una
  lectura real: por eso hay un **set de lectura disjunto** del de escritura,
  sembrado con `--load`.

## Architecture Decisions

| # | Decisión | Motivo |
|---|---|---|
| S1 | **Dos sets de checksums disjuntos**: `--count` (escrituras, `salt="post"`) y `--reads` (lecturas, `salt="read"`); `sha256("<salt><seed>:<índice>")` | El `GET` por checksum debe leer datos que existan; si el set compartiera checksums con el `POST`, la siembra convertiría el ataque de escritura en replays (`200`) y no habría escrituras que medir |
| S2 | Sin `--pre-clean` ni purga | Append-only (`405`); el replay idempotente es `200` (éxito en `[200,400)`) — los residuos de corridas previas no contamina la medición |
| S3 | **Seed aleatoria por defecto** en `run-vegeta.ps1` (`-Seed` para reproducir) | Cada corrida crea eventos nuevos (escrituras reales); con `-Seed` fijo el ataque mide el replay idempotente y es reproducible |
| S4 | Targets de Vegeta en **formato JSON** (`-format json`, un target por línea, body en base64) | El formato HTTP legible de Vegeta no admite cuerpos inline (verificado en Persistencia, derivación S3 de su plan) |
| S5 | Preflight con **`/readyz`** (servicio *y* Mongo) | `list` y `bychecksum` leen la base; `POST` la escribe. Un `readyz` en `200` es la única comprobación necesaria |
| S6 | `performed_at` único por target (`base + índice`, RFC 3339 UTC con `Z`) | La clave de idempotencia incluye `performed_at`; dentro de una corrida los checksums ya son únicos, pero mantener fechas distintas hace cada evento genuinamente nuevo |
| S7 | Los eventos de stress **se quedan** en la base | Decisión humana (append-only, no hay borrado); el volumen `audit-mongo-data` acumula y el replay sigue siendo `200` |
| S8 | `auditCycle()` de k6 es **autónomo** (POST único → GET listado → GET bychecksum) | k6 sí puede generar bodies únicos por iteración; no necesita siembra previa |

## Task List

- [x] **T1: `gen_targets.py`** — checksums disjuntos post/read, targets
      `post.txt`/`list.txt`/`bychecksum.txt`, siembra `--load`; test unitario.
- [x] **T2: Scripts k6** — `utils.js` (guard de token, `BASE_URL`,
      `auditCycle`) + `smoke.js`/`load.js`/`stress.js` con thresholds.
- [x] **T3: Script de Vegeta** — `run-vegeta.ps1` con perfiles y umbral.
- [x] **T4: Orquestación + cierre** — `run-stress.ps1`, `README.md`,
      `.gitignore` (`out/`, `targets/`).

## Task Detail

### T1: `gen_targets.py`

**Description:** Script Python (corre con `uv run`, `httpx` ya es dev-dependency)
que (1) genera checksums únicos por sal (`post`/`read`), (2) siembra con
`POST /audit/logs` el set de lectura (`--load`, un `200` cuenta como replay y no
aborta), y (3) escribe los targets de Vegeta en formato JSON —`post.txt` con
bodies únicos (action/entity_type/checksum/performed_at/details) y
`list.txt`/`bychecksum.txt` con el header `Authorization` desde
`SERVICE_API_TOKEN`. CLI: `--count`, `--reads`, `--base-url`, `--seed`,
`--out-dir`, `--load`.

**Acceptance criteria:**
- [x] `--count 1000` produce 1000 líneas únicas en `post.txt` (test lo afirma)
- [x] Set de escritura y de lectura **disjuntos** con la misma semilla (test)
- [x] Los `post` llevan `performed_at` RFC 3339 UTC con `Z`, distinto por target
- [x] `Authorization: Bearer <token>` del entorno, nunca hardcodeado
- [x] Sin `SERVICE_API_TOKEN`, `main` devuelve `2` sin escribir nada
- [x] `ruff check` y `ruff format --check` limpios

**Verification:**
- [x] `uv run pytest tests/stress` → **13 passed**
- [x] Suite completa con la cobertura de `app` intacta (100%)

**Dependencies:** None
**Files likely touched:** `tests/stress/scripts/gen_targets.py`,
`tests/stress/test_gen_targets.py`, `tests/stress/__init__.py`,
`tests/stress/scripts/__init__.py`
**Estimated scope:** Small

### T2: Scripts k6

**Description:** `utils.js` comparte `BASE_URL` (default `http://localhost:8083`),
el guard de token en el scope del módulo (falla antes de arrancar VUs) y
`auditCycle()`: evento único (checksum `sha256(randomBytes(16))`, `performed_at`
ISO con `Z`) → `POST /audit/logs` (201) → `GET /audit/logs?skip=0&limit=50`
(200) → `GET /audit/logs/checksum/{c}` (200 y contiene el checksum).
`smoke.js` (1 VU/30 s), `load.js` (rampa → 100 VUs), `stress.js` (rampa → 500
VUs), cada uno con thresholds (`p95`, `http_req_failed`, `checks`) que hacen
salir con código ≠ 0 si se incumplen. Cada escenario sólo declara `options` +
`export default auditCycle`.

**AC:** `k6 run smoke.js` sale `0` contra el servicio · cada iteración usa un
checksum único (no hay replays en una corrida) · `stress.js` declara ≥ 500 VUs ·
`--out json=...` escribe resultados parseables · sin token ⇒ exit ≠ 0 en la
carga del módulo.
**Verify:** manual E2E en la fase de verificación (sección Verificación).
**Deps:** T1 · **Files:** `tests/stress/scripts/k6/{utils,smoke,load,stress}.js`
**Scope:** Medium

### T3: `run-vegeta.ps1`

**Description:** Orquesta el ataque Vegeta: preflight (`vegeta` en PATH,
`SERVICE_API_TOKEN`, `baseUrl/readyz`), regenera targets con
`gen_targets.py` (siembra `--load` cuando se ataca `bychecksum` y no hay
`-NoSeed`), ataca cada verbo con el perfil (`smoke` 10×10 s ≤1 %, `load`
100×30 s ≤5 %, `stress` 300×60 s ≤10 %) guardando `.results`/`.report.txt`/
`.report.json` en `out/`, y sale ≠ 0 si el porcentaje de errores (`1 - success`
del reporte JSON) supera el umbral.

**AC:** smoke contra el servicio real ⇒ exit 0 con reportes · sin `vegeta`, sin
token o sin `/readyz` ⇒ fail-fast con mensaje y arreglo · umbral roto ⇒ exit ≠ 0.
**Verify:** manual E2E (verificación).
**Deps:** T1 · **Files:** `tests/stress/scripts/run-vegeta.ps1` · **Scope:** Medium

### T4: Orquestación + cierre

**Description:** `run-stress.ps1` encadena el pipeline: preflight (vegeta, k6,
token, `/readyz`) → delega en `run-vegeta.ps1` → `k6 run` con `--env
SERVICE_API_TOKEN`/`BASE_URL` y `--out json=...` → resumen de artefactos en
`out/`. `tests/stress/README.md` documenta instalación (vegeta/k6), variables,
cómo levantar el servicio y leer reportes. `.gitignore` gana
`tests/stress/out/` y `tests/stress/targets/`.

**AC:** `./tests/stress/run-stress.ps1 -Profile smoke -Scenario smoke` corre el
pipeline completo sin pasos manuales · fail-fast en cada etapa · `git status` sin
artefactos de stress · README suficiente para un nuevo.
**Verify:** manual E2E · `uv run pytest --cov=app --cov-fail-under=100` ·
`ruff check .` · `ruff format --check .`.
**Deps:** T2, T3 · **Files:** `tests/stress/run-stress.ps1`,
`tests/stress/README.md`, `.gitignore` · **Scope:** Medium

## Checkpoint Summary

| Punto | Tareas | Se verifica |
|---|---|---|
| Carga reproducible | T1–T3 | Targets únicos y disjuntos; vegeta y k6 corren; thresholds deciden |
| Complete | T4 | Pipeline de un solo comando; docs; lint; cobertura intacta |

## Risks and Mitigations

| Riesgo | Impacto | Mitigación | Tarea |
|---|---|---|---|
| `GET /checksum` sin datos sembrados devuelve `[]` | Mediciones de lectura vacías | `--load` siembra el set de lectura disjunto antes del ataque; `-NoSeed` lo desactiva a propósito | T1, T3 |
| Crecimiento de Mongo por residuo acumulado | Bajo (volumen local) | Aceptado: decisión humana S7; el replay convierte residuos en `200` | — |
| Servicio caído durante el run | Medio | Fail-fast con `/readyz` en ambos scripts | T3, T4 |
| k6/vegeta ausentes del PATH | Bajo | Fail-fast con instrucciones en README | T3, T4 |
| Resultados ensuciando el repo | Bajo | `out/` y targets gitignored | T4 |

## Open Questions

- **Cerrado (v2):** sin Grafana/Prometheus/dashboard; no se toca `app/`.
- **Cerrado (humano):** mezcla de ataque `post + list + bychecksum` con seeding
  del set de lectura.
- **Cerrado (humano):** los eventos de stress **se dejan** en la base (S7).
- **Asumido:** perfiles y umbrales (10/100/300 rps; p95 < 500 ms, error < 1 % en
  smoke/load; p95 < 1 s, error < 10 % en stress) son puntos de partida.