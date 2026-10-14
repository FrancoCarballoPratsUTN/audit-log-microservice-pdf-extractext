# Audit Log Microservice (AUDA)

Microservicio de auditoría **append-only** para `pdf-extractext`: recibe los
eventos del orquestador Go y los guarda en MongoDB. No edita ni borra nada; los
logs se leen con dos listados ordenados.

Diseño completo en [`SPEC.md`](./SPEC.md); plan de ejecución en
[`tasks/plan.md`](./tasks/plan.md).

## Requisitos

- Python **3.14+**
- [uv](https://docs.astral.sh/uv/)
- MongoDB accesible (para arrancar y para los tests de integración)

## Configuración

Todas las variables se leen del entorno (o de un `.env`). Copia
[`.env.example`](./.env.example) a `.env`. **`SERVICE_API_TOKEN` no tiene valor
por defecto**: sin él el servicio se niega a arrancar.

| Variable | Por defecto | Descripción |
|---|---|---|
| `SERVICE_API_TOKEN` | — **(obligatoria)** | Secreto compartido que el orquestador envía como `Authorization: Bearer <token>`. Generar con `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `MONGO_URI` | `mongodb://localhost:27017` | URI de MongoDB. |
| `MONGO_DATABASE` | `pdf_extractext_audit` | Base de datos. |
| `MONGO_AUDIT_LOGS_COLLECTION` | `audit_logs` | Colección de eventos. |
| `MONGO_TIMEOUT_MS` | `5000` | Timeout de selección de servidor, en ms. |
| `MAX_BODY_BYTES` | `1048576` | Tamaño máximo del cuerpo de la petición (1 MiB). |
| `MAX_DETAILS_BYTES` | `65536` | Tope del campo `details` ya serializado (64 KiB). |
| `DEFAULT_LIMIT` | `10` | `limit` del listado global cuando no se envía. |
| `MAX_LIMIT` | `100` | `limit` máximo aceptado. |
| `MAX_SKIP` | `10000` | `skip` máximo aceptado. |
| `RETENTION_DAYS` | `0` | Días de retención (TTL de Mongo sobre `performed_at`). `0` desactiva el TTL. |
| `APP_NAME` | `Audit Log Microservice` | Nombre mostrado por la app. |

## Arranque

```bash
uv sync
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8083
```

`--factory` es necesario: la configuración se resuelve en el `lifespan`, así que
importar `app.main` no exige entorno. El puerto `8083` es el que espera el
orquestador por defecto (`AUDIT_LOG_BASE_URL`).

Si MongoDB no responde, la app **arranca igualmente** y es `/readyz` quien
reporta `503`: un proceso vivo que responde sondas es recuperable.

Documentación interactiva: <http://localhost:8083/docs> (y `/openapi.json`).

## Docker (Traefik compartido + compose)

Plan y checklist: [`tasks/docker-plan.md`](./tasks/docker-plan.md) y
[`tasks/docker-todo.md`](./tasks/docker-todo.md).

Imagen de producción multi-stage (`uv`, non-root) y stack local con
`docker-compose.yml`. AUDA **no** levanta su propio Traefik: se une a la red
`proxy` del edge que ya levanta Persistencia y se sirve bajo
`Host(\`audit.localhost\`)`. El puerto `8083` del host sigue siendo el de
`AUDIT_LOG_BASE_URL`.

```bash
# El Traefik compartido debe estar arriba (o: docker network create proxy)
docker compose up --build -d

curl http://localhost:8083/health        # directo
curl http://audit.localhost/health       # vía Traefik compartido
```

`SERVICE_API_TOKEN` se lee del `.env` (ver `.env.example`); sin él, compose falla
al levantar. `mongo` corre en una red interna sin puerto al host.

## Pruebas de stress (Vegeta + k6)

Plan y checklist: [`tasks/stress-plan.md`](./tasks/stress-plan.md) y
[`tasks/stress-todo.md`](./tasks/stress-todo.md). Documentación de uso:
[`tests/stress/README.md`](./tests/stress/README.md).

Atacan `post`, `list` y `bychecksum` (AUDA es append-only: no hay `PUT`/`DELETE`).
Con el servicio levantado:

```powershell
$env:SERVICE_API_TOKEN = "el-token-de-tu-despliegue"

# Pipeline completo (Vegeta smoke + k6 smoke)
./tests/stress/run-stress.ps1 -Profile smoke -Scenario smoke

# Sólo Vegeta, o sólo k6
./tests/stress/scripts/run-vegeta.ps1 -Profile smoke
k6 run --env SERVICE_API_TOKEN=$env:SERVICE_API_TOKEN `
       tests/stress/scripts/k6/smoke.js
```

Los resultados quedan en `tests/stress/out/` (ignorado por git).

## Estructura del proyecto

```
audit-log-microservice-pdf-extractext/
├── app/
│   ├── api/
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── audit_logs.py      # Endpoints POST /audit/logs, GET /audit/logs, GET /audit/logs/checksum/{checksum}
│   │   │   └── health.py          # Endpoints /health y /readyz
│   │   ├── __init__.py
│   │   ├── auth.py                # Autenticación Bearer
│   │   ├── dependencies.py        # Dependencias FastAPI (inyección de repositorio/servicio)
│   │   ├── exception_handlers.py  # Manejadores de errores (RFC 9457 Problem Details)
│   │   ├── middleware.py          # Middleware (BodyLimit, ContentType, RequestValidationError)
│   │   ├── problem.py             # Utilidades para errores RFC 9457
│   │   └── schemas.py             # Esquemas Pydantic (validación y serialización)
│   ├── domain/
│   │   ├── __init__.py
│   │   └── models.py              # Modelos de dominio (AuditLog)
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── mongodb.py             # Conexión y gestión de MongoDB (lifespan)
│   │   ├── mongo_audit_log_repository.py  # Implementación MongoDB del repositorio
│   │   ├── protocol.py            # Protocolo (interfaz) del repositorio
│   │   └── serialization.py       # Serialización/deserialización MongoDB
│   ├── services/
│   │   ├── __init__.py
│   │   └── audit_log_service.py   # Lógica de negocio (idempotencia, paginación)
│   ├── __init__.py
│   ├── config.py                  # Configuración desde variables de entorno
│   ├── errors.py                  # Excepciones de dominio
│   └── main.py                    # Punto de entrada FastAPI (factory + lifespan)
├── tasks/
│   ├── docker-plan.md
│   ├── docker-todo.md
│   ├── plan.md
│   ├── stress-plan.md
│   ├── stress-todo.md
│   └── todo.md
├── tests/
│   ├── fakes/                     # Fakes para tests unitarios
│   ├── integration/               # Tests de integración (requieren MongoDB)
│   │   ├── api/                   # Tests de endpoints
│   │   └── repositories/          # Tests de repositorio MongoDB
│   ├── stress/                    # Pruebas de carga/stress (Vegeta + k6)
│   │   ├── out/                   # Resultados (ignorado por git)
│   │   ├── scripts/               # Scripts PowerShell, Python y k6
│   │   ├── targets/               # Ficheros de targets para Vegeta
│   │   ├── README.md
│   │   └── test_gen_targets.py
│   ├── unit/                      # Tests unitarios
│   │   ├── api/
│   │   ├── domain/
│   │   ├── repositories/
│   │   └── services/
│   ├── conftest.py
│   └── __init__.py
├── .env.example                  # Plantilla de variables de entorno (copiar a .env)
├── Dockerfile                    # Imagen Docker multi-stage
├── docker-compose.yml            # Stack local con Traefik compartido
├── LICENSE
├── pyproject.toml                # Dependencias y configuración (uv, ruff, pytest)
├── README.md
├── SPEC.md                       # Especificación completa
└── uv.lock                       # Lockfile de dependencias
```

## Contrato

Todas las rutas salvo las sondas requieren `Authorization: Bearer <token>`.

| Verbo | Ruta | Éxito | Notas |
|---|---|---|---|
| `GET` | `/health` | `200` | Liveness. Público, no toca Mongo. |
| `GET` | `/readyz` | `200` | Readiness. Público; `503` si Mongo no responde. |
| `POST` | `/audit/logs` | `201` | Guarda un evento. `200` sólo si es un replay idempotente. |
| `GET` | `/audit/logs?skip=&limit=` | `200` | Array de primer nivel, `performed_at desc`. |
| `GET` | `/audit/logs/checksum/{checksum}` | `200` | Array de primer nivel de un checksum. |

`PUT` y `DELETE` sobre `/audit/logs` responden `405 METHOD_NOT_ALLOWED`: un log de
auditoría que se puede editar no es una auditoría.

**Cuerpo de entrada** (`POST`): `action`, `entity_type`, `checksum`,
`performed_at` (RFC 3339 con offset) y `details` opcional. Se rechaza cualquier
clave desconocida de primer nivel.

**Respuestas:** array JSON pelado (nunca `{"logs": [...]}`) con los 7 campos
`_id`, `action`, `entity_type`, `checksum`, `details`, `performed_at`,
`received_at`. `_id` es el hex de 24 caracteres del `ObjectId`; las fechas son
RFC 3339 UTC con `Z`.

**Errores:** `application/problem+json` (RFC 9457) con `type`, `title`, `status`,
`detail`, `instance` y `code`. Las ocho filas del contrato están en SPEC §7.2;
ninguna ruta devuelve `422`.

### Ejemplos con `curl`

```bash
export BASE=http://localhost:8083
export TOKEN=el-token-de-tu-despliegue
```

Guardar un evento:

```bash
curl -i -X POST "$BASE/audit/logs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "action": "pdf.extract",
        "entity_type": "document",
        "checksum": "9f86d081884c7d659a2feaa0c55ad015",
        "details": {"page_count": 12},
        "performed_at": "2026-10-05T12:34:56.789Z"
      }'
