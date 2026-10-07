# Implementation Plan: Audit Log Microservice (`pdf-extractext`) · AUDA

> Fase 2 del SDD, **ejecución**. Diseño completo en [`../SPEC.md`](../SPEC.md).
> Este archivo es el plan de ejecución; el checklist operativo vive en
> [`todo.md`](./todo.md).
>
> **Estado:** en ejecución. T1–T11 cerradas y verificadas (296 tests, 100 % de
> cobertura de `app/`); el checklist de estado vive en [`todo.md`](./todo.md).

---

## Overview

Microservicio FastAPI que persiste los **logs de auditoría append-only** del
ecosistema `pdf-extractext` en MongoDB. Consume el contrato del orquestador Go ya
implementado y testeado: `POST /audit/logs` y dos lecturas
(`GET /audit/logs?skip&limit`, `GET /audit/logs/checksum/{checksum}`).

Arquitectura de 3 capas estricta con dependencia hacia adentro, Pydantic v2 en el
contrato, autenticación por Bearer token con fail-fast de arranque, idempotencia
por índice único ante el reintento del orquestador, RFC 9457 en todo error
`status >= 300`, y **ningún verbo capaz de modificar o borrar un log**.

Diferencia estructural respecto del hermano `PersistenceMicroservices-pdf-extractext`:
sin `PUT`, sin `DELETE`, sin `409`, sin `checksum` como `_id`, y con una
invariante de contrato que el hermano no tiene — **las respuestas de lectura
son un array de primer nivel**, no un objeto.

## Deviations Recorded During Execution

Se llenan durante la Fase 3.

| # | Desviación | Plan original | Motivo |
|---|---|---|---|
| **1** | T3 añade `tests/unit/api/test_exception_handlers.py`, que el plan no listaba | Los AC de T3 exigían probar el `400` del `RequestValidationError`, la ausencia de `422` y el catch-all, pero sus archivos de test eran sólo `test_problem.py` y `test_schemas.py` | Esos AC son de comportamiento HTTP, no de modelo: necesitaban una app real con rutas que fallen de verdad. `app/main.py` aún no existe, así que la app se construye dentro del módulo de test |
| **2** | T3 registra además `pydantic.ValidationError` | Sólo se pedía el handler de `RequestValidationError` | FastAPI eleva `pydantic.ValidationError` como subclass de `RequestValidationError`, pero el orden de la MRO lo hace elegible para el registro por separado. Registrar ambos elimina la dependencia de ese detalle de Pydantic |
| **3** | `http_exception_handler` traduce `404`/`405` y mapea cualquier otro status a `500 INTERNAL_ERROR` | SPEC §7.2 define 8 filas y ninguna más | Traducir un status no mapeado exigiría inventar un noveno `code`, que es exactamente la deriva de contrato que el guard de drift de T2 existe para impedir |
| **4** | El AC de mutación de T3 apunta a `alias="_id"`, no a `serialization_alias` | «Quitar el `serialization_alias` ⇒ el test de `_id` en rojo» | **Comprobado empíricamente**: con `alias="_id"` solo, `model_dump(by_alias=True)` ya emite `_id`, porque FastAPI serializa con `by_alias=True` y `serialization_alias` sólo aplica en ese mismo modo. Quitar `serialization_alias` **no** rompe ningún test; quitar `alias` rompe tres. El `alias` es la pieza que carga y la que hay que mutar. SPEC D6 declara ambos, así que se conservan los dos |
| **5** | `create_app()` resuelve `Settings`; el `lifespan` queda para MongoDB | SPEC §3.6 y T4 piden «`get_settings` en el `lifespan`, no a nivel de módulo» | El middleware de autenticación y el título del OpenAPI necesitan el token **antes** de que la app empiece a servir, y `add_middleware` no admite cambios después. Resolverlo en la fábrica mantiene la exigencia que importa —`import app.main` no exige entorno— y hace el fallo **más temprano**, no más tarde. El `lifespan` conservará su responsibility real: abrir Mongo, hacer `ping` y crear los índices (SPEC §6.5) |
| **6** | El middleware lee el token de `app.state.api_token` en vez de recibirlo por constructor | T5 requería `app/api/auth.py` con `BearerAuthMiddleware(token)` | Evita una clase distinta por instancia de app y un token capturado en un closure. `app.state` es la dependencia explícita y ya la usa Starlette para el estado por petición. La clase queda sin estado y es registrable directamente con `app.add_middleware(BearerAuthMiddleware)` |
| **7** | Dos tests de T5 inspeccionan el fuente con `ast` | El plan sólo preveía tests de comportamiento | `secrets.compare_digest` no es observable desde fuera: sustituirlo por `==` deja **todos** los tests funcionales en verde, porque la diferencia sólo aparece en el tiempo de respuesta. Es la misma técnica que ya usa `tests/unit/test_package_layout.py` para la dirección de dependencias: una propiedad no observable se protege en el código, no en el test |
| **8** | Comentarios y docstrings de T2–T5 corregidos al español; SPEC §13 reescrito | SPEC §13 decía «código, identificadores y docstrings: inglés», tomados de la convención de los dos hermanos | El usuario aclaró la regla que quería: **el código en inglés, los comentarios y docstrings en español**. SPEC §13 ahora lo dice sin ambigüedad e incluye lo que *no* se traduce: los valores que cruzan el contrato HTTP (`code`, `title`, `type`, `default_detail`, que lee el cliente de Go), los literales de log y los identificadores del dominio. Durante la corrección se habían traducido también los literales de `REASON_*`, `logger.*` y el `ValueError` de arranque; se devolvieron a inglés porque son código, no documentación |
| **9** | T6 declara los índices como datos (`IndexSpec`) y los traduce a `IndexModel` al crear | El plan de T6 no fijaba la forma de declararlos; `ensure_indexes` podía construirlos en línea con `IndexModel` | Un índice mal escrito **no falla**: la app arranca, responde bien y sólo se nota semanas después, cuando una página de `skip/limit` devuelve filas distintas entre dos llamadas idénticas. Declararlos como datos permite afirmar el contrato de §6.3 completo —nombres, orden de campos, `-1` descendente, `unique`, TTL condicional— en un test unitario sin abrir una conexión, y es lo que hace las mutaciones M1–M5 Detection triviales |
| **10** | T6 añade `tests/integration/api/test_health_probes.py` y un `conftest.py` compartido en `tests/integration/` | El plan listaba `tests/integration/repositories/test_mongo_indexes.py` para la verificación de T6 | Los AC de T6 incluyen «Mongo inalcanzable ⇒ la app arranca», y su camino feliz necesita Mongo real: los tests unitarios de `test_health.py` sólo cubren el camino malo, con `FailingClient`. Sin un test que arranque la app contra un Mongo de verdad, `ensure_indexes` se ejecutaba en cada test unitario sin que nadie comprobara que funcionaba —es una llamada silenciosa, y una llamada silenciosa puede no estar ocurriendo o fallar sin que nadie lo note |
| **11** | El `conftest` compartido limpia los índices **por test**, no una vez por sesión | El borrador inicial borraba la base al terminar cada test de repositorio | **Fallo real y detectado durante T6**: MongoDB nunca borra un índice. El `ttl_performed_at` creado por un test seguía ahí en `test_no_ttl_index_is_created_when_retention_is_zero`, que pasaba sin que el lifespan hubiera creado nada —el test verde probaba lo contrario de lo que dice. Con `clean_collection` dependiente por test, ambos tests del lifespan son fiables. El mismo fallo habría afectado a T11 |
| **12** | T7 fija nombres propios para el puerto y el dominio: `AuditLog` / `CreateAuditLogRequest`, `find_by_checksum`, `list`, `count` | SPEC §5.1 y el plan pedían `StoredAuditLog` / `NewAuditLog`, `list_by_checksum(query)`, `list_page(query)`, `ping()` | T7 se entregó y cerró con los modelos de dominio aprobados (`AuditLog`, `CreateAuditLogRequest`, 20 tests). Son nombres internos: ninguno cruza el contrato HTTP que ve el cliente Go. Renombrarlos reescribiría una tarea cerrada sin ganar nada; las referencias de T9/T12/T13 a `StoredAuditLog`, `list_page` y `list_by_checksum` se leen como sus equivalentes entregados. Además, el test del puerto vive en `tests/unit/repositories/test_protocol.py`, no en `tests/unit/services/test_ports.py`, y el AC «el fake cuenta invocaciones de `insert` y `find_replay`» sólo estaba a medias: a `find_replay_calls` le faltaba el contador (añadido en T8) |
| **13** | T8 añade `tests/unit/repositories/test_mongo_audit_log_repository.py` y `tests/unit/repositories/test_protocol.py`, y define `ReplayDetected` en `app/repositories/protocol.py` | El plan sólo listaba `tests/unit/repositories/test_serialization.py` y el test de integración; no decía dónde vive la señal de replay | El AC «ningún `PyMongoError` escapa sin traducir» se decide rama a rama (`DuplicateKeyError`, `DocumentTooLarge`, `PyMongoError` genérico, errores que **no** son del driver): sin unitarios con una colección falsa, esa cobertura dependería de tener Mongo levantado y el gate del 100 % sería intermitente. La señal de replay es parte del contrato del puerto —la lanza la Capa 3 y la consume la Capa 2—, así que vive junto a `AuditLogRepository`. `test_protocol.py` cierra además el AC de T7 que no estaba verificado en ningún test: que el fake satisface el `Protocol` |
| **14** | `received_at` lo pica la Capa 3 (`MongoAuditLogRepository.insert` con `datetime.now(UTC)`); el servicio no tiene reloj inyectable | T9: «`received_at` lo pone el reloj inyectable del servicio», y el flujo de SPEC §9 muestra `received_at = reloj de AUDA` en la Capa 2 | El puerto `insert(request)` de T7/T8 no recibe `received_at` ni lo expone `CreateAuditLogRequest`; inyectarle un reloj al servicio exigiría abrir una tarea cerrada y cambiar el contrato del puerto sin ganancia observable. El observable que importa (SPEC §5.2) es «`received_at` del servidor, no del emisor»: la Capa 3 usa el reloj del servidor y el test de T9 lo afirma con tolerancia. `performed_at` sí queda cubierto explícitamente como «el del emisor, sin tocar» |
| **15** | T10 añade `tests/unit/api/routers/test_audit_logs_router.py`, tests de `AuditLogResponse.from_log` en `test_schemas.py`, un guard de imports en `test_package_layout.py`, y mueve el formateo RFC 3339 a `app/domain/models.rfc3339_utc` | El plan listaba sólo `tests/integration/api/test_create_audit_log.py`, y SPEC/plan dejaban el render de fechas en `serialization.py` (Capa 3) | La Capa 1 no puede importar `app.repositories` (AC de T10), así que el router no puede usar `render`. Si el endpoint viviera sólo en tests de integración, los unit de Capa 1 caerían en skipping cuando Mongo no está y el gate del 100 % sería intermitente —el mismo argumento que la desviación 13. `rfc3339_utc` pasa a la única capa que Capas 1 y 3 ven, y `serialization.render` la reutiliza: el formato llega al cable por una sola primitiva, que es lo que el docstring de `serialization.py` ya exigía. El guard de imports reemplaza un chequeo por substring por un `ast` (el docstring del router nombra `app.repositories` y haría un falso positivo) |
| **16** | T11 despliega **dos** escenarios en `test_idempotency_race.py`: el vertical HTTP (N `POST` concurrentes) y una carrera a nivel servicio con `asyncio.gather` que cría el índice único con `ensure_indexes` antes de correr | El plan describía el escenario como «N peticiones `POST` concurrentes» (uno solo) y no decía que el test debiera crear los índices | El observable del HTTP (1 `201` + 9 `200`) es idéntico caiga el perdedor por la Barrera 1 o por la 2, así que **solo** no demuestra que la Barrera 2 se ejercite: si el servidor serializara las peticiones, la Barrera 1 cortaría a todos los perdedores y la mutación del AC quedaría sin detectar. El segundo escenario garantiza que los N pasan la Barrera 1 casi a la vez sobre una colección vacía y obliga al índice único a decidir: es el que hace **determinista** el AC «quitar la traducción de `DuplicateKeyError` rompe el test». El `ensure_indexes` es necesario porque `clean_collection` borra colección **e índices** (dev. 11): sin él, los N `insert` duplicados cabrían todos en una colección sin índice y el test mentiría |
| — | — | — | — |

