# Tasks: Audit Log Microservice (`pdf-extractext`) · AUDA

> Checklist operativo. El detalle de cada tarea (criterios, verificación,
> dependencias) está en [`plan.md`](./plan.md); el diseño en
> [`../SPEC.md`](../SPEC.md).
>
> **Estado:** 10/16 tareas. T7–T10 cerradas y verificadas (294 tests, 100 % de
> cobertura de `app/`); Checkpoint Core slice pendiente de T11 y revisión humana.

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

- [ ] **T11: Carrera bajo concurrencia + replay**
  - [ ] N=10 concurrentes ⇒ exactamente 1 documento, 1 `201`, 9 `200` de replay
  - [ ] **Desactivar la Barrera 2 rompe el test** (verificado por mutación)
  - [ ] 20 repeticiones sin flakiness, sin `sleep` ni polling
  - [ ] Gate sobre la Capa 3 real, no sobre el fake

### Checkpoint: Core slice ★
- [ ] `POST /audit/logs` ⇒ `201` + `Location` + 7 campos
- [ ] Repetido ⇒ `200` + `X-Idempotent-Replay`
- [ ] T11 verde: exactamente 1 documento bajo concurrencia
- [ ] Replay por Barrera 1 y por Barrera 2
- [ ] `details` ausente ⇒ `{}`; `text.delete` funciona
- [ ] Checksum arbitrario aceptado
- [ ] Clave desconocida ⇒ `400`; `details` anidado ⇒ `201`
- [ ] Capas sin imports prohibidos (grep)
- [ ] `pytest --cov=app --cov-fail-under=85` verde
- [ ] **Revisión humana** — aprobado / rechazado (nota: ................................)

---

## Phase 4: Lecturas

- [ ] **T12: `GET /audit/logs?skip&limit`**
  - [ ] **Array de primer nivel** (el test afirma `isinstance(body, list)`)
  - [ ] 7 campos por elemento, sin nulos
  - [ ] `_id` hex de 24 chars; fechas RFC 3339 UTC con `Z`
  - [ ] Orden `performed_at desc` con desempate estable por `_id`
  - [ ] `skip`/`limit` fuera de rango ⇒ `400`, nunca recorte
  - [ ] Sin resultados ⇒ `200` + `[]`
  - [ ] El `GET` no registra evento de auditoría

- [ ] **T13: `GET /audit/logs/checksum/{checksum}`**
  - [ ] Path exacto `/audit/logs/checksum/{valor}`
  - [ ] Filtra sólo por `checksum`, con el orden de SPEC §8.1
  - [ ] Sin `.limit()` en el cursor (D12)
  - [ ] Sin resultados ⇒ `200` + `[]`, nunca `404`
  - [ ] `/audit/logs/checksum/` sin valor ⇒ `404`, no `500`
  - [ ] También array de primer nivel

### Checkpoint: Lecturas
- [ ] Ambos `GET` devuelven array JSON de primer nivel
- [ ] 7 campos por elemento, sin nulos
- [ ] `_id` hex de 24 chars; fechas con `Z` parseables por `time.Time`
- [ ] Orden estable entre dos llamadas iguales
- [ ] `skip`/`limit` inválidos ⇒ `400`, sin recorte
- [ ] Checksum sin resultados ⇒ `200` + `[]`
- [ ] Checklist de contrato SPEC §9 en verde
- [ ] **Revisión humana** — aprobado / rechazado (nota: ................................)

---

## Phase 5: Endurecimiento y cierre

- [ ] **T14: Middleware**
  - [ ] Orden `401 → 415 → 413 → 400`, con test que fija el orden real
  - [ ] Body > `MAX_BODY_BYTES` ⇒ `413`; `Content-Type` incorrecto en POST ⇒ `415`
  - [ ] Eco de `X-Request-ID`; generación si falta
  - [ ] CORS con `GET, POST, OPTIONS`
  - [ ] Log de acceso con duración
  - [ ] El límite mira `Content-Length` y nunca lee el body

- [ ] **T15: Matriz de errores completa**
  - [ ] Las 8 filas de SPEC §7.2 con su `status` y `code`
  - [ ] Regla de `httpclient/client.go:39`: todo `>= 300` devuelve body parseable
  - [ ] Garantía negativa: ningún endpoint devuelve `422`
  - [ ] `PUT` y `DELETE` ⇒ `405 METHOD_NOT_ALLOWED`
  - [ ] Faults inyectados en la base de datos, no con `patch` sobre `app/`
  - [ ] Sin `xfail` ni `skip`

- [ ] **T16: OpenAPI, README y cobertura**
  - [ ] `/openapi.json` documenta request, response y `Bearer` en las 3 rutas
  - [ ] El schema declara `_id`
  - [ ] Ninguna operación lista `422`
  - [ ] `POST /audit/logs` documenta `201`, `400`, `401`, `413`, `415`
  - [ ] README: variables, arranque (`uvicorn app.main:create_app --factory --port 8083`), contrato, `curl` por endpoint, cómo levantar MongoDB para los tests
  - [ ] `pytest --cov=app --cov-fail-under=85` sin excluir producción

### Checkpoint: Complete
- [ ] Suite completa verde con `--cov-fail-under=85`
- [ ] `ruff check` · `ruff format --check` limpios
- [ ] 8 filas de la matriz por test, sin `skip` ni `xfail`
- [ ] Checklist SPEC §9 en verde
- [ ] Criterios de éxito del SPEC cumplidos
- [ ] Listo para revisión final del humano

---

## Handoff al orquestador Go (fuera del alcance de AUDA)

> Bloqueante del despliegue: AUDA **no arranca** sin `SERVICE_API_TOKEN`, así que
> los puntos 1-4 deben estar en el cliente Go **antes** del primer arranque de
> AUDA. Detalle con archivos y líneas en SPEC §2.7.

- [ ] 1. `AUDIT_LOG_API_TOKEN` en `internal/config/config.go`, **sin default**
- [ ] 2. `httpclient.New(baseURL, timeout, token)` + `Authorization: Bearer` en **todas** las requests
- [ ] 3. `cmd/orchestrator/main.go:35` propaga el token a `auditlog.NewClient(...)`
- [ ] 4. `internal/clients/auditlog/client.go:25` propaga el token al cliente
- [ ] 5. `internal/services/audit_service.go:38` — un `401` es error de cableado: `logger.Error`, sin reintento
- [ ] 6. Actualizar los 5 tests de `internal/clients/auditlog/client_test.go` con el header y añadir el caso `401` sin token
- [ ] 7. *(Opcional)* `ListByChecksum(skip, limit)` para acotar el listado por checksum

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