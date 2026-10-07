# SDD — Audit Log Microservice (`pdf-extractext`) · AUDA

> **Fase 1 (Discovery & Requirements) + Fase 2 (Planning & System Design).**
> Documento de diseño para revisión humana. **No contiene código de
> implementación** (eso es Fase 3, empieza tras la aprobación de este documento).
>
> **Estado:** pendiente de aprobación. No se ha escrito una línea de código.
>
> El plan de ejecución vive en [`tasks/plan.md`](./tasks/plan.md); el checklist
> operativo en [`tasks/todo.md`](./tasks/todo.md).

---

## 0. Alcance del documento

Este servicio es **AUDA** (Auditoría), la cuarta pieza del ecosistema
`pdf-extractext`. Su responsabilidad es **recibir, persistir y consultar los
registros de auditoría** de todos los eventos y transacciones del ecosistema,
que le envía el **Orquestador** (Go, `:8080`).

La diferencia con su hermano `PersistenceMicroservices-pdf-extractext` es
**estructural y no cosmética**: Persistencia es un CRUD con `PUT`, `DELETE` y
`409` por duplicado. AUDA es **append-only**: no existe verbo que modifique o
borre un log. Esa única diferencia elimina la mitad de los casos de uso, y es
la razón de que casi todo el diseño de Persistencia (control de duplicados,
inmutabilidad, semántica de `ausente` vs `null`) no aplique aquí.

---

## 1. Normativa aplicable

| Documento | Qué aporta |
|---|---|
| **RFC 9457** (jul-2023) | *Problem Details for HTTP APIs* — **vigente**. Los cinco miembros pedidos (`type`, `title`, `status`, `detail`, `instance`) son los canónicos de §3.1; `code` es extensión permitida por §3.2 |
| ~~RFC 7807~~ (2016) | Obsoleto por RFC 9457. No se cita |
| **RFC 9110** | Semántica de códigos de estado (§15.5.10 `409`, §15.5.2 `WWW-Authenticate`) |
| **RFC 6750** | `Authorization: Bearer` y la cabecera `WWW-Authenticate` en `401` |
| **RFC 3339** / ISO 8601 | Formato de fecha-hora de `performed_at` (entrada) y de `performed_at` / `received_at` (salida) |
| **BSON spec** | `_id` como `ObjectId` de 12 bytes → 24 caracteres hexadecimales |

Toda referencia a "el orquestador" es al módulo Go
`../Orquestador/orchestator-microservices-pdf-extractext`
(`validationmicroservices-pdf-extractext`).

---

## 2. Contrato de entrada — análisis del orquestador

El cliente de Audit Log **ya está escrito y testeado** en Go. Este diseño no
inventa una API: la deduce del consumidor. Los 5 tests de
`internal/clients/auditlog/client_test.go` **fijan** método, path, `Content-Type`,
`201` y la forma del body decodificado. Son la primera línea de defensa del
contrato.

| Archivo del orquestador | Qué aporta |
|---|---|
| `internal/clients/auditlog/client.go` | Rutas, verbos, cuerpos, forma de la respuesta |
| `internal/models/audit_log.go` | `AuditEvent` (lo que emite) y `AuditLog` (lo que decodifica) |
| `internal/models/checksum.go` | `type Checksum string` → serializa como string JSON |
| `internal/services/audit_service.go` | Fire-and-forget, `maxEmitAttempts=2`, `FetchLogs` |
| `internal/services/pdf_service.go` | Qué emite tras una extracción: `entity_type`, `details` |
| `internal/services/text_service.go` | Qué emite en create/update/delete; el `GET` **no** emite |
| `internal/handlers/audit_handler.go` | Defaults `skip=0` / `limit=10`, proxy, `502` de último recurso |
| `internal/httpapi/httpapi.go` | Cómo el orquestador escribe sus propios problem details |
| `internal/httpclient/client.go` | **La regla dura**: todo `status >= 300` debe ser problem |
| `internal/httpclient/problem.go` | Sólo 4 campos declarados; el resto se ignora |
| `internal/config/config.go` | `AUDIT_LOG_BASE_URL`, default `http://localhost:8083` |
| `internal/clients/auditlog/client_test.go` | El contrato, verificado desde el consumidor |

### 2.1 Transporte

| Parámetro | Valor | Origen |
|---|---|---|
| Base URL | `http://localhost:8083` (`AUDIT_LOG_BASE_URL`) | `config.go:15,40` |
| Puerto de AUDA | `8083` | derivado del default del orquestador |
| Timeout del cliente Go | 10 s | `config.go:16` |
| Timeout de una emisión | 10 s (`context.WithTimeout` sobre `WithoutCancel`) | `audit_service.go:29` |
| Media type de entrada | `application/json` (sólo POST) | `client.go:19,34` |
| Media type de salida esperada | `application/json` (sólo GET) | `client_test.go:124,159` |
| Autenticación actual | **ninguna** | `httpclient.New(baseURL, timeout)` |

### 2.2 Rutas

| # | Verbo | Ruta | Éxito | Note el cliente Go |
|---|---|---|---|---|
| 1 | `POST` | `/audit/logs` | **`201`** (`200` sólo en replay idempotente, §6.4) | `client.go:34` |
| 2 | `GET` | `/audit/logs?skip=<int>&limit=<int>` | `200` + **array pelado** | `client.go:39-40` |
| 3 | `GET` | `/audit/logs/checksum/{checksum}` | `200` + **array pelado** | `client.go:46-47` |

**No hay `PUT` ni `DELETE`.** Se responden `405 METHOD_NOT_ALLOWED` (§6.2): un
log de auditoría que se puede editar o borrar no es una auditoría.

### 2.3 Cuerpo de entrada — `models.AuditEvent`

```go
type AuditEvent struct {
    Action      OperationType `json:"action"`
    EntityType  string        `json:"entity_type"`
    Checksum    Checksum      `json:"checksum"`
    Details     any           `json:"details,omitempty"`
    PerformedAt time.Time     `json:"performed_at"`
}
```

Lo que el orquestador emite hoy, verificado en el código:

| `action` | `entity_type` | `checksum` | `details` | Origen |
|---|---|---|---|---|
| `pdf.extract` | `document` | SHA-256 del texto | `{"page_count": N}` | `pdf_service.go:42-46` |
| `text.create` | `text` | idem | `{"name": "..."}` | `text_service.go:33-37` |
| `text.update` | `text` | idem | `{"name": "..."}` | `text_service.go:56-60` |
| `text.delete` | `text` | idem | **ausente** (`omitempty` con nil) | `text_service.go:71-73` |

El `GET /api/v1/texts/{checksum}` **no** emite evento: leer no es una acción
auditable. Decisión del orquestador, respetada sin discusión.

### 2.4 Forma de las respuestas

`models.AuditLog` — lo que el orquestador decodifica **estrictamente** en ambos
`GET`. Los siete campos son obligatorios; si falta alguno, queda en su valor
cero y el orquestador observa datos vacíos sin enterarse:

```json
[
  {
    "_id":          "6f1c9a2b3d4e5f60718293a4",
    "action":       "pdf.extract",
    "entity_type":  "document",
    "checksum":     "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "details":      { "page_count": 12 },
    "performed_at": "2026-10-05T12:34:56.789Z",
    "received_at":  "2026-10-05T12:34:57.041Z"
  }
]
```

| Campo | Tipo | Nota |
|---|---|---|
| `_id` | `string` | hex de 24 chars del `ObjectId` de Mongo. **Nunca** `{"$oid":…}` (§3.4) |
| `action` | `string` | eco |
| `entity_type` | `string` | eco |
| `checksum` | `string` | eco |
| `details` | `any` | eco; siempre presente, `{}` si el emisor lo omitió |
| `performed_at` | `string` | RFC 3339 UTC con `Z` y milisegundos — lo parsea `time.Time` |
| `received_at` | `string` | RFC 3339 UTC con `Z` — **lo añade el servidor**, Go lo ignora |