---

## Architecture Decisions

Resumen de SPEC §12; el detalle y el porqué están ahí.

- **3 capas con dependencia hacia adentro.** `api → services → repositories`.
  `app/api/` nunca importa `pymongo`; `app/services/` tampoco. Composition root
  único en `app/main.py`.
- **El `_id` es un `ObjectId`, no el checksum.** Un checksum genera **varios**
  eventos (`pdf.extract`, `text.create`, `text.update`, `text.delete`), así que
  el checksum es un campo indexado, no la identidad. El hex de 24 chars encaja
  con `models.AuditLog.ID string`.
- **Pydantic v2 en el contrato**, con tres consecuencias obligatorias: el
  `422` se convierte en `400` (si no, el Orquestador entra en panic con
  `WriteHeader(0)`), `_id` necesita `serialization_alias`, y `extra="forbid"`
  convierte una clave desconocida en un `400` visible en vez de un `201` que
  descarta el dato en silencio.
- **`action` es `str`, no `enum`.** Agregar una operación en el Orquestador no
  debe exigir desplegar AUDA.
- **Doble barrera anti-duplicados.** Barrera 1 = `find_replay()` (evita el viaje
  de escritura y hace invisible el retry normal). Barrera 2 = índice único
  `(action, entity_type, checksum, performed_at)` con `DuplicateKeyError`.
  **Ambas producen la misma respuesta: `200` con el log existente.** El `409`
  del hermano Persistencia no aplica: el cliente trataría un reintento exitoso
  como fallo y loguearía una alarma falsa.
- **`200` de replay, no `409` ni `201`.** El `Emit` del Go pasa `out=nil` y
  acepta cualquier `2xx`: el reintento es invisible. `201 Created` sería mentir
  —no se creó nada— y `409` sería una alarma falsa por un evento que sí se
  guardó.
- **Respuestas de lectura = array de primer nivel.** Invariante de contrato
  (SPEC §2.5 H1). Si se envuelve en `{logs: […]}`, el `json.Decode` de Go falla
  y el orquestador responde `502`: AUDA funcionaría bien y el pipeline se
  rompería.
- **Append-only real.** `PUT` y `DELETE` responden `405`. Un log de auditoría
  editable no es una auditoría.
- **`skip`/`limit` fuera de rango ⇒ `400`, nunca recorte silencioso.** Un recorte
  haría creer al cliente que su página está completa.
- **Listado vacío = `200 []`, nunca `404`.** Semántica de colección.
- **`received_at` lo pone el servidor.** Distingue "cuándo ocurrió" de "cuándo
  lo supimos" — que es lo que hace falta para auditar una pérdida de eventos.
- **`checksum` opaco.** Sin validación de formato: SHA-256 hex en la práctica,
  y el path param ya está implementado y testeado en Go.
