# Tasks: Audit Log Microservice (`pdf-extractext`) · AUDA

> Checklist operativo. El detalle de cada tarea (criterios, verificación,
> dependencias) está en [`plan.md`](./plan.md); el diseño en
> [`../SPEC.md`](../SPEC.md).
>
> **Estado:** 16/16 tareas originales. T7–T16 cerradas y verificadas (380 tests,
> 100 % de cobertura de `app/`); Core slice, las dos lecturas, el endurecimiento
> del transporte, la matriz de errores y el OpenAPI implementados.
>
> **Remediación post code review:** 3/13 tareas (T17–T29); ver Fases 6–8.

---

## Phase 1: Foundation

- [x] **T1: Project scaffolding**
  - [x] `pyproject.toml` con uv, fastapi, pydantic, pydantic-settings, pymongo, uvicorn
  - [x] pytest + pytest-asyncio (`asyncio_mode = "auto"`) + pytest-cov + httpx + ruff
  - [x] Árbol de paquetes y layout de tests espejo de `app/`
  - [x] `uv sync` genera `uv.lock` **versionado**
  - [x] `.env.example` con las 12 variables; `SERVICE_API_TOKEN` sin valor por defecto
  - [x] `.gitignore`
  - [x] `tests/unit/test_package_layout.py` — la dirección de dependencias es un test, no una nota
  - [x] `uv run ruff check .` · `uv run ruff format --check .` limpios

- [x] **T2: Jerarquía de errores**
  - [x] `ServiceError` base con `status` / `code` / `type_uri` / `title`
  - [x] Las 8 subclases de SPEC §7.2
  - [x] Guard de drift contra la matriz de SPEC §7.2
  - [x] Test de mutación: cambiar `AuditStorageError.status` rompe el test

- [x] **T3: Problem details + handlers + schemas**
  - [x] `app/api/problem.py` — cuerpo `application/problem+json` con los 6 campos
  - [x] `app/api/exception_handlers.py` — `ServiceError`, `RequestValidationError`, HTTP, catch-all
  - [x] **`RequestValidationError` → `400 VALIDATION_ERROR`; ningún `422`**
  - [x] `app/api/schemas.py` — `AuditEventRequest` (`extra="forbid"`), `AuditLogResponse` (`_id`), `ProblemDetails`
  - [x] `instance` = ruta sin host ni query
  - [x] Test de mutación: quitar el `alias="_id"` rompe el test de `_id`
  - [x] Test de mutación: quitar el handler de `RequestValidationError` ⇒ `422`
  - [x] `4XX` declarado en `responses` para que FastAPI no inyecte `422` en el OpenAPI

### Checkpoint: Foundation
- [x] `uv sync` limpio · ruff limpio
- [x] Las 8 excepciones con `status`/`code`/`type_uri` correctos
- [x] Un `ServiceError` sale como problem details válido
- [x] Un `RequestValidationError` sale como `400`, nunca `422`
- [x] El schema de `AuditLogResponse` declara `_id` y ninguna operación lista `422`
      (validado sobre el modelo aislado: los routers llegan en T10)
- [x] `uv run pytest --cov-fail-under=85` → 94 tests, 100 % de `app/`
- [x] **Revisión humana** — aprobado

---

## Phase 2: Autenticación

- [x] **T4: Config + token**
  - [x] `app/config.py` con `pydantic-settings` y las 12 variables de SPEC §3.6
  - [x] `SERVICE_API_TOKEN` **sin default**: la app no arranca sin ella
  - [x] Token vacío o sólo con espacios tratado como ausente
  - [x] Variables numéricas `<= 0` ⇒ error que nombra la variable
  - [x] `RETENTION_DAYS = 0` sí se acepta: significa "retención desactivada"
  - [x] El token nunca aparece en logs, en `repr` ni en mensajes de error
  - [x] `get_settings(environ=…)` acepta un `Mapping`, sin mutar el proceso