**El envoltorio `{"logs": […]}` lo pone el Orquestador**, en
`dto.AuditLogsResponse` (`audit_handler.go:42`). AUDA devuelve el array pelado.

### 2.5 Los 5 puntos donde el contrato puede romperse en silencio

| # | Punto | Qué exige el Go | Qué pasa si el diseño se equivoca |
|---|---|---|---|
| **H1** | Forma de la respuesta de lectura | `client.go:40` y `:47` hacen `Do(..., &logs)` con `logs []models.AuditLog` | Si AUDA devuelve `{"logs":[…]}`, `json.Decode` falla → el orquestador responde **`502 Bad Gateway`**. AUDA "funciona bien" y el pipeline se rompe |
| **H2** | Todo `status >= 300` | `httpclient/client.go:39-44` + `ParseProblem` | Todo error debe ser JSON con `type`, `title`, `status`, `detail`. Un `500` con body plano degrada a `fmt.Errorf` genérico y el orquestador responde `502` |
| **H3** | `_id` como string | `models.AuditLog.ID string` | Debe serializarse como hex de 24 chars. Pydantic renombra `_id` → `id` por defecto si no se aliasa: el orquestador leería `ID == ""` **sin ningún error visible** |
| **H4** | `details` es `any` | `AuditEvent.Details any` con `omitempty` | No se puede exigir `object`: el tipo declarado acepta **cualquier** valor JSON. Exigir `dict` rompería la extensibilidad declarada por el contrato |
| **H5** | `Authorization` | `httpclient.New(baseURL, timeout)` **no** manda token | Si AUDA exige Bearer y el Go no lo manda, **todo `POST` da `401`**, el orquestador loguea un `Warn` y **la auditoría entera deja de crecer sin que nada se encienda** (§2.6) |

### 2.6 Semántica de errores — lo que el orquestador exige de verdad

```go
// internal/httpclient/client.go:39-44 — la única regla dura
if response.StatusCode < 200 || response.StatusCode >= 300 {
    if problem, parseErr := ParseProblem(response.Body); parseErr == nil {
        return problem            // <- el cuerpo DEBE ser el problema
    }
    return fmt.Errorf("unexpected status %d from %s", ...)
}
```

Y el proxy del orquestador:

```go
// internal/handlers/audit_handler.go:73-80
var problem httpclient.Problem
if errors.As(err, &problem) {
    httpapi.WriteProblem(w, problem.Status, problem.Title, problem.Detail)
    return
}
httpapi.WriteProblem(w, http.StatusBadGateway, "Bad Gateway", "audit log service is unreachable")
```

Consecuencias de diseño:

1. **Todo `status >= 300` devuelve JSON con `type`, `title`, `status`, `detail`.**
2. `application/problem+json` es correcto (RFC 9457 §3) y el cliente Go lo lee
   sin negociar media type.
3. Go ignora campos JSON desconocidos (`problem.go:9-14` declara 4) → `instance`
   y `code` son seguros.
4. `errors.As` funciona porque `Problem` implementa `Error()` como **valor**,
   no puntero. El error que viaja es el `Problem` en sí.

#### La trampa del `422` de FastAPI (motiva §3.3)

`ParseProblem` **no falla** ante un body que no es un problem: decodifica
`{"detail":[…]}` a un `Problem{}` **con todos los valores en cero**, y devuelve
`nil` como error. Entonces `audit_handler.go:76` llama
`httpapi.WriteProblem(w, 0, "", "")`, y `WriteHeader(0)` en el servidor Go real
**entra en panic**: `checkWriteHeaderCode` rechaza todo código `< 100`.

> Es decir: si AUDA deja que FastAPI emita su `422` automático, un `POST` con un
> body mal formado **tumba al Orquestador**, no a AUDA. Por eso §3.3 convierte
> el `422` en `400 VALIDATION_ERROR` problem details. No esotiable.

### 2.7 Cambios requeridos en el orquestador Go

El contrato **cambia** en un punto (autenticación) y el cliente debe
adaptarse. Estos son los cambios exactos, con archivo y línea:

```go
// (1) internal/httpclient/client.go:17-31 — token en TODAS las requests
func New(baseURL string, timeout time.Duration, token string) *Client {
    return &Client{
        baseURL: baseURL,
        http:    &http.Client{Timeout: timeout},
        token:   token,
    }
}
func (c *Client) Do(ctx context.Context, method, path, contentType string, body io.Reader, out any) error {
    request, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, body)
    if err != nil { /* … */ }
    if contentType != "" { request.Header.Set("Content-Type", contentType) }
    request.Header.Set("Authorization", "Bearer "+c.token)   // <- nuevo
    // … resto igual
}

// (2) internal/config/config.go — nueva variable obligatoria, sin default
const defaultAuditLogAPIToken = "" // no existe: es obligatoria
cfg.AuditLogAPIToken = getenvRequired("AUDIT_LOG_API_TOKEN")

// (3) cmd/orchestrator/main.go:35 — pasar el token
auditLogClient := auditlog.NewClient(cfg.AuditLogBaseURL, cfg.HTTPTimeout, cfg.AuditLogAPIToken)

// (4) internal/clients/auditlog/client.go:25 — propagar
func NewClient(baseURL string, timeout time.Duration, token string) *Client {
    return &Client{http: httpclient.New(baseURL, timeout, token)}
}

// (5) internal/services/audit_service.go:38 — un 401 NO es transitorio
//     Es error de cableado: log ERROR + sin reintento. Ver SPEC §4.5.

// (6) internal/clients/auditlog/client_test.go — los 5 tests existentes
//     deben mandar Authorization; añadir el caso 401 sin token.
```

> Con el **cambio (1)** el token viaja también en los `GET`. Es una decisión
> deliberada: los logs de auditoría son datos sensibles y no hay razón para que
> la lectura sea un agujero abierto en un servicio interno.

### 2.8 Lo que el contrato **no** exige (y por qué se decide igual)

| Decisión | Elección | Alternativa descartada |
|---|---|---|
| Forma de la respuesta de lectura | **Array de primer nivel** | `{logs: […]}` — rompe H1 |
| `GET` por checksum inexistente | **`200` + `[]`** | `404`: `client_test.go:174` tiene un mock con `404`, pero prueba el camino de error, no una exigencia. `200 []` es semántica de colección y evita un `502` espurio en el proxy |
| Ubicación del checksum | **Path param** (`PathEscape`, ya implementado) | Query param, como en Persistencia: más robusto ante un checksum con `/`, pero rompe el cliente ya testeado. Se asume el riesgo: un checksum real es SHA-256 hex |
| Paginación del listado por checksum | **Ninguna** — el cliente Go no la envía | Añadirla exige cambiar `ListByChecksum(skip, limit)` en Go. Volumen real por checksum en este ecosistema: ~4 eventos. Riesgo documentado (§11) |
| Verbos mutables | **No existen** | Soft-delete con `deleted_at`: agrega estado, índices parciales y reglas de visibilidad a cambio de nada |

---

## 3. Arquitectura de 3 capas

### 3.1 Principio

Dependencia hacia adentro, en un solo sentido:

```
        ┌──────────────────────────────────────────────┐
        │  CAPA 1 · PRESENTACIÓN  (app/api)            │
        │  HTTP · auth · middleware · validación       │
        │  Pydantic · NO conoce MongoDB                │
        └───────────────────┬──────────────────────────┘
                            │  modelo tipado
        ┌───────────────────▼──────────────────────────┐
        │  CAPA 2 · LÓGICA DE NEGOCIO  (app/services)  │
        │  idempotencia · orden · reglas de lectura     │
        │  habla con el puerto, no con el driver       │
        └───────────────────┬──────────────────────────┘
                            │  puerto (Protocol)
        ┌───────────────────▼──────────────────────────┐
        │  CAPA 3 · ACCESO A DATOS  (app/repositories) │
        │  MongoDB · índices · mapeo de documentos     │
        └──────────────────────────────────────────────┘
```

Reglas innegociables:

