# App Backend — Smart Inventory

Test Coverage:

[![codecov](https://codecov.io/github/Smart-Inventory-App/App_backend/graph/badge.svg?token=LQMB0H4SY1)](https://codecov.io/github/Smart-Inventory-App/App_backend)

Backend principal de Smart Inventory. Gestiona productos del usuario y valida JWT emitidos por el servicio `Auth`.

---

## Stack

- Python 3.10+ + FastAPI
- PostgreSQL (SQLAlchemy sync + Alembic)
- JWT HS256 (python-jose) — valida tokens del servicio Auth

---

## Endpoints

### Productos (requieren `Authorization: Bearer <token>`)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/products/` | Listar productos del usuario |
| POST | `/products/` | Crear producto |
| GET | `/products/{id}` | Obtener un producto |
| PUT | `/products/{id}` | Actualizar producto |
| DELETE | `/products/{id}` | Eliminar producto |

**Filtros en `GET /products/`:**

| Query param | Descripción |
|-------------|-------------|
| `search` | Busca por nombre o marca (ilike) |
| `categoria` | Filtra por categoría exacta (ilike) |
| `ubicacion` | Filtra por ubicación (ilike) |

### Schema de producto

| Campo | Tipo | Requerido | Restricciones |
|-------|------|-----------|---------------|
| `nombre` | string | sí | max 20 chars |
| `categoria` | string | sí | max 20 chars |
| `stock` | int | sí | > 0 |
| `marca` | string | no | — |
| `vencimiento` | date | no | formato `YYYY-MM-DD` |
| `descripcion` | string | no | max 400 chars |
| `imagen_url` | string | no | URL desde image_storage_service |
| `ubicacion` | string | no | — |

### Escaneo por OCR (Requiere `Authorization: Bearer <token>`)

Alta de un producto **a partir de una foto**, en vez de a mano.

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/products/scan` | Manda la foto. Código de barras → `200` resuelto; el resto → `202 { job_id }` |
| GET | `/products/scan/{job_id}` | Estado del escaneo y, al terminar, el borrador |

Los dos devuelven **la misma forma** (`ScanState`) y la regla para el cliente es una sola: **si `status` es `done`, el resultado ya está**.

Un código de barras la cumple en la primera llamada, porque no pasa por un motor OCR —lo decodifica el coordinador— y encolarlo sería pagar la subida a Cloudinary, la cola y el polling por un trabajo de 0,2 s. Medido: **0,07 s** por esta vía contra 2,8 s por la otra; escanear una entrega de 50 productos pasa de dos minutos a cuatro segundos, y de 50 imágenes almacenadas a cero.

**Campos de `POST /products/scan`** (`multipart/form-data`):

| Campo | Tipo | Requerido | Valores |
|-------|------|-----------|---------|
| `file` | archivo | sí | JPEG, PNG o WebP · máx. 10 MB |
| `doc_type` | string | no (default `product_label`) | `product_label`, `expiry_date`, `receipt`, `barcode` |

#### Cómo Funciona

```
App → POST /products/scan ──► ocr_service ──► image_storage_service (bazaar/ocr-temp)
                                    │                    ▲
                                    │  worker            │ DELETE al terminar
                                    ▼                    │
                          tesseract · paddleocr ×2
App → GET  /products/scan/{id} ─► { status, result: { draft } }
App → POST /products/            (el alta de siempre, con el borrador corregido)
```

Tres cosas que definen la integración:

- **Este backend habla con un solo servicio del módulo**: `ocr_service`, que es el coordinador. Los tres motores viven detrás de él y sus URLs no se conocen acá, así que cambiar la estrategia de reconocimiento no toca este repositorio.
- **La foto no se guarda acá ni en la base.** El coordinador la sube a `image_storage_service` en su carpeta temporal (`bazaar/ocr-temp`, TTL 15 min, sin recomprimir de más para no degradar el reconocimiento) y la descarta cuando termina de procesarla. La foto que alguien saca para escanear un producto no tiene por qué sobrevivir al escaneo; lo único que queda es la lectura.
- **Es asincrónico** porque el reconocimiento tarda: sobre una foto de envase el coordinador prueba varias orientaciones y filtros, y puede llegar a pedirle una inferencia al motor pesado por cada una. Bloquear el formulario de alta todo ese tiempo es peor que devolver un identificador y avisar cuando está.

#### Uso del Draft

`result.draft` trae **los campos de `ProductCreate` que el OCR pudo leer**, con la confianza de cada uno. La app lo muestra en el formulario y la persona confirma o corrige; el alta sigue siendo `POST /products/`, con su validación, su fusión con un producto existente y su registro de actividad.

| `doc_type` | Qué rellena |
|---|---|
| `product_label` | `nombre`, `marca`, `descripcion` |
| `expiry_date` | `vencimiento` |
| `barcode` | `codigo_barras`, `pais_registro` (informativos: la tabla de productos no los guarda) |
| `receipt` | `items[]` — un borrador por renglón, con `nombre` y `stock` — más `comprobante` (`comercio`, `fecha_compra`, `total`) |

**El borrador no inventa.** `categoria` y `stock` no salen de una etiqueta, así que llegan vacíos: rellenarlos con algo plausible sería peor que dejarlos vacíos, porque el usuario confirma el formulario sin releerlo y termina cargando un dato que nadie leyó de la foto. Si un texto no entra en el máximo del formulario (`nombre`, 20 caracteres) se recorta por palabra y se avisa en `advertencias`.

`needs_review` viene en `true` cuando algún campo clave no llega al 0,85 que fija la propuesta. No bloquea el alta: avisa que conviene mirar antes de confirmar.

#### Polling y Concurrencia

Mientras el escaneo espera, `GET /products/scan/{job_id}` devuelve `queue_position` y `estimated_wait_seconds`: la app debería mostrarlos («3º de 7, ~2 min») en vez de un spinner. A dos documentos pesados por minuto, una fila de diez son cuatro minutos y medio, y un spinner mudo ahí se lee como una app rota.

El escaneo puede volver **`429`** por dos motivos, los dos con `Retry-After`: el usuario agotó su cupo del minuto (60 códigos de barras, 10 etiquetas o vencimientos, 4 comprobantes) o la cola del módulo ya es más larga que la paciencia. La app debería reintentar recién cuando ese header lo indique.

Consultar cada **medio segundo** alcanza: un código de barras o un sello se resuelven en 2-3 s, un ticket puede llevar decenas. El escaneo **sólo lo ve quien lo creó** — el coordinador guarda el `sub` que lo encoló y responde `404` a cualquier otro, así que un `job_id` filtrado no expone el ticket de nadie.

Del lado de este backend, las llamadas al coordinador van por un **pool de conexiones compartido** en vez de abrir una por request como el resto del backend. Es deliberado: con el polling, un solo producto son decenas de conexiones nuevas, y con varios clientes a la vez son cientos por minuto.

Varios clientes escaneando simultáneamente no se bloquean entre sí: el worker del OCR procesa varios jobs a la vez, así que un código de barras enviado detrás de tres tickets se resuelve igual en segundos. El detalle está en el README de `ocr_service`.

### Health

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/health` | Liveness check |

---

## Autenticación

El backend valida el JWT con el mismo `JWT_SECRET` que usa el servicio `Auth`. No hay llamadas externas por request — la validación es local.

Del payload del token extrae:
- `sub` → `user_id` (aísla los productos por usuario)
- `email` → disponible si se necesita en endpoints futuros

---

## Configuración

Crear `.env` a partir de `.env.example`:

```env
# Base de datos
DATABASE_URL=postgresql://user:password@db:5432/tpp_db

# JWT (mismo secret que el servicio Auth)
JWT_SECRET=change-this-secret-in-production
JWT_ALGORITHM=HS256

# Módulo de OCR — el coordinador. Vacío = escaneo por foto deshabilitado y los
# endpoints responden 503; el alta manual de productos sigue funcionando igual.
# Dentro de la red de Docker el host es `http://tpp_ocr:8003`.
OCR_SERVICE_URL=http://localhost:8003
OCR_TIMEOUT_SECONDS=30

# API
DEBUG=True
SECRET_KEY=dev-secret-key-change-in-production
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8081,http://localhost:19000

# Servidor
HOST=0.0.0.0
PORT=8000
```

---

## Setup local

### 1. Instalar dependencias

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Levantar PostgreSQL

```bash
docker-compose up -d db
```

PostgreSQL queda disponible en `localhost:5432`.

### 3. Aplicar migraciones

```bash
alembic upgrade head
```

### 4. Levantar el backend

```bash
python main.py
```

Swagger disponible en `http://localhost:8000/docs`.

---

## Docker

```bash
# Build y run completo (Postgres + backend)
docker-compose up -d
```

El backend espera a que Postgres esté saludable antes de iniciar (`depends_on: condition: service_healthy`).

---

## Migraciones

```bash
# Aplicar todas las migraciones pendientes
alembic upgrade head

# Ver estado actual
alembic current

# Crear nueva migración tras cambiar un modelo
alembic revision --autogenerate -m "descripción"

# Acceso directo a la DB
docker-compose exec db psql -U user -d tpp_db
```

---

## Estructura

```
App_backend/
├── app/
│   ├── api/
│   │   ├── products.py     # CRUD de productos
│   │   └── health.py       # Health check
│   ├── core/
│   │   ├── config.py       # Settings (pydantic-settings)
│   │   ├── database.py     # Engine + sesión SQLAlchemy
│   │   └── security.py     # Validación JWT local
│   ├── models/
│   │   └── product.py      # Modelo Product (user_id, nombre, stock, ...)
│   └── schemas/
│       └── product.py      # ProductCreate / ProductUpdate / ProductResponse
├── alembic/                # Migraciones
├── tests/
├── docker-compose.yml
├── main.py                 # Punto de entrada — uvicorn
└── .env.example
```

---

## Tests

```bash
pytest tests/ -v
```

**77 tests.** No necesitan PostgreSQL (se usa SQLite en memoria de archivo) ni ningún otro servicio: el módulo de OCR se dobla en tres niveles según lo que cada test pregunta —la traducción de una lectura a un borrador con diccionarios, el cliente HTTP contra un transporte de mentira de `httpx` (que sí ejercita el multipart, el reenvío del token y la traducción de errores) y los endpoints con el cliente doblado—.

---

## Troubleshooting

**`connection refused` en puerto 5432**
```bash
docker-compose up -d db
# Esperar ~10s y reintentar
```

**`401 Unauthorized` en todos los endpoints**
- El JWT expiró (30 min). Hacer logout/login en la app para obtener uno nuevo.
- Verificar que `JWT_SECRET` sea el mismo que usa el servicio `Auth`.

**`ModuleNotFoundError`**
```bash
source venv/bin/activate
pip install -r requirements.txt
```