- **Autenticación en la Capa 1, con `detail` genérico y comparación en tiempo
  constante.** Sin `403`: es un secreto compartido. `/health` y `/readyz`
  abiertos para sondas de plataforma.
- **`SERVICE_API_TOKEN` sin default ⇒ la app no arranca sin ella.** Convierte un
  fallo silencioso (§2.5 H5) en un fallo duro de arranque. Lección: el
  fail-fast es la decisión que hace innecesario vigilar el handoff.
- **Errores de dominio llevan metadatos de cable.** `app/errors.py` declara
  `status`, `code`, `type_uri` y `title` como `ClassVar`; el handler traduce de
  forma declarativa, sin escalera de `if/else`.
- **`503` para fallos de Mongo, no `500`.** Infraestructura caída: el
  Orquestador puede reintentar.
- **`_id desc` como desempate en ambos índices compuestos.** Sin él, dos
  eventos con el mismo `performed_at` pueden ordenarse de forma no determinista
  entre páginas de `skip/limit`.
- **uv** como gestor de paquetes, `pytest-asyncio` porque Capa 2 y 3 son async.

---

## Estrategia de pruebas (TDD)

Cada tarea del plan sigue **RED → GREEN → REFACTOR**. El `Description` de cada
tarea declara explícitamente qué test falla primero y por qué.

| Nivel | Tamaño | Qué cubre | Tareas |
|---|---|---|---|
| **Unitario** | pequeño, sin I/O | `errors`, `problem`, `auth`, `schemas`, `serialization`, `ports`, `AuditLogService` (con fake), lifecycle | T2, T3, T4, T5, T7, T9, T14 |
| **Integración API** | medio, Mongo real | los 3 endpoints end-to-end, carrera de idempotencia, matriz de errores, OpenAPI | T10, T11, T12, T13, T15, T16 |
| **Integración repo** | medio, Mongo real | mapeo `DuplicateKeyError` → replay, índices, orden del cursor | T8, T11 |

Reglas que este plan se impone:

- **Un test que pasa en el primer intento no prueba nada.** Cada AC nueva se
  escribe y se ve fallar antes de escribir el código.
- **Preferir real > fake > stub > mock.** El `Protocol` más un fake en memoria
  permite testear Capa 2 sin mocks. En Capa 3 se usa Mongo real: un fake de
  colección no probaría el `DuplicateKeyError` real, que es la defensa que
  importa.
- **Tests de contrato, no de interacción.** Se afirma sobre la respuesta HTTP y
  sobre el estado de Mongo, no sobre "se llamó a este método".
- **Chequeo de mutación en T11**: desactivar la Barrera 2 debe romper el test. Si
  el test sigue verde, la defensa no existe.
- **La suite completa corre en cada checkpoint**, no sólo el test enfocado.
- **Gate de cobertura**: `--cov-fail-under=85` en cada checkpoint, sin excluir
  código de producción para alcanzarlo. Cobertura sin excluir es el gate real.
- Los tests de integración necesitan un `mongod` alcanzable (`MONGO_URI`). Se
  documenta cómo levantarlo en el README; sin él, esa parte de la suite no
  corre y **eso se dice explícitamente en el checkpoint**, nunca se oculta con
  `skip`.

---

## Dependency Graph

```
T1 scaffolding
 ├─► T2 errores (8 subclases) ──► T3 problem + handlers + schemas (Pydantic, 422→400)
 └─► T4 config (pydantic-settings, fail-fast) ──► T5 auth middleware (401)
                                       │
                 T4 ──► T6 lifecycle Mongo + índices (único, compuestos, TTL)
                                       │
                 T2 ──► T7 Protocol + Fake ──┤
                                          ▼
                                  T8 repo insert (DuplicateKeyError → replay)
                                          ▼
                                  T9 AuditLogService.create (idempotencia)
                                          ▼
                                  T10 POST /audit/logs  ◄── CHECKPOINT CRÍTICO
                                          ▼
                                  T11 carrera/idempotencia  ◄── CHECKPOINT CRÍTICO
                                          ▼
                          T12 GET global ──► T13 GET por checksum
                                          ▼
                          T14 middleware ──► T15 matriz de 8 errores
                                          ▼
                          T16 OpenAPI + README + cobertura
```

Las dos flechas marcadas como **checkpoint crítico** son las que tienen capacidad
de romper el sistema en silencio: la forma de la respuesta de lectura (H1) y la
defensa anti-duplicados. Se verifican antes de seguir construyendo encima.

---

## Task List

### Phase 1: Foundation

- [ ] **T1: Project scaffolding** — `pyproject.toml` (uv, fastapi, pydantic,
      pydantic-settings, pymongo, uvicorn + pytest, pytest-asyncio, pytest-cov,
      httpx, ruff), árbol de paquetes, `.env.example`, `.gitignore`,
      `tests/conftest.py`, `uv.lock`.
- [ ] **T2: Jerarquía de errores** — `app/errors.py` con `ServiceError` base y
      las **8** subclases de SPEC §7.2, cada una con `status` / `code` /
      `type_uri` / `title`, más un guard de drift contra la matriz.
- [ ] **T3: Problem details + handlers + schemas Pydantic** —
      `app/api/problem.py`, `app/api/exception_handlers.py`
      (`ServiceError`, `RequestValidationError` → **400**, `Exception`) y
      `app/api/schemas.py` (`AuditEventRequest` con `extra="forbid"`,
      `AuditLogResponse` con `serialization_alias="_id"`, `ProblemDetails`).

### Checkpoint: Foundation
- [ ] `uv sync` limpio; `uv run ruff check .` sin violaciones
- [ ] Las 8 excepciones exponen `status`/`code`/`type_uri` correctos
- [ ] Un `ServiceError` lanzado desde donde sea sale como problem details válido
- [ ] Un `RequestValidationError` sale como **`400 VALIDATION_ERROR`**, jamás `422`
- [ ] `/docs` muestra los schemas con `_id` (no `id`) y sin el `422` de FastAPI
- [ ] **Revisión humana antes de continuar**

### Phase 2: Autenticación

- [ ] **T4: Config + token** — `app/config.py` con `pydantic-settings`,
      `SERVICE_API_TOKEN` obligatoria sin default, las 12 variables de SPEC §3.6
      con fail-fast explícito.
- [ ] **T5: Middleware de autenticación** — `app/api/auth.py`: Bearer,
      `secrets.compare_digest`, `401` con `detail` genérico y
      `WWW-Authenticate: Bearer`, registro en `main.py` sobre `/audit/*`.

### Checkpoint: Auth
- [ ] Sin `SERVICE_API_TOKEN` la app **no arranca**, con error que nombra la variable
- [ ] Token ausente, vacío, con esquema distinto o incorrecto ⇒ `401` en los 4 casos
- [ ] El `detail` es **idéntico** en los 4 casos (sin oráculo)
- [ ] El token nunca aparece en logs ni en el cuerpo de respuesta
- [ ] `/health` y `/readyz` siguen accesibles sin token
- [ ] **Revisión humana antes de continuar**

### Phase 3: Core vertical slice — escritura + idempotencia

- [ ] **T6: Lifecycle de Mongo + índices** — `app/repositories/mongodb.py`:
      `AsyncMongoClient`, `ping`, y los índices de SPEC §6.3 (único, ambos
      compuestos con `_id desc`, TTL condicional).
- [ ] **T7: Puerto + doble de test** — `app/services/ports.py`
      (`AuditLogRepository` como `Protocol` + dataclasses de dominio) y
      `tests/fakes/fake_audit_log_repository.py` con contador de llamadas y
      barreras para `DuplicateKeyError` / `DocumentTooLarge`.