- `app/api/` **nunca** importa `pymongo`. Recibe el `AuditLogService` ya
  inyectado por `dependencies.py`.
- `app/services/` **nunca** importa `pymongo`. Depende del `Protocol`.
- Sólo `app/repositories/` sabe que existe MongoDB.
- Composition root único: `app/main.py`.
- La autenticación vive **enteramente** en la Capa 1: es una preocupación de
  transporte. El `AuditLogService` no sabe si existe un token.
- La Capa 3 lanza **excepciones de dominio**, nunca HTTP. La traducción a
  códigos de estado ocurre en la Capa 1.

### 3.2 Qué se valida en qué capa

| concern | Capa | Motivo |
|---|---|---|
| Ausencia o invalidez del Bearer token | **1** | Frontera HTTP |
| `Content-Type` distinto de `application/json` | **1** | Frontera HTTP |
| Tamaño del body > `MAX_BODY_BYTES` | **1** | Frontera HTTP |
| JSON mal formado o no es objeto | **1** | Estructura e integridad del JSON |
| Tipos de campo incorrectos | **1** | Estructura e integridad del JSON |
| Campos requeridos ausentes o vacíos | **1** | Estructura de la petición |
| **Clave desconocida en el nivel superior** | **1** | `extra="forbid"` (§3.4) |
| `performed_at` no es RFC 3339 con offset | **1** | Formato de entrada |
| `details` serializado > `MAX_DETAILS_BYTES` | **1** | Límite de transporte |
| `skip` / `limit` fuera de rango | **1** | Estructura de la query |
| **¿Ya existe este evento?** | **2** (consulta a 3) | **Regla de negocio** |
| Orden y límites de la lectura | **2** | Regla de negocio |
| `received_at` lo pone el servidor | **2** | Regla de negocio |
| Traducir excepción → HTTP | **1** | La Capa 3 no conoce HTTP |

> El punto crítico, idéntico en su forma al de Persistencia: la **existencia**
> del evento jamás se valida en la Capa 1. Un `POST` bien formado puede ser
> **aceptado con `200`** en vez de `201`: eso es un dato de negocio, no un error
> de sintaxis. Por eso el replay **jamás** puede ser un `422` de validación.

### 3.3 Pydantic v2 — elección y sus tres consecuencias

Se usa **Pydantic v2** para el contrato (igual que el hermano
`ExtractMicroservice-pdf-extractext`), no el tipado nativo del hermano
`PersistenceMicroservices-pdf-extractext`. La razón: el OpenAPI se genera
automático y correcto, en lugar de escrito a mano, y el esquema queda como
ejecutable junto al código.

| Elemento | Se usa |
|---|---|
| Body de entrada | `AuditEventRequest` (`BaseModel`) como parámetro del router |
| Validación | `Field(min_length=1)`, `AwareDatetime`, `ConfigDict(extra="forbid")` |
| Comando de servicio | `CreateAuditLogCommand` (`@dataclass(frozen=True, slots=True)`) |
| Respuesta | `response_model` con `serialization_alias` |
| Cuerpo de error | `ProblemDetails` (`BaseModel`) serializado a `application/problem+json` |
| Configuración | `pydantic-settings.BaseSettings` |

**D1 — el `422` de FastAPI se convierte en `400`.**
Se registra un handler para `RequestValidationError` que devuelve
`application/problem+json` con `400 VALIDATION_ERROR`. Sin esto, §2.6 explica
por qué el Orquestador entra en panic.

**D2 — `_id` sobrevive a la serialización.**
`AuditLogResponse` declara el campo como `id` con `alias="_id"` y
`serialization_alias="_id"`, más `populate_by_name=True`. FastAPI serializa con
`by_alias=True` por defecto, de modo que el JSON sale con `_id`. **Hay un test
que lo verifica** y que falla si alguien quita el alias: sin él, H3 rompe en
silencio.

**D3 — `action` es `str`, no `enum`.**
Deliberado: agregar una operación nueva en el Orquestador (`text.archive`) no
debe exigir desplegar AUDA. `action` se valida con `min_length=1`, nada más.
El vocabulario vive en el SPEC, no en el código.

### 3.4 `extra="forbid"` — por qué el request rechaza claves desconocidas

| Valor | Body con clave desconocida | Consecuencia |
|---|---|---|
| `"ignore"` | Se acepta y la clave **se descarta** | `201`, y `user_id` no se guarda. **Nadie se entera** |
| **`"forbid"`** | `ValidationError` → `400 VALIDATION_ERROR` | El Orquestador loguea `Warn`, y alguien lo ve **el mismo día** |
| `"allow"` | Se acepta y se guarda en `model_extra` | No se usa: deja el dominio indefinido |

El argumento es la asimetría de los modos de fallo. Un evento legítimo
**rechazado** es visible, ruidoso y se arregla en una tarde. Un evento
**aceptado y descartado** es invisible y permanente: en un log de auditoría, la
peor falla posible es un `201` que miente sobre lo que contiene.

Los costes son reales y asumidos:

- **Acoplamiento de despliegue**: agregar un campo de primer nivel a
  `AuditEvent` obliga a cambiar AUDA. Mitigado por D3: las operaciones nuevas
  no requieren despliegue.
- **Ventana de rollout**: con `ignore`, Orquestador nuevo + AUDA viejo pierde
  datos en silencio. Con `forbid`, esa ventana produce `400` ruidosos.
- **Amortiguación**: cada evento rechazado cuesta 2 intentos
  (`maxEmitAttempts=2`) y una línea de log. Ruido, no daño.

**La válvula de escape existe**: `details: Any` sigue aceptando cualquier JSON,
anidado y sin límite de claves. `forbid` aplica **sólo al nivel superior**.
`details` es, por diseño, el sitio donde va la información que no merece una
columna ni un índice.

### 3.5 Árbol de directorios

```
audit-log-microservice-pdf-extractext/
├── SPEC.md                        ← este documento
├── README.md
├── pyproject.toml                 ← uv + pytest + pytest-asyncio + ruff
├── uv.lock
├── .env.example
├── .gitignore
├── LICENSE
│
├── app/
│   ├── __init__.py
│   ├── main.py                    ← COMPOSITION ROOT: app factory + lifespan
│   ├── config.py                  ← Settings (pydantic-settings)
│   ├── errors.py                  ← ServiceError + 8 subclases
│   │
│   ├── api/                       ══ CAPA 1 · PRESENTACIÓN ══
│   │   ├── __init__.py
│   │   ├── dependencies.py        ← cableado de inyección (repository → service)
│   │   ├── auth.py                ← Bearer token: 401 Unauthorized
│   │   ├── middleware.py          ← request-id, content-type, body-size, CORS, log
│   │   ├── exception_handlers.py  ← ServiceError · RequestValidationError · Exception
│   │   ├── problem.py             ← constructores de cuerpos RFC 9457
│   │   ├── schemas.py             ← AuditEventRequest · AuditLogResponse · ProblemDetails
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── health.py          ← GET /health · GET /readyz  (abiertos)
│   │       └── audit_logs.py      ← POST · GET /audit/logs · GET /audit/logs/checksum/{c}
│   │
│   ├── services/                  ══ CAPA 2 · LÓGICA DE NEGOCIO ══
│   │   ├── __init__.py
│   │   ├── ports.py               ← AuditLogRepository (Protocol) + dataclasses
│   │   └── audit_log_service.py   ← create · list_page · list_by_checksum
│   │
│   └── repositories/              ══ CAPA 3 · ACCESO A DATOS ══
│       ├── __init__.py
│       ├── mongodb.py             ← AsyncMongoClient, índices, lifecycle
│       ├── mongo_audit_log_repository.py ← implementación del Protocol
│       └── serialization.py       ← documento BSON ⇄ dict de la API
│
└── tests/                         ← replica el layout de app/
    ├── conftest.py
    ├── fakes/
    │   ├── __init__.py
    │   └── fake_audit_log_repository.py ← doble en memoria para unit tests
    ├── unit/
    │   ├── __init__.py
    │   ├── test_config.py
    │   ├── test_errors.py
    │   ├── api/
    │   │   ├── __init__.py
    │   │   ├── test_problem.py
    │   │   ├── test_auth.py
    │   │   ├── test_middleware.py
    │   │   └── test_schemas.py
    │   ├── services/
    │   │   ├── __init__.py
    │   │   ├── test_ports.py
    │   │   └── test_audit_log_service.py
    │   └── repositories/
    │       ├── __init__.py
    │       ├── test_mongodb_lifecycle.py
    │       └── test_serialization.py
    └── integration/
        ├── __init__.py
        ├── api/
        │   ├── __init__.py
        │   ├── conftest.py
        │   ├── test_create_audit_log.py
        │   ├── test_list_audit_logs.py
        │   ├── test_list_by_checksum.py
        │   ├── test_idempotency_race.py
        │   ├── test_error_matrix.py
        │   └── test_openapi.py
        └── repositories/
            ├── __init__.py
            ├── conftest.py
            └── test_mongo_audit_log_repository.py
```

