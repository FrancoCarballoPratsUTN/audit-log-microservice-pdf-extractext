# Tasks — Docker + Traefik compartido (AUDA)

> Plan: [`docker-plan.md`](./docker-plan.md)
>
> **Archivo nuevo.** `plan.md` / `todo.md` siguen intactos: pertenecen a la
> implementación del microservicio.
>
> **Estado: T1–T3 cerradas y verificadas.** Falta sólo la revisión final humana.

---

## T1: `Dockerfile`
**Status:** done ✅
- [x] Multi-stage: builder `python:3.14-slim` + `uv 0.11.7` (`uv sync --frozen --no-install-project --no-dev`)
- [x] Runtime non-root (`app`), `EXPOSE 8000`, `HEALTHCHECK` sobre `/health`, `CMD uvicorn --factory --port 8000`

**AC:** build sin errores · sin `SERVICE_API_TOKEN` ⇒ error de configuración · `/health` 200 en el contenedor
**Verify:** `docker compose config` OK · build real incluido en la verificación E2E de T3
**Deps:** — · **Files:** `Dockerfile` · **Scope:** Small
**Decisiones:** espejo del Dockerfile ya validado de Persistencia (D5); `/health` no toca Mongo ⇒ liveness correcto (SPEC §6.5)

---

## T2: `.dockerignore`
**Status:** done ✅
- [x] Ignora `.git/`, `.venv/`, caches, `.env*` (salvo `.env.example`), `tests/`, `tasks/`, `*.md`, `tests/stress/{out,targets}`

**AC:** el secretos de `.env` no viaja en el contexto de build
**Verify:** revisión + build
**Deps:** — · **Files:** `.dockerignore` · **Scope:** Small

---

## T3: `docker-compose.yml`
**Status:** done ✅
- [x] `audit-log` publica `8083:8000`, env completo (token obligatorio, resto con defaults), `depends_on mongo service_healthy`
- [x] Labels de Traefik: `Host(\`audit.localhost\`)`, entrypoint `web`, puerto `8000`
- [x] Redes: `proxy` **externa** (`name: proxy`, del stack de Persistencia) + `audit-internal` (`internal: true`, mongo sin puerto host)
- [x] Volumen `audit-mongo-data`

**AC:** `docker compose config` OK · se une a `proxy` sin crearla ni romperla · `:8083/health|/readyz` y `audit.localhost/health` responden · sin token ⇒ fallo claro
**Verify:** manual E2E — `docker compose config` → exit 0 · `docker compose up --build -d` → contendores sanos · `curl http://localhost:8083/health` → `{"status":"ok"}` · `curl http://localhost:8083/readyz` → `{"status":"ok","mongo":"ok"}` · `curl http://audit.localhost/health` (Traefik compartido) → 200
**Deps:** T1, T2 · **Files:** `docker-compose.yml` · **Scope:** Small
**Decisiones:** sin servicio Traefik propio (D1, decisión humana) · red interna propia `audit-internal` para no colisionar con `internal` de Persistencia (D2) · puerto contenedor `8000` / host `8083` por `AUDIT_LOG_BASE_URL` (D3)

---

## Verificación (compartida T1–T3)

- [x] `docker compose config` resuelve (exit 0)
- [x] Build + `up --build -d` con Mongo sano
- [x] `curl http://localhost:8083/health` y `http://localhost:8083/readyz` → 200
- [x] `curl http://audit.localhost/health` → 200 vía el Traefik existente
- [ ] **Revisión final del humano**

## Nota sobre decisiones abiertas

- Topología **compartida** (red `proxy` externa) elegida por el humano: AUDA no
  levanta Traefik propio. Requisito de arranque: el edge de Persistencia debe
  estar arriba, o `docker network create proxy` (documentado en el compose).
- Sin observabilidad: no hay instrumentación en `app/`; el stress usa sólo
  Vegeta + k6.