- [x] **T5: Middleware de autenticación**
  - [x] Bearer + `secrets.compare_digest`
  - [x] `401` con `WWW-Authenticate: Bearer`
  - [x] `detail` **idéntico** en los 7 casos de fallo (sin oráculo)
  - [x] `/health` y `/readyz` sin credenciales
  - [x] Registrado outermost en `create_app`
  - [x] Auth antes del routing: una ruta inexistente también da `401`
  - [x] `app/main.py` — composition root, importable sin entorno

### Checkpoint: Auth
- [x] Sin token la app no arranca, con un error que nombre la variable
- [x] Token ausente / vacío / esquema distinto / incorrecto ⇒ `401`
- [x] `detail` idéntico en todos los casos
- [x] Token ausente de logs y respuestas
- [x] `/health` y `/readyz` accesibles sin token
- [x] `uv run pytest --cov-fail-under=85` → 166 tests, 100 % de `app/`
- [x] **Revisión humana** — aprobado

---

## Phase 3: Core vertical slice — escritura + idempotencia ★

- [x] **T6: Lifecycle de Mongo + índices**
  - [x] `AsyncMongoClient` con timeout; `ping` en el `lifespan`
  - [x] Índice único `(action, entity_type, checksum, performed_at)`
  - [x] Compuestos con `_id desc`
  - [x] TTL sobre `performed_at` sólo si `RETENTION_DAYS > 0`
  - [x] Mongo inalcanzable ⇒ la app arranca y `/readyz` da `503`
  - [x] `app/api/routers/health.py`: `/health` siempre `200`, `/readyz` con `ping`
  - [x] Ambos endpoints fuera del alcance del middleware de autenticación
  - [x] Cierre limpio del cliente al apagar
  - [x] Índices declarados como datos (`IndexSpec`) y traducidos a `IndexModel`
  - [x] Test de integración que comprueba los índices con `index_information()`
  - [x] Test de integración que comprueba el plan real con `explain()` e `IXSCAN`
  - [x] Test de mutación: TTL siempre activo / `unique=False` / `_id` ascendente /
        sin traducción de `PyMongoError` / sin cierre ⇒ los 5 tests se ponen rojos

- [x] **T7: Puerto + doble de test**
  - [x] `AuditLogRepository` como `Protocol` (5 métodos)
  - [x] Dataclasses de dominio (`AuditLog`, `CreateAuditLogRequest`)
  - [x] `FakeAuditLogRepository` con contador de llamadas (`insert` y `find_replay`) y barreras de error

- [x] **T8: Repositorio Mongo — escritura**
  - [x] `insert()` con `_id = ObjectId()`, fechas BSON, `details` verbatim (`{}` si falta)
  - [x] `find_replay()` por los 4 campos
  - [x] `DuplicateKeyError` → señal de replay (`ReplayDetected`)
  - [x] `DocumentTooLarge` y errores de conexión traducidos
  - [x] `serialization.py` devuelve los 7 campos: `_id` hex de 24 chars, fechas con `Z`
  - [x] Test de mutación: quitar la traducción de `DuplicateKeyError` rompe los tests de replay

- [x] **T9: AuditLogService.create**
  - [x] Reloj del servidor → Barrera 1 → Barrera 2
  - [x] `find_replay` encuentra ⇒ `replay=True` y **`insert` no se invoca** (contador del fake)
  - [x] Señal de `DuplicateKeyError` produce el mismo resultado observable
  - [x] `received_at` del servidor —lo pica la Capa 3, desviación **14**—; `performed_at` sin tocar

- [x] **T10: Endpoint `POST /audit/logs`**
  - [x] `201` + `Location` + los 7 campos
  - [x] Repetido ⇒ `200` + `idempotent_replay: true` + `X-Idempotent-Replay: true`
  - [x] Body inválido / clave desconocida / `performed_at` sin offset ⇒ `400`
  - [x] `details` > `MAX_DETAILS_BYTES` ⇒ `413` sin escribir
  - [x] Checksum de formato arbitrario se acepta y persiste
  - [x] `details` ausente ⇒ `{}`; `details` anidado ⇒ verbatim
  - [x] `Location` con `quote(..., safe="")`
  - [x] `app/api/routers/` sin `pymongo` ni `app.repositories`