### 3.6 Configuración

| Variable | Tipo | Def. | Propósito |
|---|---|---|---|
| `APP_NAME` | `str` | `Audit Log Microservice` | título OpenAPI |
| `SERVICE_API_TOKEN` | `str` | **— (obligatoria)** | secreto Bearer compartido |
| `MONGO_URI` | `str` | `mongodb://localhost:27017` | conexión |
| `MONGO_DATABASE` | `str` | `pdf_extractext_audit` | base de datos |
| `MONGO_AUDIT_LOGS_COLLECTION` | `str` | `audit_logs` | colección |
| `MONGO_TIMEOUT_MS` | `int` | `5000` | timeout de operaciones Mongo |
| `MAX_BODY_BYTES` | `int` | `1048576` (1 MiB) | límite del body |
| `MAX_DETAILS_BYTES` | `int` | `65536` (64 KiB) | límite de `details` serializado |
| `DEFAULT_LIMIT` | `int` | `10` | paginación por defecto (coincide con el orquestador) |
| `MAX_LIMIT` | `int` | `100` | tope de `limit` |
| `MAX_SKIP` | `int` | `10000` | tope de `skip` |
| `RETENTION_DAYS` | `int` | `0` (desactivado) | TTL sobre `performed_at` |

`SERVICE_API_TOKEN` **no tiene default**: si falta o está vacía,
`Settings(...)` lanza `ValidationError` dentro del `lifespan` y **la app no
arranca**. Se prefiere fallar rápido a levantar un servicio cuya escritura está
protegida pero cuyo cliente no lo sabe (§2.5 H5).

El token **nunca** se loguea, ni en debug, ni en el mensaje de error. Códigos,
títulos y URIs de problema **no** son configurables: son parte del contrato
HTTP y viven en `app/errors.py`.

---

## 4. Capa 1 — Presentación

### 4.1 Endpoints

```
ABIERTO   GET    /health    → 200 {"status":"ok"}
ABIERTO   GET    /readyz    → 200 {"status":"ok","mongo":"ok"}  (hace ping) | 503
PROTEGIDO POST   /audit/logs                       Content-Type: application/json
PROTEGIDO GET    /audit/logs?skip=<int>&limit=<int>
PROTEGIDO GET    /audit/logs/checksum/{checksum}
```

`/health` y `/readyz` quedan **abiertos** para sondas de plataforma (k8s, load
balancers) que no pueden llevar credenciales. `/readyz` revela si Mongo está
alcanzable, que es aceptable en una red interna y es consistente con el
orquestador, que también expone `/healthz` y `/readyz` abiertos.

### 4.2 Autenticación

```
Header:  Authorization: Bearer <token>

Algoritmo:
  1. Extraer el esquema; si no es exactamente "Bearer" (case-insensitive)
     → Unauthorized
  2. Extraer el valor; si falta o está vacío → Unauthorized
  3. secrets.compare_digest(valor, SERVICE_API_TOKEN) — tiempo constante
  4. Falso en cualquiera de los pasos → Unauthorized
```

Respuesta de rechazo:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/problem+json
WWW-Authenticate: Bearer
```

```json
{
  "type": "/problems/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Missing or invalid bearer token.",
  "instance": "/audit/logs",
  "code": "UNAUTHORIZED"
}
```

Decisiones de seguridad:

- **`detail` es idéntico** si el token falta, está vacío, tiene otro esquema o
  es incorrecto. Distinguir los casos le daría a un atacante un oráculo para
  enumerar tokens. El log del servidor sí registra el motivo real, sin el valor.
- **`secrets.compare_digest`** evita que el tiempo de respuesta revele cuántos
  caracteres correctos lleva el token.
- **No hay `403`**: es un secreto compartido, no hay roles ni autorización
  granular. Un único `401` basta y no se puede malinterpretar.
- El esquema se compara case-insensitivamente (`bearer` es válido según
  RFC 7235/9110); el **valor** no: los tokens son sensibles a mayúsculas.

### 4.3 Orden de validación

De la más barata a la más costosa, para no gastar trabajo en peticiones que van
a fallar:

```
401 (auth) → 415 (content-type) → 413 (body size) → 400 (estructura) → [Capa 2]
```

La autenticación va **primero** a propósito: no se parsea ni se limita el body
de un llamador no autenticado. Es además la primera barrera contra abuso de
recursos.

### 4.4 Flujo de una petición — `POST /audit/logs`

1. `BearerAuthMiddleware` — valida el Bearer; `401` si falla.
2. `RequestIdMiddleware` — lee o genera `X-Request-ID`, lo devuelve y lo loguea.
3. `ContentTypeMiddleware` — POST exige `application/json`; si no, `415`.
4. `BodySizeLimitMiddleware` — `Content-Length > MAX_BODY_BYTES` → `413`.
5. Pydantic valida `AuditEventRequest`:
   `RequestValidationError` → **`400 VALIDATION_ERROR`** (§3.3 D1), nunca `422`.
6. `len(json.dumps(details)) > MAX_DETAILS_BYTES` → `413 PAYLOAD_TOO_LARGE`.
7. `AuditEventRequest` → `CreateAuditLogCommand`.
8. `audit_log_service.create(command)` → **Capa 2**.
9. `201` + `Location: /audit/logs/checksum/<escaped>` + documento completo.
   `200` si fue un replay (§6.4).
10. Cualquier `ServiceError` lo serializa `exception_handlers` como problem
    details.

### 4.5 Flujo de las lecturas

| Endpoint | Capa 1 | Capa 2 | Capa 3 | Resultado |
|---|---|---|---|---|
| `GET /audit/logs?skip&limit` | auth · `skip`/`limit` fuera de rango → `400` | `list_page(query)` | `find().sort(…).skip().limit()` | `200` + **array** (puede ser `[]`) |
| `GET /audit/logs/checksum/{c}` | auth | `list_by_checksum(query)` | `find({"checksum": c}).sort(…)` | `200` + **array** (puede ser `[]`) |

Un listado vacío **nunca** es un error: es `200 []`. No existe `404` para
"no hay logs de este checksum".

---

## 5. Capa 2 — Lógica de negocio

### 5.1 `AuditLogRepository` (puerto)

```python
class AuditLogRepository(Protocol):
    async def insert(self, document: NewAuditLog) -> StoredAuditLog: ...
    async def find_replay(
        self, *, action: str, entity_type: str, checksum: str, performed_at: datetime
    ) -> StoredAuditLog | None: ...
    async def list_page(self, query: ListQuery) -> list[StoredAuditLog]: ...
    async def list_by_checksum(self, query: ListQuery) -> list[StoredAuditLog]: ...
    async def ping(self) -> bool: ...
