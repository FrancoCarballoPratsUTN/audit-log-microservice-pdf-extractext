# Implementation Plan: Docker + Traefik para AUDA

> **Archivo nuevo.** El plan (`tasks/plan.md`) y su checklist (`tasks/todo.md`)
> pertenecen a la implementación del microservicio y **no se han tocado**.
> Este plan vive en `docker-plan.md` / `docker-todo.md`.
>
> **Estado:** implementado y verificado (10-oct-2026).
>
> **Decisión humana (topología):** AUDA **no levanta su propio Traefik**; se
> enruta con el Traefik que ya levanta Persistencia, uniéndose a su red `proxy`
> y aportando los labels. Sin Grafana / Prometheus / dashboards.

## Overview

Contenedor de producción para AUDA más un stack de desarrollo replicable en
`docker-compose.yml`:

- **`Dockerfile`** — imagen multi-stage con `uv` (builder resuelve `uv.lock` en
  un virtualenv; el runtime lleva sólo la app y el venv, corre como usuario
  `app` no-root y arranca uvicorn). Espejo del patrón de Persistencia.
- **`.dockerignore`** — contexto de build pequeño y libre de secretos.
- **`docker-compose.yml`** — servicio `audit-log` (publicado en host `:8083`,
  el puerto que espera el orquestador) + `mongo` (sólo en red interna), con
  `audit.log` enrutado por el Traefik compartido bajo `Host(\`audit.localhost\`)`.

## Architecture Decisions

| # | Decisión | Motivo |
|---|---|---|
| D1 | Reutilizar el **Traefik existente** de Persistencia: red `proxy` **externa** (`external: true, name: proxy`) y labels de ruta en el servicio | Decisión humana. Un solo edge para la rede de microservicios; el Traefik de Persistencia ya vigila la red `proxy` (`--providers.docker.network=proxy`, `exposedbydefault=false`) |
| D2 | Red interna **propia** `audit-internal` (no reusar `internal` de Persistencia) | `internal` tiene `name: internal` fijo; compartirla acoplaría los stacks y mezclaría redes de Mongo |
| D3 | Contenedor escucha en `:8000`, publicado como `8083:8000` | `AUDIT_LOG_BASE_URL=http://localhost:8083` es el puerto que espera el orquestador; el contenedor, como en Persistencia, usa el puerto interno del `CMD` de uvicorn |
| D4 | Env sin hardcodeo; `SERVICE_API_TOKEN` **obligatoria** sin default; el resto con defaults del `.env.example` | El servicio ya se niega a arrancar sin token (SPEC §3.6); compose falla rápido con mensaje claro |
| D5 | `Dockerfile` espejo del de Persistencia (multi-stage `uv`, `python:3.14-slim`, non-root, healthcheck sobre `/health`) | Patrón ya validado en el repo hermano; `/health` no toca Mongo y sirve de liveness (SPEC §6.5) |
| D6 | `mongo` **sin puerto al host**, sólo red interna | La base no es pública; sólo el servicio la alcanza (`MONGO_URI=mongodb://mongo:27017`) |

## Dependency Graph

```
T1 Dockerfile ─┐
T2 .dockerignore ──► T3 docker-compose.yml ──► (verificación E2E)
```

## Task List

- [x] **T1: `Dockerfile`** — multi-stage `uv` / `python:3.14-slim`, non-root,
      `EXPOSE 8000`, healthcheck `/health`, `CMD uvicorn --factory`.
- [x] **T2: `.dockerignore`** — `.git`, `.venv`, caches, `.env*` (salvo
      `.env.example`), `tests/`, `tasks/`, `*.md`, `tests/stress/{out,targets}`.
- [x] **T3: `docker-compose.yml`** — `audit-log` + `mongo` + redes `proxy`
      (externa) y `audit-internal`; labels de Traefik; env completo; `depends_on`
      con healthcheck de Mongo.