- [x] **T11: Carrera bajo concurrencia + replay**
  - [x] N=10 concurrentes ⇒ exactamente 1 documento, 1 `201`, 9 `200` de replay
  - [x] **Desactivar la Barrera 2 rompe el test** (verificado por mutación)
  - [x] 20 repeticiones sin flakiness, sin `sleep` ni polling
  - [x] Gate sobre la Capa 3 real, no sobre el fake

### Checkpoint: Core slice ★
- [x] `POST /audit/logs` ⇒ `201` + `Location` + 7 campos
- [x] Repetido ⇒ `200` + `X-Idempotent-Replay`
- [x] T11 verde: exactamente 1 documento bajo concurrencia
- [x] Replay por Barrera 1 y por Barrera 2
- [x] `details` ausente ⇒ `{}`; `text.delete` funciona
- [x] Checksum arbitrario aceptado
- [x] Clave desconocida ⇒ `400`; `details` anidado ⇒ `201`
- [x] Capas sin imports prohibidos (grep)
- [x] `pytest --cov=app --cov-fail-under=85` verde (suite: 296 tests, 100 %)
- [ ] **Revisión humana** — aprobado / rechazado (nota: ................................)

---

## Phase 4: Lecturas

- [x] **T12: `GET /audit/logs?skip&limit`**
  - [x] `repo.list()` — `find().sort(performed_at desc, _id desc).skip().limit()`
  - [x] `service.list_page()` traslada la página ya validada a Capa 3
  - [x] `AuditLogItem` (7 campos, sin `idempotent_replay`) y `GET` con **array de primer nivel** (el test afirma `isinstance(body, list)`)
  - [x] 7 campos por elemento, sin nulos
  - [x] `_id` hex de 24 chars; fechas RFC 3339 UTC con `Z`
  - [x] Orden `performed_at desc` con desempate estable por `_id` (verificado contra Mongo)
  - [x] `skip`/`limit` fuera de rango ⇒ `400`, nunca recorte; `limit` ausente ⇒ `DEFAULT_LIMIT`
  - [x] Sin resultados ⇒ `200` + `[]`
  - [x] El `GET` no registra evento de auditoría

- [x] **T13: `GET /audit/logs/checksum/{checksum}`**
  - [x] `repo.find_by_checksum()` — `find({"checksum": c}).sort(performed_at desc, _id desc)`
  - [x] `service.list_by_checksum()` traslada el filtro a Capa 3
  - [x] Path exacto `/audit/logs/checksum/{valor}` (`client_test.go:156`)
  - [x] Filtra sólo por `checksum`, con el orden de SPEC §8.1
  - [x] Sin `.skip()`/`.limit()` en el cursor (D12)
  - [x] Sin resultados ⇒ `200` + `[]`, nunca `404`
  - [x] `/audit/logs/checksum/` sin valor ⇒ `404`, no `500`
  - [x] También array de primer nivel

### Checkpoint: Lecturas
- [x] Ambos `GET` devuelven array JSON de primer nivel
- [x] 7 campos por elemento, sin nulos
- [x] `_id` hex de 24 chars; fechas con `Z` parseables por `time.Time`
- [x] Orden estable entre dos llamadas iguales
- [x] `skip`/`limit` inválidos ⇒ `400`, sin recorte
- [x] Checksum sin resultados ⇒ `200` + `[]`
- [x] Checklist de contrato SPEC §9 en verde (T12/T13)
- [ ] **Revisión humana** — aprobado / rechazado (nota: ................................)

---

## Phase 5: Endurecimiento y cierre

- [x] **T14: Middleware**
  - [x] Orden `401 → 415 → 413 → 400`, con test que fija el orden real
  - [x] Body > `MAX_BODY_BYTES` ⇒ `413`; `Content-Type` incorrecto en POST ⇒ `415`
  - [x] Eco de `X-Request-ID`; generación si falta
  - [x] CORS con `GET, POST, OPTIONS`
  - [x] Log de acceso con duración
  - [x] El límite mira `Content-Length` y nunca lee el body