```

`Protocol` estructural en vez de `ABC`: la Capa 2 no importa nada de la Capa 3,
y el `FakeAuditLogRepository` de tests cumple el contrato sin herencia.

### 5.2 Reglas de negocio

| Regla | Comportamiento | HTTP |
|---|---|---|
| Todo evento se persiste con `received_at` del servidor | siempre | `201` |
| Un log **nunca** se modifica ni se borra | no existe el verbo | — |
| Un evento idéntico ya existente devuelve el **log original** | `idempotent_replay: true` | `200` |
| Los listados ordenan `performed_at desc, _id desc` | siempre | `200` |
| `limit` fuera de `[1, MAX_LIMIT]` se rechaza, **nunca** se recorta | rechazada | `400` |
| `skip` mayor que `MAX_SKIP` se rechaza, **nunca** se recorta | rechazada | `400` |
| Un listado sin resultados | `[]` | `200` |
| El `checksum` es un string **opaco** | sin validación de formato | — |

### 5.3 Idempotencia — la doble barrera

Éste es el punto más delicado del diseño. `audit_service.go:33` reintenta el
**mismo** `AuditEvent` hasta `maxEmitAttempts=2`. Si la primera inserción tuvo
éxito y la respuesta se perdió por timeout, el reintento insertaría un
duplicado. En un log de auditoría, un duplicado de infraestructura es una
defectuosidad del propio instrumento de auditoría.

**Barrera 1 — comprobación previa.** `find_replay(...)` sobre el índice único.
Si encuentra el evento, devuelve el `StoredAuditLog` existente con
`idempotent_replay=True`, y el router responde `200`.

**Barrera 2 — índice único atómico.** `insert_one(...)` con índice único sobre
`(action, entity_type, checksum, performed_at)`. Bajo concurrencia, dos
inserciones del mismo evento compiten; MongoDB resuelve una con
`DuplicateKeyError` (código `11000`), que se traduce a la misma respuesta de
replay.

```
┌─ Barrera 1 ────────────────────────────────────────────────┐
│ find_replay(action, entity_type, checksum, performed_at)     │
│      └─ SÍ ──► devolver StoredAuditLog existente            │
│                 (replay=True, sin escribir)                 │
│      └─ NO ──► Barrera 2                                     │
└─────────────────────────────────────────────────────────────┘
┌─ Barrera 2 ────────────────────────────────────────────────┐
│ insert_one(doc)                                            │
│      ├─ DuplicateKeyError (11000) ──► misma respuesta de   │
│      │                                 replay (cierra la    │
│      │                                 carrera)            │
│      ├─ DocumentTooLarge ──────────────► 413                │
│      ├─ ServerSelectionTimeout ───────► 503                │
│      └─ ok ────────────────────────────► replay=False → 201│
└─────────────────────────────────────────────────────────────┘
```

La exactitud **no depende** de la Barrera 1: si se eliminara, la Barrera 2
seguiría garantizando que existe exactamente un documento por evento. La
Barrera 1 existe para evitar el viaje de escritura y para que el caso normal
(retry tras timeout) no genere ningún error.

**Riesgo asumido y documentado**: dos eventos legítimos con la misma tupla
`(action, entity_type, checksum)` dentro del **mismo milisegundo** se funden en
uno solo. Requiere dos operaciones del mismo tipo sobre el mismo checksum en
menos de 1 ms. El volumen real del sistema (4 operaciones por checksum) hace
esto inexistente en la práctica.

### 5.4 Preservación del instante del emisor

`performed_at` lo envía el Orquestador y se guarda **tal cual llega**, parseado
a `datetime` con offset. El orden de la base de datos no lo decide AUDA: la
fuente de verdad es el reloj del emisor. `received_at` es el reloj de AUDA.

La diferencia entre ambos no es decorativa: es lo que permite responder
"¿cuándo ocurrió?" y "¿cuándo lo supimos?" por separado, que es exactamente lo
que hace falta para auditar una pérdida de eventos.

### 5.5 Respuesta a un `401` en el orquestador

Un `401` desde este servicio significa **error de configuración**, no un
problema de datos: el token está mal cableado, o el servicio está
desincronizado. El orquestador debería **fallar rápido y ruidosamente**
(`logger.Error`, sin reintento), no tratarlo como un error de negocio
transitorio.

El diseño de AUDA refuerza esa necesidad: como `SERVICE_API_TOKEN` es
obligatoria y la app **no arranca** sin ella, un desalineamiento de
configuración se manifiesta como un fallo de arranque del propio servicio, no
como una cadena de `401` en producción.

---

## 6. Capa 3 — Acceso a datos

### 6.1 Driver

`pymongo` con `AsyncMongoClient` (API asíncrona oficial de PyMongo ≥ 4.9).
`motor` está en modo mantenimiento, por lo que **no** se usa.

### 6.2 Esquema del documento

```json
{
  "_id":          ObjectId("6f1c9a2b3d4e5f60718293a4"),
  "action":       "pdf.extract",
  "entity_type":  "document",
  "checksum":     "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "details":      { "page_count": 12 },
  "performed_at": ISODate("2026-10-05T12:34:56.789Z"),
  "received_at":  ISODate("2026-10-05T12:34:57.041Z")
}
```

- `_id` es el `ObjectId` de Mongo, **no** el checksum. La diferencia con
  Persistencia es deliberada: allí el checksum **es** la identidad natural; aquí
  un mismo checksum genera **varios** eventos (`pdf.extract`, `text.create`,
  `text.update`, `text.delete`), así que el `ObjectId` es lo correcto y el
  checksum es un campo indexado.
- `performed_at` / `received_at` se guardan como BSON `Date` (ordenable,
  indexable) y se serializan a RFC 3339 UTC con `Z` y milisegundos.
- El mapeo documento ⇄ respuesta vive **sólo** en `serialization.py`: el
  servicio nunca ve un `ObjectId` ni un `datetime` crudo.
- `details` se guarda verbatim, incluyendo las claves con `.` o `$` que
  llegen del emisor. Riesgo asumido: MongoDB 5+ las tolera en inserciones, y
  `details` nunca se consulta con notación de punto en este servicio.
- `details` ausente en el request ⇒ `details: {}` en el documento. Nunca `null`.

### 6.3 Índices

| Índice | Tipo | Para qué |
|---|---|---|
| `_id_` | implícito | identidad del documento; no requiere acción |
| `(action, entity_type, checksum, performed_at)` | **único** | idempotencia (§5.3, Barrera 2) |
| `(checksum, performed_at desc, _id desc)` | compuesto | `GET /audit/logs/checksum/{c}` |
| `(performed_at desc, _id desc)` | compuesto | `GET /audit/logs` global |
| `performed_at` (expireAfterSeconds) | TTL | retención; **sólo** si `RETENTION_DAYS > 0` |

El `_id_` secundario dentro de los compuestos no es decorativo: sin él, dos
eventos con el mismo `performed_at` pueden ordenarse de forma no determinista
entre páginas sucesivas de `skip/limit`, y el mismo `skip/limit` devolvería
filas distintas en dos llamadas.

### 6.4 Traducción de errores de Mongo

| Excepción del driver | Significado | HTTP resultante |
|---|---|---|
| `DuplicateKeyError` (`11000`) | evento ya existente (Barrera 2) | **`200` con el log existente** |
| `DocumentTooLarge` | documento > 16 MiB | `413 PAYLOAD_TOO_LARGE` |
| `ServerSelectionTimeoutError` | Mongo inalcanzable | `503 AUDIT_STORAGE_ERROR` |
| `ConnectionFailure` | red caída | `503 AUDIT_STORAGE_ERROR` |
| `ExecutionTimeout` | operación lenta | `503 AUDIT_STORAGE_ERROR` |
| `PyMongoError` (resto) | inesperado | `503 AUDIT_STORAGE_ERROR` |

Este mapeo vive en la Capa 3 pero **se expresa con las excepciones de
`app/errors.py`**: la Capa 3 lanza errores de dominio, nunca HTTP. El acceso a
datos no conoce códigos de estado; la traducción ocurre en la Capa 1.

> `AUDIT_STORAGE_ERROR` se traduce a `503` y no a `500` porque es infraestructura
> caída: el Orquestador puede reintentar. Un `500` le quitaría esa opción.

### 6.5 Arranque

En el `lifespan` de FastAPI, en este orden:

1. Resolver `Settings`. Si `SERVICE_API_TOKEN` falta ⇒ `ValidationError` y **la
   app no arranca**.
2. Abrir el `AsyncMongoClient` con timeout.
3. Hacer `ping`.
4. Crear los índices de §6.3 (el TTL sólo si `RETENTION_DAYS > 0`).

Si Mongo **no** responde, la app **arranca igualmente** y es `/readyz` quien
reporta `503`: es preferible un proceso vivo que responde sondas a un proceso
muerto. La composición de la colección ocurre en el `lifespan`, no en
`create_app`, porque la colección sólo existe tras `connection.start()`.

Arranque:

```bash
uv sync
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8083
```

`--factory` es necesario porque la configuración se resuelve en el `lifespan`:
importar `app.main` no debe exigir entorno. El puerto `8083` es el que espera el
Orquestador por defecto (`AUDIT_LOG_BASE_URL`).

---

## 7. Gestión de errores — RFC 9457

### 7.1 Estructura del cuerpo

Media type: **`application/problem+json`** (RFC 9457 §3).

```json
{
  "type":     "/problems/validation_error",
  "title":    "Request validation error",
  "status":   400,
  "detail":   "Field 'performed_at' must be an RFC 3339 date-time with offset.",
  "instance": "/audit/logs",
  "code":     "VALIDATION_ERROR"
}
```

| Miembro | Regla aplicada |
|---|---|
| `type` | URI relativa `/problems/<snake_case>`, estable y documentada |
| `title` | Resumen corto y **genérico** de la clase de problema. Idéntico para todas las ocurrencias del mismo error |
| `status` | Código HTTP, repetido en el cuerpo para que sea autocontenido |
| `detail` | Explicación de **esta** ocurrencia. **Nunca** stack traces ni mensajes del driver |
| `instance` | Ruta (sin host, sin valores de query) que disparó el error |
| `code` | Extensión estable y legible por máquina (RFC 9457 §3.2) |

`title` nunca incluye valores variables: si lo hiciera, los clientes no podrían
comparar errores por `title`. La información variable va en `detail`.

### 7.2 Matriz de errores

| `code` | HTTP | `type` | `title` | Capa | Condición |
|---|---|---|---|---|---|
| `UNAUTHORIZED` | 401 | `/problems/unauthorized` | `Unauthorized` | 1 | Bearer ausente, mal formado o inválido (4 casos, mismo `detail`) |
| `VALIDATION_ERROR` | 400 | `/problems/validation_error` | `Request validation error` | 1 | JSON malformado, no-objeto, tipo erróneo, requerido ausente, clave desconocida, `performed_at` inválido, `skip`/`limit` fuera de rango |
| `PAYLOAD_TOO_LARGE` | 413 | `/problems/payload_too_large` | `Payload too large` | 1 / 3→2 | body > `MAX_BODY_BYTES`, `details` > `MAX_DETAILS_BYTES`, o documento > 16 MiB |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | `/problems/unsupported_media_type` | `Unsupported media type` | 1 | `Content-Type ≠ application/json` en POST |
| `NOT_FOUND` | 404 | `/problems/not_found` | `Resource not found` | 1 | ruta inexistente (incluye `/audit/logs/checksum/` sin valor) |
| `METHOD_NOT_ALLOWED` | 405 | `/problems/method_not_allowed` | `Method not allowed` | 1 | verbo no soportado, **incluido `PUT`/`DELETE` sobre `/audit/logs`** |
| `AUDIT_STORAGE_ERROR` | 503 | `/problems/audit_storage_error` | `Audit storage unavailable` | 3→2 | MongoDB inalcanzable o error de servidor |
| `INTERNAL_ERROR` | 500 | `/problems/internal_error` | `Internal server error` | 1 | excepción no prevista (catch-all) |

**Ocho filas.** `PAYLOAD_TOO_LARGE` y `AUDIT_STORAGE_ERROR` tienen dos orígenes
posibles porque pueden producirse en capas distintas; el cuerpo de la respuesta
es idéntico en ambos casos, así que el cliente no necesita saber dónde se
originó.

`PAYLOAD_TOO_LARGE` tiene **tres** disparadores porque hay **tres** límites
distintos y ninguno es redundante: entrada (1 MiB de body), campo (`details` de
64 KiB) y motor (16 MiB de documento BSON).

### 7.3 El `422` de FastAPI no aparece en la matriz

Porque no existe en el contrato de AUDA. `RequestValidationError` se traduce a
`400 VALIDATION_ERROR` en Capa 1 (§3.3 D1). Si alguna vez apareciera un `422`,
sería un defecto: §2.6 explica que hace entrar en panic al Orquestador.

### 7.4 El caso `200` de replay

**Disparador.** Un `POST /audit/logs` cuyo `(action, entity_type, checksum,
performed_at)` ya está en la colección — normalmente el reintento del
orquestador tras un timeout.

**Respuesta:**

```http
HTTP/1.1 200 OK
Content-Type: application/json
X-Idempotent-Replay: true
Location: /audit/logs/checksum/9f86d081…
```

```json
{
  "_id": "6f1c9a2b3d4e5f60718293a4",
  "action": "pdf.extract",
  "entity_type": "document",
  "checksum": "9f86d081…",
  "details": { "page_count": 12 },
  "performed_at": "2026-10-05T12:34:56.789Z",
  "received_at": "2026-10-05T12:34:57.041Z",
  "idempotent_replay": true
}
```

**Por qué `200` y no `409`:**

| Código | ¿Correcto? | Motivo |
|---|---|---|
| **`200 OK`** | **Sí** | El recurso solicitado ya existe, y el cliente **obtuvo exactamente lo que quería**: el log está persistido. El `Emit` del Go pasa `out=nil` y trata cualquier `2xx` como éxito, así que el reintento es **invisible** en el Orquestador: ni Warn ni error |
| `409 Conflict` | No | El cliente lo leería como fallo, el orquestador loguearía `Warn("audit emit failed")` por un evento que **sí** se guardó, y el pipeline mostraría una alarma falsa |
| `201 Created` | No | Sería mentir: no se creó nada. El `201` es lo que un cliente usa para saber que se insertó |
| `422` | No | El body es perfectamente válido |

El replay se distingue por dos vías redundantes y no ambiguas: el status `200`
frente al `201` por defecto de la ruta, y `X-Idempotent-Replay: true` más el
campo `idempotent_replay` en el body. `idempotent_replay` es un campo **de la
respuesta**, nunca del documento: no se persiste.

**Efecto en la base de datos: ninguno.**

---

## 8. Diagrama de flujo conceptual

```
╔════════════════════════╗
║  ORQUESTADOR (Go) :8080║  POST /audit/logs
║  goroutine fire-and-   ║  {action, entity_type, checksum, details, performed_at}
║  forget · 2 intentos   ║  → AUDIT_LOG_BASE_URL = http://localhost:8083
╚═══════════╤════════════╝
            │  Authorization: Bearer <AUDIT_LOG_API_TOKEN>
            │  Content-Type: application/json
            │  X-Request-ID: 3f2a91c8e7b4d05a
            ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ CAPA 1 · PRESENTACIÓN                   app/api/                                         ┃