- [ ] **T8: Repositorio Mongo — escritura** — `insert` y `find_replay`, con el
      mapeo driver → dominio de SPEC §6.4.
- [ ] **T9: AuditLogService.create** — la idempotencia de SPEC §5.3: reloj del
      servidor, Barrera 1, Barrera 2, `received_at`.
- [ ] **T10: Endpoint `POST /audit/logs`** — `routers/audit_logs.py`,
      `dependencies.py`, `main.py`; `413` por `details` grande; `201` + `Location`.
- [ ] **T11: Carrera bajo concurrencia + replay** — N `POST` concurrentes del mismo
      evento ⇒ exactamente **1 documento**, N-1 respuestas `200` de replay.

### Checkpoint: Core slice ★ el más importante del plan
- [ ] `POST /audit/logs` devuelve `201` + `Location` + los 7 campos
- [ ] Un `POST` repetido devuelve `200` + `idempotent_replay: true` + `X-Idempotent-Replay`
- [ ] **T11 pasa:** bajo concurrencia hay exactamente 1 documento en Mongo
- [ ] El replay se emite tanto si salta la Barrera 1 como si salta la Barrera 2
- [ ] `details` ausente ⇒ `{}` en el documento (nunca `null`), y `text.delete` funciona
- [ ] Un `checksum` de formato arbitrario (no-hex, con guiones) se acepta y persiste
- [ ] Clave desconocida en el body ⇒ `400`, y `details` con claves anidadas ⇒ `201`
- [ ] `pydantic` no se importa en `app/services/` ni en `app/repositories/`, y
      `pymongo` no se importa en `app/api/` ni en `app/services/`
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa
- [ ] **Revisión humana antes de continuar**

### Phase 4: Lecturas

- [ ] **T12: `GET /audit/logs?skip&limit`** — **array de primer nivel**, orden
      `performed_at desc, _id desc`, límites validados, serialización de
      `_id` hex y fechas RFC 3339 `Z`.
- [ ] **T13: `GET /audit/logs/checksum/{checksum}`** — path param, mismo orden,
      `200 []` si no hay resultados.

### Checkpoint: Lecturas
- [ ] Ambos `GET` devuelven un **array JSON de primer nivel**, no un objeto
- [ ] Un elemento contiene los **7** campos de `models.AuditLog`, sin nulos
- [ ] `_id` es hex de 24 chars; `performed_at` y `received_at` terminan en `Z`
- [ ] El orden es `performed_at desc` y es estable entre dos llamadas con los mismos `skip`/`limit`
- [ ] `skip`/`limit` fuera de rango ⇒ `400`, y **nunca** recorte silencioso
- [ ] Checksum sin resultados ⇒ `200` + `[]` (no `404`)
- [ ] Checklist de contrato SPEC §9 satisfecha
- [ ] **Revisión humana antes de continuar**

### Phase 5: Endurecimiento y cierre

- [ ] **T14: Middleware** — eco de `X-Request-ID`, `415`, `413` por body, CORS,
      log de acceso con duración. Orden `401 → 415 → 413 → 400`.
- [ ] **T15: Matriz de errores completa** — test parametrizado sobre las 8
      filas de SPEC §7.2 + la garantía de que **ninguna ruta emite `422`**.
- [ ] **T16: OpenAPI, README y cobertura** — esquema `Bearer` publicado,
      `/openapi.json` honesto, README operativo, cobertura ≥ 85 %.

### Checkpoint: Complete
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa
- [ ] `uv run ruff check .` y `uv run ruff format .` limpios
- [ ] Las 8 filas de la matriz verificadas por test, sin `skip` ni `xfail`
- [ ] Checklist de contrato SPEC §9 en verde
- [ ] Criterios de éxito del SPEC cumplidos
- [ ] **Listo para revisión final del humano**

---

## Task Detail

### T1: Project scaffolding

**Description:** Base del proyecto replicando las convenciones de los dos
hermanos: `uv`, `pytest` + `pytest-cov` + `pytest-asyncio` (`asyncio_mode =
"auto"`, necesario porque Capa 2 y Capa 3 son `async`), `ruff` (`line-length =
88`, select `["E","F","W","I","B","UP","SIM","C4"]`, `extend-exclude = ["*.md"]`
para que `ruff format` no reescriba los snippets de `SPEC.md`), layout de
tests espejo de `app/`. Los `__init__.py` de cada capa llevan docstring que
**encoda la dirección de dependencias**, que es la restricción central del
diseño.

**Acceptance criteria:**
- [ ] `uv sync` completa y crea `uv.lock` **versionado** (es una aplicación, no
      una librería: sin el lock, dos instalaciones resuelven dependencias distintas)
- [ ] `uv run pytest --collect-only` colecta 0 items leyendo la config de
      `pyproject.toml` (pytest devuelve exit 5 con 0 tests, por diseño)
- [ ] `uv run ruff check .` y `uv run ruff format --check .` pasan
- [ ] `.env.example` documenta las **12** variables de SPEC §3.6, con
      `SERVICE_API_TOKEN` marcada obligatoria y **sin valor por defecto**
- [ ] `app.api`, `app.services` y `app.repositories` importan, y ninguno arrastra
      `pymongo`

**Verification:**
- [ ] `uv sync` · `uv run ruff check .` · `uv run ruff format --check .`
- [ ] `uv run pytest --collect-only`
- [ ] `uv run python -c "import app.api, app.services, app.repositories"`
- [ ] Manual: contrastar `.env.example` contra SPEC §3.6, variable por variable

**Dependencies:** None
**Files:** `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`,
`app/__init__.py`, `app/api/__init__.py`, `app/services/__init__.py`,
`app/repositories/__init__.py`, `app/api/routers/__init__.py`,
`tests/__init__.py`, `tests/conftest.py`, `tests/**/__init__.py`
**Scope:** Medium

---

### T2: Jerarquía de errores

**Description:** `app/errors.py` con `ServiceError(Exception)` que lleva `status`,
`code`, `type_uri`, `title` como `ClassVar` y `detail` por instancia, más las 8
subclases de SPEC §7.2. Son el vocabulario compartido por las tres capas: la
Capa 3 las lanza, la Capa 2 decide, la Capa 1 traduce. `errors.py` **no importa
nada de FastAPI**: es un módulo de dominio puro.

**Acceptance criteria:**
- [ ] Las 8 subclases existen con `status`/`code`/`type_uri`/`title` correctos
- [ ] `UnauthorizedError.status == 401`, `ValidationError.status == 400`,
      `AuditStorageError.status == 503`, `PayloadTooLargeError.status == 413`
- [ ] `ServiceError("detalle")` expone `.detail` y `str(exc)` lo incluye
- [ ] Existe un **guard de drift**: un test recorre `ServiceError.__subclasses__()`
      y falla si una clase no está en la matriz de SPEC §7.2 (y al revés)

**Verification:**
- [ ] `uv run pytest tests/unit/test_errors.py`
- [ ] Manual: contrastar la tabla de subclases contra SPEC §7.2
- [ ] **Mutación**: cambiar `AuditStorageError.status` de `503` a `500` debe
      poner el test en rojo (confirma que la matriz no es tautológica)

**Dependencies:** T1
**Files:** `app/errors.py`, `tests/unit/test_errors.py`
**Scope:** Small

---

### T3: Problem details + handlers + schemas Pydantic

**Description:** `app/api/problem.py` construye el cuerpo como `ProblemDetails`
serializado a `application/problem+json`. `app/api/exception_handlers.py`
registra handlers para `ServiceError`, `RequestValidationError` (**→ `400
VALIDATION_ERROR`**, nunca el `422` de FastAPI — SPEC §2.6 y §3.3 D1),
`StarletteHTTPException` (cubre 404/405) y `Exception` (catch-all `500`).
`app/api/schemas.py` declara `AuditEventRequest` (`extra="forbid"`,
`Field(min_length=1)`, `AwareDatetime`, `details: Any`),
`AuditLogResponse` (`id` con `alias="_id"` + `serialization_alias="_id"`,
`populate_by_name=True`) y `ProblemDetails`.