- [x] **T15: Matriz de errores completa**
  - [x] Las 8 filas de SPEC §7.2 con su `status` y `code`
  - [x] Regla de `httpclient/client.go:39`: todo `>= 300` devuelve body parseable
  - [x] Garantía negativa: ningún endpoint devuelve `422`
  - [x] `PUT` y `DELETE` ⇒ `405 METHOD_NOT_ALLOWED`
  - [x] Faults inyectados en la base de datos, no con `patch` sobre `app/`
  - [x] Sin `xfail` ni `skip`

- [x] **T16: OpenAPI, README y cobertura**
  - [x] `/openapi.json` documenta request, response y `Bearer` en las 3 rutas
  - [x] El schema declara `_id`
  - [x] Ninguna operación lista `422`
  - [x] `POST /audit/logs` documenta `201`, `400`, `401`, `413`, `415`
  - [x] README: variables, arranque (`uvicorn app.main:create_app --factory --port 8083`), contrato, `curl` por endpoint, cómo levantar MongoDB para los tests
  - [x] `pytest --cov=app --cov-fail-under=85` sin excluir producción

### Checkpoint: Complete
- [x] Suite completa verde con `--cov-fail-under=85` (380 tests, 100 % de cobertura)
- [x] `ruff check` · `ruff format --check` limpios
- [x] 8 filas de la matriz por test, sin `skip` ni `xfail`
- [x] Checklist SPEC §9 en verde
- [x] Criterios de éxito del SPEC cumplidos
- [ ] Listo para revisión final del humano

---

## Phase 6: Remediación — Bloqueantes