┃                                                                                        ┃
┃  ① auth.py ── Bearer presente y correcto?                                              ┃
┃                  ├── NO ──────► 401 UNAUTHORIZED (WWW-Authenticate: Bearer)            ┃
┃                  ▼ SÍ                                                                     ┃
┃  ② middleware: X-Request-ID · Content-Type · límite de body                            ┃
┃                  ├── Content-Type ≠ json ───────► 415                                  ┃
┃                  ├── body > 1 MiB ──────────────► 413                                  ┃
┃                  ▼                                                                         ┃
┃  ③ AuditEventRequest (Pydantic v2, extra="forbid")                                      ┃
┃                  │   · action       str, min_length 1   (NO es enum: §3.3 D3)           ┃
┃                  │   · entity_type  str, min_length 1                                   ┃
┃                  │   · checksum     str, min_length 1  (opaco, sin formato)            ┃
┃                  │   · details      Any | ausente ⇒ {}                                  ┃
┃                  │   · performed_at AwareDatetime (RFC 3339 con offset)                  ┃
┃                  │   · clave desconocida ─────────────────► 400                        ┃
┃                  │   · violates tipo/ausencia ────────────► 400  (RequestValidationError)┃
┃                  ▼                                                                         ┃
┃  ④ details serializado > 64 KiB ─────────────────► 413                                   ┃
┃                    ▼                                                                      ┃
┃         CreateAuditLogCommand (dataclass frozen)                                         ┃
╞════════════════════════╪═══════════════════════════════════════════════════════════════════╡
            ▼            ╎  ◄── la Capa 1 NO consulta MongoDB ──►
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ CAPA 2 · LÓGICA DE NEGOCIO            app/services/audit_log_service.py                  ┃
┃                                                                                        ┃
┃         AuditLogService.create(command)                                                  ┃
┃                    │                                                                   ┃
┃                    ▼                                                                   ┃
┃     received_at = reloj de AUDA                                                         ┃
┃                    │                                                                   ┃
┃  ┌─ BARRERA 1 ── repo.find_replay(...) ────────────────────────────────────────────┐  ┃
┃  │        │                                                                      │  ┃
┃  │        ├── ENCONTRADO ──► StoredAuditLog(existente, replay=True) ──────► 200 │  ┃
┃  │        │                (sin escribir; respuesta idéntica a la que se        │  ┃
┃  │        │                 habría perdido el cliente en el timeout)            │  ┃
┃  │        ▼ NO                                                                   │  ┃
┃  └───────────────────────────────────────────────────────────────────────────────┘  ┃
┃                    ▼                                                                   ┃
┃  ┌─ BARRERA 2 ── repo.insert(doc) ◄──── MongoDB                                   ┐  ┃
┃  │        │                                       ▲                             │  ┃
┃  │        ├─ DuplicateKeyError (11000) ────────────┘ ──► replay=True ───────► 200 │  ┃
┃  │        │      (salto atómico del índice único; cierra la carrera)            │  ┃
┃  │        ├─ DocumentTooLarge ─────────────────────────────► 413                │  ┃
┃  │        ├─ ServerSelectionTimeout / ConnectionFailure ──► 503                │  ┃
┃  │        ▼                                                                      │  ┃
┃  └───────── StoredAuditLog (_id, replay=False) ──────────────────────────────────┘  ┃
╞════════════════════════╪═══════════════════════════════════════════════════════════════════╡
            ▼            ╎  ◄── ÚNICA capa que conoce pymongo ──►
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ CAPA 3 · ACCESO A DATOS              app/repositories/mongo_audit_log_repository.py    ┃
┃                                                                                      ┃
┃  insert_one({                                                                       ┃
┃     _id:          ObjectId()          ← la identidad NO es el checksum (§6.2)        ┃
┃     action:       command.action,                                                  ┃
┃     entity_type:  command.entity_type,                                             ┃
┃     checksum:     command.checksum,                                               ┃
┃     details:      command.details or {},   ← ausente ⇒ {}, nunca null              ┃
┃     performed_at: command.performed_at (BSON Date),   ← reloj del EMISOR           ┃
┃     received_at:  now         (BSON Date),               ← reloj de AUDA            ┃
┃  })                                                                                 ┃
┃  list_page(query)          → find().sort([("performed_at",-1),("_id",-1)])           ┃
┃                                  .skip(q.skip).limit(q.limit)                         ┃
┃  list_by_checksum(query)   → find({"checksum": q.checksum}).sort(idem)              ┃
┃                    ▼                                                                  ┃
┃      ┌──────────────────────────────┐                                                ┃
┃      │        MongoDB               │  audit_logs                                    ┃
┃      │  _id_                        │  (implícito)                                   ┃
┃      │  unique (action,entity_type, │  ← idempotencia: Barrera 2                     ┃
┃      │            checksum,        │                                                ┃
┃      │            performed_at)     │                                                ┃
┃      │  (checksum, performed_at     │  ← consulta por checksum                       ┃
┃      │        desc, _id desc)       │                                                ┃
┃      │  (performed_at desc,        │  ← listado global                             ┃
┃      │   _id desc)                  │                                                ┃
┃      │  TTL performed_at (opt.)     │  ← retención, si RETENTION_DAYS > 0            ┃
┃      └──────────────────────────────┘                                                ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
            │
            │  Los errores de cualquier capa ascienden hasta exception_handlers (Capa 1),
            │  que los serializa como application/problem+json
            ▼
      201 Created  (o 200 si fue replay)
      Location: /audit/logs/checksum/9f86d081…
      { "_id": "6f1c9a2b3d4e5f60718293a4", "action": …, "idempotent_replay": false }