**Acceptance criteria:**
- [ ] Todo error sale con `Content-Type: application/problem+json` y los 6 campos
- [ ] **`RequestValidationError` produce `400 VALIDATION_ERROR`; no existe forma
      de que una ruta emita `422`**
- [ ] `instance` es la ruta **sin** host ni valores de query
- [ ] `AuditLogResponse` serializa **`_id`**, nunca `id`
- [ ] `AuditEventRequest` rechaza clave desconocida y acepta `details` con
      cualquier estructura JSON anidada
- [ ] Ninguna excepción interna se filtra: `detail` no contiene mensajes de driver
      ni stack traces
- [ ] `title` no incluye valores variables — el mismo error da el mismo `title`

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_problem.py tests/unit/api/test_schemas.py`
- [ ] `uv run pytest tests/integration/api/test_openapi.py` (el `_id` no está en
      `/docs` todavía: el endpoint llega en T10; hasta entonces se valida el
      modelo aislado)
- [ ] Manual: lanzar un `RequestValidationError` desde un test y revisar el body
- [ ] **Mutación**: quitar el `serialization_alias` ⇒ el test de `_id` en rojo;
      quitar el handler de `RequestValidationError` ⇒ el test de `422` en rojo

**Dependencies:** T2
**Files:** `app/api/problem.py`, `app/api/exception_handlers.py`,
`app/api/schemas.py`, `tests/unit/api/test_problem.py`,
`tests/unit/api/test_schemas.py`
**Scope:** Medium

---

### T4: Config + token

**Description:** `app/config.py` con `Settings(BaseSettings)` de
`pydantic-settings`, las 12 variables de SPEC §3.6. `SERVICE_API_TOKEN` **no
tiene default**: si falta o está vacía, `Settings(...)` lanza `ValidationError`
y la app no arranca. `get_settings()` se invoca **dentro del `lifespan`**, no a
nivel de módulo: importar `app.main` no debe exigir entorno, y el fallo debe
ocurrir al arrancar, que es donde un token ausente es fatal.

**Acceptance criteria:**
- [ ] Los 11 defaults coinciden con SPEC §3.6
- [ ] Sin `SERVICE_API_TOKEN` la app **no arranca**, con un error que **nombra la
      variable pero nunca su valor**
- [ ] Un token vacío o sólo con espacios se trata como ausente
- [ ] Una variable numérica no numérica o ≤ 0 ⇒ error que nombra la variable
      (un timeout o límite en `0` deshabilitaría la protección en silencio)
- [ ] El token nunca aparece en el log ni en el mensaje de error
- [ ] `get_settings(environ=…)` acepta un `Mapping`, para poder probar sin
      mutar el proceso

**Verification:**
- [ ] `uv run pytest tests/unit/test_config.py`
- [ ] Manual: `uvicorn app.main:create_app --factory` sin la variable ⇒ el proceso
      muere con error de configuración; con `MONGO_URI` a un puerto muerto ⇒ la
      app **arranca** y `/readyz` da `503` (comportamiento de T6, se re-verifica
      en T6)

**Dependencies:** T1
**Files:** `app/config.py`, `tests/unit/test_config.py`
**Scope:** Small

---

### T5: Middleware de autenticación

**Description:** `app/api/auth.py`. Extrae el esquema `Bearer`
(comparación case-insensitive según RFC 9110), valida el valor con
`secrets.compare_digest` contra `SERVICE_API_TOKEN`, y devuelve `401
UNAUTHORIZED` con `WWW-Authenticate: Bearer` ante cualquier fallo. El `detail` es
**idéntico** en todos los casos de fallo para no dar un oráculo. Se registra en
`app/main.py` como **el último agregado** para quedar outermost, de modo que el
`401` precede a `415`/`413` de T14.

**Acceptance criteria:**
- [ ] Token ausente, vacío, con esquema distinto o valor incorrecto ⇒ `401` en los
      4 casos, con el **mismo** `title` y `detail`
- [ ] La respuesta incluye `WWW-Authenticate: Bearer`
- [ ] El valor del token nunca aparece en el body, ni en el log, ni en la excepción;
      el log sí registra el **motivo** del rechazo, sin el valor presentado
- [ ] `/health` y `/readyz` responden sin credenciales
- [ ] `app/services/` y `app/repositories/` no saben que la autenticación existe

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_auth.py`
- [ ] Manual: `curl -i localhost:8083/audit/logs -X POST -H 'Content-Type: application/json' -d '{}'`
      sin header ⇒ `401` + `www-authenticate: Bearer`
- [ ] Manual: `curl -i localhost:8083/health` sin header ⇒ `200`

**Dependencies:** T4
**Files:** `app/api/auth.py`, `app/main.py`, `app/api/problem.py`
(+`headers` opcional para el `WWW-Authenticate`), `tests/unit/api/test_auth.py`
**Scope:** Small

---

### T6: Lifecycle de Mongo + índices

**Description:** `app/repositories/mongodb.py`: fábrica de `AsyncMongoClient` con
timeout, `ping` de comprobación, y bootstrap de los índices de SPEC §6.3 —
`(action, entity_type, checksum, performed_at)` **único**,
`(checksum, performed_at desc, _id desc)`, `(performed_at desc, _id desc)` y TTL
sobre `performed_at` **sólo** si `RETENTION_DAYS > 0`. Todo en el `lifespan`. Si
Mongo no responde, la app **arranca igualmente** y es `/readyz` quien reporta
`503`.

**Acceptance criteria:**
- [ ] El `lifespan` hace `ping` y crea los tres índices; el TTL sólo con
      `RETENTION_DAYS > 0`
- [ ] El índice único rechaza un segundo documento con la misma tupla
      `(action, entity_type, checksum, performed_at)`
- [ ] Los compuestos se crean **con** `_id desc` (desempate determinista, §12)
- [ ] Con Mongo inalcanzable la app arranca y `/readyz` devuelve `503`
- [ ] `app/api/routers/health.py` con `GET /health` (siempre `200`) y
      `GET /readyz` (hace `ping` y devuelve `503` si Mongo no responde), ambos
      **fuera** del alcance del middleware de autenticación
- [ ] El cliente se cierra limpiamente al apagar la app

**Verification:**
- [ ] `uv run pytest tests/unit/repositories/test_mongodb_lifecycle.py`
- [ ] `uv run pytest tests/integration/repositories/`
- [ ] Manual: `mongosh` → `db.audit_logs.getIndexes()` y comparar contra SPEC §6.3
- [ ] Manual: con `MONGO_URI` a un puerto muerto, `/health` ⇒ `200` y
      `/readyz` ⇒ `503`

**Dependencies:** T4
**Files:** `app/repositories/mongodb.py`, `app/api/routers/health.py`,
`app/main.py`, `tests/unit/repositories/test_mongodb_lifecycle.py`,
`tests/integration/repositories/test_mongo_audit_log_repository.py`,
`tests/integration/repositories/conftest.py`
**Scope:** Medium

---

### T7: Puerto + doble de test