## Task Detail

### T1: `Dockerfile`

**Description:** Imagen de producción multi-stage. `builder` copia `uv` desde
`ghcr.io/astral-sh/uv:0.11.7`, hace `uv sync --frozen --no-install-project
--no-dev` con los mount de caché, y copia `app/`. `runtime` crea el usuario
`sistema app`, copia el `/app` del builder con `--chown`, expone `8000`, declara
un `HEALTHCHECK` sobre `127.0.0.1:8000/health` y arranca
`uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`.

**Acceptance criteria:**
- [x] `docker compose build` termina sin errores (un solo stage runtime final)
- [x] `docker run` sin `SERVICE_API_TOKEN` sale con error de configuración
- [x] El proceso corre como usuario no-root (`app`)
- [x] `/health` responde dentro del contenedor
- [x] El `CMD` usa `--factory` (la app resuelve su config en `lifespan`)

**Verification:** build real + `docker compose up` + sondeos (ver sección
Verificación del `docker-todo.md`).

**Dependencies:** None
**Files likely touched:** `Dockerfile`
**Estimated scope:** Small

### T2: `.dockerignore`

**Description:** Recorta el contexto de build. Ignora control de versiones,
virtualenv y caches de Python, secretos (`.env`, `.env.*` salvo `.env.example`),
tests/tasks/docs y los artefactos generados por el arnés de stress.

**Acceptance criteria:**
- [x] `docker compose build` no envía `.env` (con secretos) al daemon
- [x] Los artefactos de stress (`out/`, `targets/`) no inflan el contexto

**Verification:** tamaño del contexto en el build; revisión del fichero.
**Dependencies:** None
**Files likely touched:** `.dockerignore`
**Estimated scope:** Small

### T3: `docker-compose.yml`

**Description:** Stack local. `audit-log` publica `8083:8000`, inyecta el env
completo (token obligatorio; resto con defaults), depende de `mongo` sano
(`depends_on: condition: service_healthy`), lleva los labels de Traefik
(`Host(\`audit.localhost\`)`, entrypoint `web`, puerto `8000`) y se une a
`proxy` + `audit-internal`. `mongo` (`mongo:7.0`) sólo en `audit-internal`, con
healthcheck `ping` y volumen `audit-mongo-data`.

**Acceptance criteria:**
- [x] `docker compose config` resuelve sin errores ni advertencias
- [x] Se une a la red `proxy` existente (no la crea ni la rompe)
- [x] `curl http://localhost:8083/health|/readyz` responden
- [x] `curl http://audit.localhost/health` responde a través del Traefik
      compartido (con el stack de Persistencia arriba)
- [x] Sin `.env` con token, `docker compose up` falla con mensaje claro

**Verification:** E2E (ver sección Verificación del `docker-todo.md`).
**Dependencies:** T1, T2
**Files likely touched:** `docker-compose.yml`
**Estimated scope:** Small

## Risks and Mitigations

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Red externa `proxy` ausente (Persistencia no arriba) | `docker compose up` falla | Documentar el orden (levantar el Traefik de Persistencia primero) y el fallback `docker network create proxy` |
| Choque con el puerto `:80` del Traefik existente | Medio si se levanta un segundo Traefik | AUDA **no** define servicio Traefik; `:80` sigue siendo sólo del edge compartido |
| Puerto host `:8083` ocupado | Arranque fallido | Documentado; comprobarlo antes de `up` |
| Datos de stress acumulándose en el volumen | Crecimiento de Mongo | Aceptado (append-only): el POST idempotente convierte residuos en `200`, nunca en error |

## Open Questions

- **Cerrado (humano):** topología = Traefik compartido (red `proxy` exterior).
- **Cerrado (humano):** sin observabilidad (sin Grafana/Prometheus).
- **Asumido:** puerto de publicación `8083` porque es el de `AUDIT_LOG_BASE_URL`.