```

### 8.1 Recorrido de las lecturas

```
GET /audit/logs?skip=5&limit=20
   → Bearer → 400 si skip<0 | skip>MAX_SKIP | limit<1 | limit>MAX_LIMIT
   → AuditLogService.list_page(ListQuery(skip=5, limit=20, checksum=None))
   → repo.list_page() → find().sort(…).skip(5).limit(20)
   → serialization: ObjectId → hex, BSON Date → RFC 3339 UTC "…Z"
   → 200 [ {...}, {...} ]        ← ARRAY, no {"logs": [...]}

GET /audit/logs/checksum/9f86d081…
   → Bearer → AuditLogService.list_by_checksum(ListQuery(checksum="9f86d081…"))
   → repo.list_by_checksum() → find({"checksum": …}).sort(…)   ← sin limit: D12
   → 200 [ {...}, {...} ]        ← [] si no hay ninguno: NO es 404
```

---

## 9. Verificación de compatibilidad con el orquestador

Los tests de `internal/clients/auditlog/client_test.go` fijan el contrato desde
el lado del consumidor. Esta tabla es la checklist de contrato; **cada fila debe
tener un test en AUDA**.

| Comportamiento exigido por el cliente Go | Origen | Cubierto por |
|---|---|---|
| `POST /audit/logs` con los 5 campos, `application/json` → `2xx` | `client_test.go:31` | T10 |
| `POST` → `201` en el caso normal | `client_test.go:67` | T10 |
| `POST` de un evento repetido → `2xx`, sin documento duplicado | `maxEmitAttempts=2` | T11 |
| `POST` sin token → `401` + problem parseable | nuevo (cambio 1) | T5, T15 |
| **`GET /audit/logs` devuelve un ARRAY de primer nivel** | `client.go:40` | T12 |
| **`GET /audit/logs?skip&limit` propaga ambos valores** | `client_test.go:118-123` | T12 |
| `GET` decodifica los 7 campos de `models.AuditLog` | `client_test.go:128-149` | T12 |
| **`_id` es string hex de 24 chars** | `models.AuditLog.ID string` | T12 |
| `GET /audit/logs/checksum/{c}` con path exacto | `client_test.go:156` | T13 |
| `GET` por checksum sin resultados → `200` + `[]` | `client_test.go:170` | T13 |
| Todo `status >= 300` devuelve body con los 4 campos mínimos | `httpclient/client.go:39` | T15 |
| Ningún `422` en ninguna ruta | §2.6 | T15 |
| `performed_at` / `received_at` parseables por `time.Time` | `models.AuditLog` | T12 |
| `details` ausente ⇒ el Go no observa `nil` raro | `omitempty` | T10 |

---

## 10. Fuera de alcance

- Autenticación de usuario final, refresh tokens, rotación de secretos.
- `403` / autorización granular por rol o por recurso.
- Paginación del listado **por checksum** (el cliente Go no la envía, §2.8).
- Filtros adicionales: por `action`, `entity_type` o rango de fechas. El
  orquestador no los envía; añadirlos sería diseño especulativo.
- Modificación o borrado de logs (`PUT`, `DELETE`, soft-delete).
- Reindexado, migraciones de esquema, versionado de documentos.
- Retries, circuit breaker o backoff (responsabilidad del cliente).
- Réplica, sharding, tuning de la colección.
- Pruebas de carga o de rendimiento sostenido.
- Cola de mensajes o outbox transaccional (§12 D3).
- Validación de formato del `checksum` y sanitización de claves de `details`.

---

## 11. Riesgos

| Riesgo | Impacto | Mitigación | Tarea |
|---|---|---|---|
| **Respuesta de lectura mal envuelta ⇒ `502` en todo el pipeline** | **Muy alto** | ARRAY de primer nivel como invariante de contrato; test explícito + checklist §9 | T12 |
| **`422` de FastAPI ⇒ `WriteHeader(0)` hace entrar en panic al Orquestador** | **Muy alto** | Handler de `RequestValidationError` → `400`; test de matriz que prohíbe `422` | T3, T15 |
| **`_id` renombrado a `id` por Pydantic ⇒ `ID == ""` en Go, sin error visible** | **Muy alto** | `serialization_alias` + test que falla si se quita | T3, T10 |
| **Go no manda el token ⇒ la auditoría deja de crecer en silencio** | **Alto** | `SERVICE_API_TOKEN` sin default: la app **no arranca**; §2.7 con los 6 cambios exactos | T4, T5 |
| Condición de carrera entre `find_replay()` e `insert()` | Alto | Doble barrera (§5.3): el índice único cierra la carrera; T11 lo verifica por mutación | T8, T9, T11 |
| `_id` ausente en los compuestos ⇒ paginación no determinista | Medio | `_id desc` como criterio de desempate en ambos índices | T6 |
| Evento legítimo con clave nueva ⇒ `400` y evento perdido | Medio | `details` como válvula de escape; `action` no es enum | T10 |
| Dos eventos legítimos en el mismo milisegundo se funden | Bajo | Requisito: 2 operaciones del mismo tipo sobre el mismo checksum en <1 ms. Volumen real: ~4 eventos por checksum | — |
| `details` enorme ⇒ documento cerca del límite BSON | Medio | `MAX_DETAILS_BYTES` (64 KiB) + `DocumentTooLarge → 413` | T4, T8, T10 |
| Listado por checksum sin paginar ⇒ respuesta sin cota | Medio | Volumen real ~4 filas; mejorarlo requiere un cambio en Go (§2.7, opcional) | T13 |
| Claves de `details` con `.` o `$` | Bajo | Riesgo asumido; `details` nunca se consulta con notación de punto | — |
| Mongo caído al arrancar | Bajo | La app **arranca** y `/readyz` reporta `503`; proceso vivo > proceso muerto | T6 |
| OpenAPI sin el esquema de seguridad `Bearer` | Bajo | `HTTPBearer` de FastAPI publica el esquema automáticamente | T16 |
| Contrato del Orquestador cambia después | Medio | Checklist §9 + `client_test.go` como primera línea de defensa | T15, T16 |

---

## 12. Decisiones tomadas

| # | Decisión | Elegida | Consecuencia |
|---|---|---|---|
| **D1** | Base de datos | **MongoDB** vía `AsyncMongoClient` | Consistencia con Persistencia; `_id` hex encaja con `models.AuditLog.ID string` |
| **D2** | Identidad del documento | **`ObjectId`**, no el checksum | Un checksum genera varios eventos; el checksum es campo indexado |
| **D3** | Cola de mensajes | **No. REST directo** | El cliente Go ya existe y está probado; una cola obligaría a reescribirlo y desplazaría la pérdida al broker |
| **D4** | Modelo de contrato | **Pydantic v2** | OpenAPI automático; obliga a D5, D6 y D7 |
| **D5** | `422` de FastAPI | **Convertido a `400 VALIDATION_ERROR`** | Obligatorio: el `422` hace entrar en panic al Orquestador (§2.6) |
| **D6** | Campo `_id` | **`alias` + `serialization_alias`** | Imprescindible: sin él el Go lee `ID == ""` sin error |
| **D7** | `extra` del request | **`"forbid"`** | Una clave nueva da `400` visible en vez de un `201` que descarta el dato en silencio |
| **D8** | `action` | **`str`, no `enum`** | Agregar una operación al Orquestador no exige desplegar AUDA |
| **D9** | Durabilidad futura | **Fuera de alcance** | Si algún día hace falta, el camino es un outbox transaccional en el Orquestador, no una cola |
| **D10** | Duplicados por reintento | **Índice único + `200` con el log existente** | El reintento del Orquestador es invisible; no hay alarma falsa |
| **D11** | Verbos mutables | **No existen** | `405` explícito; append-only real |
| **D12** | Listado por checksum inexistente | **`200` + `[]`** | Semántica de colección; evita un `502` espurio en el proxy |
| **D13** | Ubicación del checksum | **Path param** | El cliente Go ya usa `PathEscape`; un checksum real es hex y nunca contiene `/` |
| **D14** | `received_at` | **Sí, lo añade el servidor** | Distingue "cuándo ocurrió" de "cuándo lo supimos"; Go lo ignora |
| **D15** | Autenticación | **Sí — Bearer token compartido** | `SERVICE_API_TOKEN` obligatoria; fail-fast de arranque |
| **D16** | `skip`/`limit` fuera de rango | **`400`, nunca recorte silencioso** | El cliente sabe que su página está incompleta |
| **D17** | Retención | **TTL desactivado por defecto** | Una auditoría no se borra sola sin que alguien lo decida |

---

## 13. Convenciones

- **Prosa de `SPEC.md` y `tasks/*.md`: español.**
- **Código fuente: inglés.** Nombres de módulos, clases, funciones, variables y
  literales de log van en inglés, como el resto del ecosistema.
- **Comentarios y docstrings: español.** Todo `#` y toda cadena de documentación
  que explique *qué hace* o *cómo funciona* algo se escribe en español, con
  estilo Google en toda función y clase pública. Es la convención pedida
  explícitamente para este repositorio; difiere de los dos hermanos, donde los
  docstrings van en inglés.
- Lo que **no** se traduce: los valores que cruzan el contrato HTTP (`code`,
  `title`, `type`, `default_detail`), porque los lee el cliente de Go, y los
  identificadores del dominio (`UnauthorizedError`, `action`, `entity_type`),
  porque son código.
- Type hints en todas las firmas.
- `ruff`, `line-length = 88`, select `["E","F","W","I","B","UP","SIM","C4"]`.
- Tests con `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`); cobertura
  `--cov=app --cov-fail-under=85`.
- Gestor de paquetes: `uv` (`pyproject.toml` + `uv.lock` versionado).
- Comandos: `uv sync` · `uv run pytest` · `uv run pytest --cov-fail-under=85` ·
  `uv run ruff check .` · `uv run ruff format .`

---

## 14. Handoff — qué necesita el Orquestador

Resumen ejecutivo de §2.7, en el orden en que conviene hacerlo:

1. `AUDIT_LOG_API_TOKEN` en `config.go`, **sin default** (configuración).
2. `httpclient.New(baseURL, timeout, token)` + `Authorization` en todas las
   requests (`httpclient/client.go`).
3. `auditlog.NewClient(...)` y `main.go:35` propagan el token.
4. `audit_service.go`: un `401` es error de configuración ⇒ `logger.Error`, sin
   reintento.
5. Actualizar los 5 tests de `client_test.go` con el header y añadir el caso
   `401` sin token.
6. *(Opcional, futuro)* `ListByChecksum(skip, limit)` para acotar el listado por
   checksum (§2.8).

> **AUDA no puede desplegarse antes que los puntos 1-4**: `SERVICE_API_TOKEN` es
> obligatoria sin default, así que el servicio no arranca sin ella. El
> desalineamiento se manifiesta como un fallo de arranque, no como una auditoría
> detenida en silencio.