**Description:** `app/services/ports.py` con el `Protocol` `AuditLogRepository`
(SPEC §5.1) y las dataclasses de dominio `CreateAuditLogCommand`, `ListQuery`,
`NewAuditLog`, `StoredAuditLog`. `tests/fakes/fake_audit_log_repository.py` lo
implementa en memoria, con **contador de llamadas** (para poder afirmar "insert
no se invocó") y barreras para inyectar `DuplicateKeyError` y
`DocumentTooLarge`. Al ser `Protocol` estructural, el fake cumple el contrato sin
herencia.

**Acceptance criteria:**
- [x] El `Protocol` declara los 5 métodos de SPEC §5.1 con las firmas exactas
      (con los nombres propios fijados en T7: ver desviación **12**)
- [x] `FakeAuditLogRepository` satisface el Protocol vía `@runtime_checkable`
- [x] El fake permite inyectar `DuplicateKeyError` y `DocumentTooLarge` a demanda
- [x] El fake cuenta invocaciones de `insert` y `find_replay`, y su almacén es
      observable desde el test (para contar documentos)

**Verification:**
- [x] `uv run pytest tests/unit/repositories/test_protocol.py`
- [x] `uv run pytest tests/unit/domain/test_models.py`
- [x] Manual: `grep -r "pymongo" app/services/` ⇒ sin resultados (sólo el
      docstring de `app/services/__init__.py` lo nombra)

**Dependencies:** T2
**Files:** `app/repositories/protocol.py`,
`tests/fakes/fake_repository.py`,
`tests/unit/domain/test_models.py`,
`tests/unit/repositories/test_protocol.py`
**Scope:** Small

---

### T8: Repositorio Mongo — escritura

**Description:** `MongoAuditLogRepository.insert()` construyendo el documento con
`_id = ObjectId()`, `details` verbatim (`{}` si no vino), `performed_at` como
recibido y `received_at` del servidor, mapeando los errores del driver según
SPEC §6.4. `find_replay()` busca por los cuatro campos de la clave de
idempotencia. Ésta es la Barrera 2, la que garantiza la corrección del control
de duplicados aunque la Barrera 1 desapareciera. En la misma tarea se crea
`serialization.py`, que es el **único** lugar donde un documento BSON se
convierte en el dict de la API (`ObjectId` → hex, `Date` → RFC 3339 `Z`); sin
esa centralización, cada endpoint acabaría serializando por su cuenta.

**Acceptance criteria:**
- [x] `insert` escribe `_id` como `ObjectId` y guarda las fechas como BSON `Date`
- [x] `details` ausente ⇒ `{}` en el documento, **nunca** `null`
- [x] `DuplicateKeyError` (11000) se traduce a la señal de replay que dispara el
      mismo `200` que la Barrera 1
- [x] `DocumentTooLarge` y los errores de conexión se traducen según SPEC §6.4;
      ningún `PyMongoError` escapa sin traducir
- [x] `serialization.py` devuelve los **7** campos de `models.AuditLog`, con
      `_id` en hex de 24 chars y las dos fechas con `Z`
- [x] `app/repositories/` no importa nada de `app/api/` ni de `app/services/`

**Verification:**
- [x] `uv run pytest tests/unit/repositories/test_serialization.py`
- [x] `uv run pytest tests/unit/repositories/test_mongo_audit_log_repository.py`
- [x] `uv run pytest tests/integration/repositories/test_mongo_audit_log_repository.py -v`
- [x] Manual: `db.audit_logs.findOne({checksum: "<c>"})` después de un insert
      (ejecutado: devuelve el documento con `_id` `ObjectId` y fechas BSON `Date`)
- [x] **Mutación**: quitar la traducción de `DuplicateKeyError` ⇒ los tests de
      replay (unitario y de integración) en rojo — verificado

**Dependencies:** T6, T7
**Files:** `app/repositories/mongo_audit_log_repository.py`,
`app/repositories/serialization.py`,
`tests/unit/repositories/test_serialization.py`,
`tests/unit/repositories/test_mongo_audit_log_repository.py`,
`tests/integration/repositories/test_mongo_audit_log_repository.py`
**Scope:** Medium

---

### T9: AuditLogService.create

**Description:** Orquestación del caso de uso de escritura (SPEC §5.3):
reloj del servidor → Barrera 1 (`find_replay`) → Barrera 2 (`insert`). Punto
único de la regla de idempotencia; no toca HTTP ni el driver. Es el lugar donde
se decide que el replay **no es un error**.

**Acceptance criteria:**
- [x] Si `find_replay()` encuentra el evento, devuelve el `StoredAuditLog`
      existente con `replay=True` y **`insert()` no se invoca nunca**
      (verificable con el contador del fake)
- [x] Si no lo encuentra, inserta y devuelve `replay=False`
- [x] La señal de `DuplicateKeyError` de la Barrera 2 produce el **mismo**
      resultado observable que la Barrera 1
- [x] `received_at` lo pone el reloj **de la Capa 3**, no uno inyectable del
      servicio (dev. **14**); `performed_at` es el del emisor, sin tocar
- [x] `app/services/` no importa `pymongo`

**Verification:**
- [x] `uv run pytest tests/unit/services/test_audit_log_service.py` — 6 tests
- [x] Manual: `grep -r "pymongo" app/services/` ⇒ sin resultados (sólo el
      docstring de `app/services/__init__.py` lo nombra)
- [x] **Mutación**: el replay deja de ser distinguible (`replay=False` en los
      dos caminos, lo que la Capa 1 traduciría como no-replay) ⇒ 3 tests de
      replay en rojo — verificado

**Dependencies:** T7, T8
**Files:** `app/services/audit_log_service.py`,
`tests/unit/services/test_audit_log_service.py`
**Scope:** Small

---

### T10: Endpoint `POST /audit/logs`

**Description:** Cerrar el primer camino vertical completo.
`routers/audit_logs.py` recibe `AuditEventRequest` de Pydantic, mide
`len(json.dumps(details))` contra `MAX_DETAILS_BYTES` (`413`), construye el
`CreateAuditLogCommand`, llama al servicio y devuelve `201` + `Location: /
audit/logs/checksum/<escaped>`, o `200` + `X-Idempotent-Replay: true` en replay.
`dependencies.py` inyecta el servicio desde `app.state`; `main.py` compone todo.

**Acceptance criteria:**
- [x] Body válido ⇒ `201`, `Location` y los **7** campos; el documento existe en Mongo
- [x] Body repetido ⇒ `200` + `idempotent_replay: true` + `X-Idempotent-Replay: true`
- [x] Body inválido, clave desconocida o `performed_at` sin offset ⇒ `400` con el
      `code` correcto
- [x] `details` de más de 64 KiB ⇒ `413`, y el documento **no** se escribe
- [x] Un `checksum` de formato arbitrario (no-hex, con guiones, con mayúsculas) se
      **acepta y persiste** — no hay validación de formato
- [x] `details` ausente ⇒ `{}` guardado; `details` con claves anidadas ⇒ verbatim
- [x] El `Location` escapa con `quote(..., safe="")` para que un `checksum` con
      `/` o comillas no rompa la URL
- [x] `app/api/routers/audit_logs.py` no importa `pymongo` ni `app.repositories`

**Verification:**
- [x] `uv run pytest tests/integration/api/test_create_audit_log.py -v` — 10 tests
      (294 suite completa, 100 % de cobertura)
- [ ] Manual: `curl -i -X POST localhost:8083/audit/logs -H 'Authorization: Bearer <tok>'
      -H 'Content-Type: application/json' -d '{"action":"pdf.extract","entity_type":"document",
      "checksum":"abc123","details":{"page_count":3},"performed_at":"2026-10-05T12:34:56Z"}'`
- [ ] Manual: el mismo `curl` repetido ⇒ `200` y `X-Idempotent-Replay: true`

**Dependencies:** T3, T5, T9
**Files:** `app/api/routers/audit_logs.py`, `app/api/dependencies.py`,
`app/main.py`, `tests/integration/api/test_create_audit_log.py`
**Scope:** Medium

---

### T11: Carrera bajo concurrencia + replay

**Description:** Prueba de que la doble barrera funciona. Lanzar N peticiones
`POST /audit/logs` concurrentes **con el mismo evento** contra MongoDB real y
verificar que hay exactamente un documento, que una respuesta es `201` y las
N-1 restantes `200` de replay. Y — esto es lo importante — comprobar por
**mutación** que el test **falla** si se desactiva la Barrera 2. Es la diferencia
entre una defensa real y una decorativa.

**Acceptance criteria:**
- [x] Con N=10 concurrentes: exactamente 1 documento, 1 `201`, 9 `200` de replay
- [x] **El test falla si se desactiva la traducción de `DuplicateKeyError`**
- [x] Repite el escenario 20 veces sin flakiness (sin `sleep`, sin polling)
- [x] El gate del test es la **Capa 3 real** sobre una colección instrumentada, no
      un doble: con un fake, las 10 peticiones se serializarían solas y la
      Barrera 1 las cortaría todas, dejando la Barrera 2 sin exertir

**Verification:**
- [x] `uv run pytest tests/integration/api/test_idempotency_race.py -v`
- [x] Manual: comentar la traducción de `DuplicateKeyError` ⇒ el test debe romper;
      al restaurarlo, vuelve a verde — **verificado** (los dos tests rompen con
      `E11000` crudo: el de servicio y el vertical HTTP)
- [x] `uv run pytest` (suite completa verde: 296 tests, 100 % de cobertura)

**Dependencies:** T10
**Files:** `tests/integration/api/test_idempotency_race.py`
**Scope:** Small

---

### T12: `GET /audit/logs?skip&limit`

**Description:** Cerrar la lectura global, empezando por la invariante más
importante del contrato: **la respuesta es un array de primer nivel**
(`JSONResponse(content=[...])` con `response_model=list[AuditLogResponse]`), no
`{"logs": […]}` ni `{"items": […]}`. La tarea cierra las tres capas de la
lectura: `repo.list_page()` (cursor con `.sort().skip().limit()`),
`service.list_page()` (validación de `skip`/`limit` y aplicación de
`DEFAULT_LIMIT`) y el router. La serialización BSON → dict la aporta
`serialization.py`, ya creado en T8. Orden `performed_at desc, _id desc`;
`skip`/`limit` fuera de rango ⇒ `400`, nunca recorte.

**Acceptance criteria:**
- [ ] La respuesta **parsea como array JSON de primer nivel** (un test que haga
      `isinstance(body, list)`, no que busque una clave)
- [ ] Cada elemento contiene los **7** campos de `models.AuditLog`, sin nulos
- [ ] `_id` es hex de 24 chars; `performed_at` y `received_at` terminan en `Z` y
      los parsea `time.Time` de Go
- [ ] El orden es `performed_at desc` con desempate estable por `_id`
- [ ] `skip < 0`, `skip > MAX_SKIP`, `limit < 1`, `limit > MAX_LIMIT` ⇒ `400
      VALIDATION_ERROR`; `limit` ausente ⇒ `DEFAULT_LIMIT`
- [ ] Sin resultados ⇒ `200` + `[]`
- [ ] `GET` **no** registra evento de auditoría (AUDA no se autoaudita)

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_list_audit_logs.py -v`
- [ ] Manual: `curl -s "localhost:8083/audit/logs?skip=0&limit=2" -H 'Authorization: Bearer <tok>'`
      | `python -c "import json,sys; b=json.load(sys.stdin); print(type(b).__name__, len(b))"`
      ⇒ debe imprimir `list 2`
- [ ] Manual: `curl -i ".../audit/logs?limit=9999"` ⇒ `400`

**Dependencies:** T10
**Files:** `app/repositories/mongo_audit_log_repository.py`,
`app/services/audit_log_service.py`, `app/api/routers/audit_logs.py`,
`tests/integration/api/test_list_audit_logs.py`
**Scope:** Medium

---

### T13: `GET /audit/logs/checksum/{checksum}`

**Description:** Cerrar la lectura filtrada, también en las tres capas:
`repo.list_by_checksum()` (filtro por `checksum` + índice compuesto de SPEC §6.3),
`service.list_by_checksum()` y el router con el path param `checksum` (el cliente
Go ya lo construye con `PathEscape`). Mismo orden, misma forma de array,
`200 []` si no hay resultados — **nunca `404`**. Sin paginación, porque el cliente
Go no la envía (SPEC §2.8, D12); se documenta el riesgo.

**Acceptance criteria:**
- [ ] El path es exactamente `/audit/logs/checksum/{valor}` (mismo path que
      verifica `client_test.go:156`)
- [ ] Filtra **sólo** por `checksum`, con el orden de SPEC §8.1
- [ ] **Sin `.limit()` en el cursor** (D12): el cliente Go no envía paginación
- [ ] Checksum sin resultados ⇒ `200` + `[]` (no `404`)
- [ ] `GET /audit/logs/checksum/` (sin valor) ⇒ `404 NOT_FOUND`, no `500`
- [ ] La respuesta también es un **array de primer nivel**

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_list_by_checksum.py -v`
- [ ] Manual: `curl -s "localhost:8083/audit/logs/checksum/abc123" -H 'Authorization: Bearer <tok>'`
      | `python -c "import json,sys; print(type(json.load(sys.stdin)).__name__)"`
      ⇒ `list`
- [ ] Manual: un checksum inexistente ⇒ `200` con `[]`

**Dependencies:** T12
**Files:** `app/repositories/mongo_audit_log_repository.py`,
`app/services/audit_log_service.py`, `app/api/routers/audit_logs.py`,
`tests/integration/api/test_list_by_checksum.py`
**Scope:** Small

---

### T14: Middleware

**Description:** `app/api/middleware.py` con, **en este orden**: autenticación
(`401`, ya registrada en T5 y outermost), `ContentTypeMiddleware` (`415` en
POST), `BodySizeLimitMiddleware` (`413` por `MAX_BODY_BYTES` sobre
`Content-Length`), `RequestIdMiddleware` (eco de `X-Request-ID`), CORS
(`GET, POST, OPTIONS`) y log de acceso con duración. El orden se resuelve en un
único sitio, `create_app`, y hay tests que fijan el orden **real**.

**Acceptance criteria:**
- [ ] Orden correcto: `401 → 415 → 413 → 400`
- [ ] Body de > 1 MiB ⇒ `413`; `Content-Type: text/plain` en POST ⇒ `415`
- [ ] `X-Request-ID` entrante se devuelve igual; si falta, se genera uno
- [ ] CORS responde al preflight (`200`, que es lo que emite Starlette; anotado
      en el test en vez de envolver la librería)
- [ ] El límite mira `Content-Length` y **nunca** lee el body: una subida enorme
      no entra en memoria
- [ ] Un `Content-Length` ausente o no numérico cuenta como `0` en vez de reventar

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_middleware.py`
- [ ] Manual: sin token y body de 2 MiB ⇒ `401` (el auth va primero); con token
      y `text/plain` y body de 2 MiB ⇒ `415`

**Dependencies:** T10
**Files:** `app/api/middleware.py`, `app/main.py`,
`tests/unit/api/test_middleware.py`
**Scope:** Medium

---

### T15: Matriz de errores completa

**Description:** Test de integración parametrizado que recorre las **8** filas de
la matriz de SPEC §7.2 y comprueba, para cada escenario, el `status` HTTP **y**
el `code`. Cubre además la garantía derivada de `httpclient/client.go:39` — todo
`status >= 300` devuelve un body parseable como problem — y la garantía
**negativa**: **ninguna ruta emite `422`**.

**Acceptance criteria:**
- [ ] Las 8 filas de SPEC §7.2 cubiertas con su `status` y `code` esperados
- [ ] Un test verifica la regla de `httpclient/client.go:39` para todo `>= 300`
- [ ] Un test verifica que **ningún endpoint** devuelve `422` en ningún escenario
      de la matriz
- [ ] `PUT` y `DELETE` sobre `/audit/logs` ⇒ `405 METHOD_NOT_ALLOWED` (append-only)
- [ ] Los faults se inyectan en la **base de datos**, no con `patch` sobre `app/`:
      así lo que se prueba es el mapeo driver → status de producción
- [ ] Sin casos `xfail` ni `skip`

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_error_matrix.py -v`
- [ ] Manual: contrastar los IDs de los tests contra SPEC §7.2
- [ ] **Mutación**: `status 503→500` en `AuditStorageError` ⇒ la fila en rojo

**Dependencies:** T12, T13, T14
**Files:** `tests/integration/api/test_error_matrix.py`,
`tests/integration/api/conftest.py`
**Scope:** Medium

---

### T16: OpenAPI, README y cobertura

**Description:** Pydantic genera los schemas de request y response, así que esta
tarea es más corta que su equivalente en Persistencia: hay que **verificar** que
`/openapi.json` publica el esquema de seguridad `Bearer` en las 3 rutas, que los
schemas muestran `_id` (no `id`), y que **no aparece el `422` de FastAPI** en
ninguna operación. Redactar el README operativo (12 variables, arranque,
contrato, `curl` con el token por endpoint, cómo levantar MongoDB para los tests
de integración) y llevar la cobertura al umbral.

**Acceptance criteria:**
- [ ] `/openapi.json` documenta request, response y seguridad de las 3 rutas
- [ ] El esquema de `AuditLogResponse` declara la propiedad **`_id`**
- [ ] **Ninguna operación lista `422`** entre sus respuestas
- [ ] `POST /audit/logs` documenta `201`, `400`, `401`, `413`, `415`
- [ ] README con variables de entorno, arranque
      (`uv run uvicorn app.main:create_app --factory --port 8083`, tal como
      SPEC §6.5), contrato, ejemplo `curl` por endpoint, y con cómo levantar el
      MongoDB que necesitan los tests
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa **sin excluir código de
      producción** para alcanzar el umbral

**Verification:**
- [ ] `uv run pytest --cov=app --cov-fail-under=85`
- [ ] `uv run ruff check .` · `uv run ruff format --check .`
- [ ] Manual: abrir `http://localhost:8083/docs` y comprobar las 3 rutas, el
      candado `Bearer`, `_id` en el schema de respuesta y la ausencia de `422`
- [ ] Manual: contrastar los IDs de los tests contra la checklist de SPEC §9

**Dependencies:** T15
**Files:** `app/api/routers/audit_logs.py`, `app/main.py`, `README.md`,
`tests/integration/api/test_openapi.py`
**Scope:** Small

---

## Checkpoint Summary

| Punto | Tareas | Se verifica |
|---|---|---|
| **Foundation** | T1–T3 | Errores, problem details, **ausencia de `422`**, `_id` en el schema |
| **Auth** | T4–T5 | **Fail-fast sin token**; `401` uniforme sin oráculo |
| **Core slice** ★ | T6–T11 | **`POST` + idempotencia correcta bajo carrera** |
| **Lecturas** | T12–T13 | **Array de primer nivel** y compatibilidad con `models.AuditLog` |
| **Complete** | T14–T16 | Matriz de 8 errores, OpenAPI, cobertura, lint |

## Risks and Mitigations

| Riesgo | Impacto | Mitigación | Tarea |
|---|---|---|---|
| Respuesta de lectura mal envuelta ⇒ `502` en todo el pipeline | Muy alto | Array de primer nivel como invariante; checklist §9 | T12 |
| `422` de FastAPI ⇒ `WriteHeader(0)` hace entrar en panic al Orquestador | Muy alto | Handler de `RequestValidationError` → `400`; test que prohíbe `422` | T3, T15 |
| `_id` renombrado a `id` ⇒ `ID == ""` en Go, sin error visible | Muy alto | `serialization_alias` + test + verificación en OpenAPI | T3, T10, T16 |
| Go no manda el token ⇒ auditoría detenida en silencio | Alto | `SERVICE_API_TOKEN` sin default: la app no arranca | T4, T5 |
| Carrera entre `find_replay()` e `insert()` | Alto | Doble barrera; el índice único cierra la carrera; T11 lo verifica por mutación | T8, T9, T11 |
| Token filtrado en logs o respuestas | Alto | `detail` genérico; comparación en tiempo constante | T5 |
| `details` enorme cerca del límite BSON | Medio | `MAX_DETAILS_BYTES` + `DocumentTooLarge → 413` | T4, T8, T10 |
| Evento legítimo con clave nueva ⇒ `400` y evento perdido | Medio | `details` como válvula de escape; `action` no es enum | T10 |
| Listado por checksum sin cota | Medio | Volumen real ~4 filas; mejorarlo requiere un cambio en Go (§2.7, opcional) | T13 |
| `_id` ausente en los compuestos ⇒ paginación no determinista | Medio | `_id desc` como desempate | T6 |
| Tests de integración sin `mongod` | Medio | Documentar cómo levantarlo en el README; decir explícitamente en el checkpoint si esa parte no corrió | T1, T16 |
| Mongo caído al arrancar | Bajo | La app arranca y `/readyz` reporta `503` | T6, T14 |
| Contrato del Orquestador cambia después | Medio | Checklist §9 + `client_test.go` | T15, T16 |

## Parallelization Opportunities

- **Paralelo seguro:** T2 y T4 tras T1; T5 y T6 tras T4.
- **Secuencial obligatorio:** T7 → T8 → T9 → T10 → T11. Es la cadena del camino
  crítico y cada eslabón depende del anterior.
- **Paralelo tras T10:** T12, T13, T14 son independientes entre sí en su lógica,
  pero **tocan el mismo archivo** `routers/audit_logs.py`. Serializarlos o
  ramificar.
- **Coordinación:** cualquier cambio de contrato obliga a revisar SPEC §2 y §9 y
  a avisar al Orquestador **antes** de implementar (§2.7).

## Open Questions

Ninguna abierta: las diecisiete decisiones (D1–D17) están tomadas y
documentadas en SPEC §12. Las dos consecuencias que recaen sobre el Orquestador
están en §2.7 y §14, y quedan pendientes de tu integración.

---

## Nota de handoff para el orquestador

Antes de conectar este servicio, el cliente Go necesita (detalle con líneas en
SPEC §2.7):

1. `AUDIT_LOG_API_TOKEN` en `config.go`, **sin default**.
2. `httpclient.New(baseURL, timeout, token)` + `Authorization: Bearer` en **todas**
   las requests (`httpclient/client.go:17-31`).
3. `auditlog.NewClient(...)` y `cmd/orchestrator/main.go:35` propagan el token.
4. `audit_service.go:38`: un `401` es error de cableado ⇒ `logger.Error`, sin
   reintento.
5. Actualizar los 5 tests de `auditlog/client_test.go` con el header y añadir el
   caso `401` sin token.
6. *(Opcional)* `ListByChecksum(skip, limit)` para acotar el listado por checksum.

> **Orden de despliegue:** AUDA **no puede arrancar** sin `SERVICE_API_TOKEN`, así
> que los puntos 1-4 son un prerrequisito del despliegue de AUDA, no un trabajo
> paralelo. El fallo se manifiesta como un error de arranque, no como una
> auditoría detenida en silencio.