```

Reenviar el mismo evento devuelve `200` con `X-Idempotent-Replay: true` y no crea
un segundo documento.

Listar con paginación:

```bash
curl -s "$BASE/audit/logs?skip=0&limit=10" -H "Authorization: Bearer $TOKEN"
```

Listar por checksum:

```bash
curl -s "$BASE/audit/logs/checksum/9f86d081884c7d659a2feaa0c55ad015" \
  -H "Authorization: Bearer $TOKEN"
```

Sondas (sin token):

```bash
curl -s "$BASE/health"
curl -s "$BASE/readyz"
```

## Tests

```bash
uv run pytest                                   # suite completa + cobertura
uv run pytest --cov=app --cov-fail-under=85     # puerta de cobertura
uv run ruff check . && uv run ruff format --check .
```

Los tests de integración **borran colecciones** y usan una base cuyo nombre debe
acabar en `_test` (por defecto `pdf_extractext_audit_test`); nunca apuntan a la
base real.

### Levantar MongoDB

Sin `MONGO_URI`, el conftest prueba `mongodb://localhost:27017`. La forma más
rápida es Docker:

```bash
docker run -d --name auda-mongo -p 27017:27017 mongo:7
```

Si no hay MongoDB, los tests de integración se **omiten** con un motivo explícito
y el resto sigue en verde. Si MongoDB responde pero rechaza credenciales, los
tests **fallan** en vez de omitirse: es un error de configuración.

Para usar un MongoDB con autenticación:

```bash
export MONGO_URI="mongodb://usuario:clave@localhost:27017/?authSource=admin"
```