> Detalle completo, dependencias, archivos y verificación: issues
> [#40–#55](https://github.com/FrancoCarballoPratsUTN/audit-log-microservice-pdf-extractext/issues/40)
> (épicos F6–F8). Este bloque surge de la revisión de código H-01…H-17.

- [x] **T17: Apagado graceful y gate de lint** · H-01, H-04, H-16
  - [x] Ningún código de `app/` instala un handler que sustituya al de uvicorn
  - [x] `SIGTERM` en contenedor: uvicorn drena, ejecuta el `finally` del lifespan y termina con código 0 dentro del grace period
  - [x] El deregistro de Consul sigue ocurriendo en el cierre; hay test con doble
  - [x] `ruff check .` y `ruff format --check .` pasan
  - [x] No queda ningún test que mute handlers globales del proceso
  - [x] `tests/unit/test_main_signals.py` eliminado y `app/main.py` formateado

- [x] **T18: Readiness real: ping + índices** · H-02, H-05
  - [x] `/readyz` responde `503` si falla el ping o si los índices no están listos
  - [x] Cuando Mongo vuelve, `/readyz` crea los índices y pasa a `200`; llamadas posteriores no los recrean
  - [x] El arranque con Mongo caído mantiene `/health` en `200` y no rompe el proceso
  - [x] `app/api` no importa `app.repositories`; el test lo verifica sobre toda la Capa 1
  - [x] `audit_logs_collection()` se invoca una sola vez en el lifespan
  - [x] `readiness_probe` inyectado en `app.state` con `indexes_ready`, `ensure_indexes` idempotente y lock

- [x] **T19: `details`: validación en frontera y errores BSON** · H-03, H-06
  - [x] `NaN` e `Infinity` ⇒ `400`, sin insertar documento
  - [x] Entero mayor de 64 bits ⇒ `400`, no `500`
  - [x] Clave con `\u0000` o estructura BSON inválida ⇒ `400`
  - [x] Anidamiento excesivo ⇒ `400`, no `500`
  - [x] El límite se mide en bytes UTF-8: un payload no ASCII por debajo del límite se acepta; uno que lo supera da `413`
  - [x] Un `POST` inválido no deja un documento que luego haga fallar el `GET` (test de integración agregado; requiere Mongo para ejecutarse)

### Checkpoint A — Bloqueantes cerrados
- [x] `U` verde.
- [x] `L` verde.
- [x] Smoke manual: `SIGTERM` limpio, `/readyz` recupera con Mongo, `details` inválidos devuelven `400`.
- [ ] Revisión humana antes de pasar a la Fase 7.

---

## Phase 7: Remediación — Corrección, seguridad y operación

- [x] **T20: Identidad normalizada a milisegundos** · H-11, H-17
  - [x] `performed_at` y `received_at` quedan normalizados a milisegundos en el dominio
  - [x] El test de serialización ya no afirma que Mongo guarda microsegundos
  - [x] Test explícito de truncamiento `.123456 → .123000`
  - [x] La documentación del contrato dice que la identidad/deduplicación es por ms

- [x] **T21: Validaciones cruzadas de `Settings`** · H-07
  - [x] Un `DEFAULT_LIMIT` mayor que `MAX_LIMIT` impide arrancar con un error explícito
  - [x] `MAX_DETAILS_BYTES > MAX_BODY_BYTES` impide arrancar
  - [x] Los valores válidos siguen funcionando igual
  - [x] `model_validator(mode="after")` con mensajes claros y tests de combinaciones inválidas

- [x] **T22: `LOG_LEVEL` dentro de `Settings`** · H-08
  - [x] `LOG_LEVEL` se lee desde `Settings`, no desde `os.getenv` en el import
  - [x] Un valor inválido falla al arrancar con un mensaje claro
  - [x] El nivel configurado se aplica aunque se cree más de una app en tests
  - [x] `.env.example` y la documentación listan la variable

- [x] **T23: Quitar handler global de `PydanticValidationError`** · H-09
  - [x] Un JSON de entrada inválido sigue devolviendo `400 VALIDATION_ERROR`
  - [x] Un `PydanticValidationError` interno devuelve `500 INTERNAL_ERROR` y deja la causa en el log
  - [x] No queda registro del tipo base en `register_exception_handlers`

- [x] **T24: Autenticación robusta con credenciales no ASCII** · H-12
  - [x] Una credencial con acentos devuelve `401`, no `500`
  - [x] Un token configurado con caracteres no ASCII funciona correctamente
  - [x] No se registra el valor del token ni de la credencial
  - [x] La documentación de despliegue incluye el rate limit de `401` como mitigación de flood

- [x] **T25: Sanear `X-Request-ID`** · H-13
  - [x] Un `X-Request-ID` válido se conserva y se devuelve igual
  - [x] Un ID inválido, vacío o demasiado largo se reemplaza por un UUID
  - [x] Los logs no pueden ser inyectados con saltos de línea desde esa cabecera

- [x] **T26: Cerrar bypass del límite de body** · H-10
  - [x] Un `POST` sin `Content-Length` no llega a Pydantic y devuelve `413`
  - [x] Un `POST` con `Transfer-Encoding: chunked` no se lee sin límite
  - [x] Un body dentro del límite sigue funcionando
  - [x] La configuración de Traefik incluye `buffering.maxRequestBodyBytes`
  - [x] La documentación explica el comportamiento para clientes chunked/HTTP/2 sin longitud

- [x] **T27: Access log único y documentación usable** · H-14
  - [x] Cada petición produce una sola línea de access log
  - [x] `/docs` y `/openapi.json` cargan sin token; `/audit/logs` sigue devolviendo `401`
  - [x] El `CMD` del Dockerfile incluye `--no-access-log`
  - [x] La documentación explica que la UI y el esquema son públicos por diseño, pero los datos no

### Checkpoint B1 — Configuración y dominio
- [x] `U` verde.
- [x] `L` verde.
- [x] Tests de configuración inválida y normalización ms pasan.

### Checkpoint B2 — Seguridad y operación
- [x] `U` verde.
- [x] `L` verde.
- [x] Smoke: credencial no ASCII, request ID inválido, body sin longitud, `/docs` y access log único.
- [x] `docker build` correcto.

---

## Phase 8: Remediación — Limpieza

- [x] **T28: Unificar renderizado y normalización de `details`** · H-15a
  - [x] Escritura y lectura usan el mismo formateador de 7 campos
  - [x] El formato RFC 3339 con `Z` y ms no cambia
  - [x] `details` se normaliza en un solo sitio y las ramas `details is None` inalcanzables desaparecen
  - [x] El tipo declarado refleja lo que realmente se acepta (`Any`/`JsonValue`, no `dict`)

- [x] **T29: Eliminar código muerto y duplicados** · H-15b
  - [x] No queda `render`, `count`, `seed` ni `count_error` sin uso
  - [x] No hay dos constantes para el mismo mensaje de storage
  - [x] El docstring del fake describe el comportamiento real del servicio
  - [x] La suite sigue verde y sin pérdida de cobertura

### Checkpoint C — Cierre
- [ ] `U` verde.
- [ ] `L` verde.
- [ ] Cobertura igual o superior al 100 % actual.
- [ ] `I` ejecutado con Mongo real.
- [ ] Revisión final contra la matriz H-01…H-17.

---

## Handoff al orquestador Go (fuera del alcance de AUDA)

> Bloqueante del despliegue: AUDA **no arranca** sin `SERVICE_API_TOKEN`, así que
> los puntos 1-4 deben estar en el cliente Go **antes** del primer arranque de
> AUDA. Detalle con archivos y líneas en SPEC §2.7.

- [x] 1. `AUDIT_LOG_API_TOKEN` en `internal/config/config.go`, **sin default**
- [x] 2. `httpclient.New(baseURL, timeout, token)` + `Authorization: Bearer` en **todas** las requests
- [x] 3. `cmd/orchestrator/main.go:35` propaga el token a `auditlog.NewClient(...)`
- [x] 4. `internal/clients/auditlog/client.go:25` propaga el token al cliente
- [x] 5. `internal/services/audit_service.go:38` - un `401` es error de cableado: `logger.Error`, sin reintento
- [x] 6. Actualizar los 5 tests de `internal/clients/auditlog/client_test.go` con el header y añadir el caso `401` sin token
- [ ] 7. *(Opcional)* `ListByChecksum(skip, limit)` para acotar el listado por checksum

> **Estado (Go, 9-oct-2026):** puntos 1-6 implementados y verificados con TDD en
> `orchestator-microservices-pdf-extractext` — `go build ./... && go vet ./... && go test ./...`
> en verde, incluido el caso `401` sin reintento. Token de AUDA generado y
> colocado en su `.env` (`SERVICE_API_TOKEN`). Punto 7 (opcional) no implementado.

---

## Notas de ejecución

- Actualizar este checklist al terminar cada tarea; el plan es la referencia, esto
  es el estado.
- Si una tarea se desvía de su criterios de aceptación, registrar la desviación en
  la tabla **Deviations Recorded During Execution** de `plan.md` antes de seguir.
- Si el MongoDB de los tests de integración no está disponible, decirlo
  explícitamente en el checkpoint en vez de marcarlo verde.

## MongoDB para los tests de integración

- Con `MONGO_URI` apuntando a un MongoDB accesible, `uv run pytest` corre la
  suite entera sin tocar nada más.
- Sin `MONGO_URI`, el conftest prueba `mongodb://localhost:27017`; si no responde,
  **omite** los tests de integración con un motivo explícito y el resto sigue en
  verde. Un `skip` con explicación es honesto; marcarlos verdes no lo es.
- Si el MongoDB responde pero **rechaza las credenciales**, los tests **fallan**
  en vez de omitirse: es un error de configuración, no una dependencia ausente, y
  omitirlo escondería el fallo hasta el CI.
- La base de datos de los tests siempre termina en `_test`; el conftest lo exige
  con un `assert` porque estos tests **borran** colecciones.
- Los índices se limpian en cada test, no una vez por sesión: MongoDB nunca borra
  un índice, y uno creado por un test anterior haría pasar al siguiente sin que
  hubiera creado nada. Durante T6 esto pasó y se detectó.
