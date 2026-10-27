# App Backend — Smart Inventory Platform

[![codecov](https://codecov.io/gh/Smart-Inventory-App/App_backend/branch/main/graph/badge.svg?token=LQMB0H4SY1)](https://codecov.io/gh/Smart-Inventory-App/App_backend)

**Backend principal** de Smart Inventory. Gestiona productos del usuario y valida JWT emitidos por el servicio `Auth`.

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
| GET | `/products/` | Listar productos del usuario (con filtros, orden y paginación) |
| POST | `/products/` | Crear producto |
| GET | `/products/{id}` | Obtener un producto |
| PUT | `/products/{id}` | Actualizar producto |
| DELETE | `/products/{id}` | Eliminar producto |
| GET | `/products/changes` | Últimos cambios de stock (entradas, salidas y modificaciones), del más nuevo al más viejo |
| GET | `/products/stock-total` | Suma del stock y cantidad de productos que cumplen los mismos filtros que `GET /products/` |
| GET | `/products/match?q=` | Productos que se parecen a un texto leído de una etiqueta, comparado con el nombre, la marca y la descripción |

**Filtros, orden y páginas en `GET /products/`:**

| Query param | Descripción |
|-------------|-------------|
| `search` | Busca por nombre o marca (ilike) |
| `categoria` | Filtra por categoría exacta (ilike) |
| `ubicacion` | Filtra por ubicación (ilike) |
| `sort_by` | `nombre`, `stock`, `vencimiento` o `categoria`. Sin este parámetro salen los más nuevos primero |
| `sort_dir` | `asc` (default) o `desc` |
| `limit` | Cuántos productos traer (1 a 200). **Sin `limit` trae todos** |
| `offset` | Cuántos saltear, para pedir las páginas siguientes (default 0) |

Cómo se ordena:

- **Por nombre el orden es alfabético de verdad**: no distingue mayúsculas ni tildes y la «ñ» va después de la «n» (`utils/sorting.py`). La base de datos pondría todas las mayúsculas antes que las minúsculas.
- **Por vencimiento no entran los productos sin fecha**, ni creciente ni decreciente.
- **El id desempata siempre**, así dos páginas seguidas nunca repiten ni se saltean productos que tienen el mismo valor en el campo ordenado.

La app muestra el inventario de a páginas: los primeros 20 productos con los filtros elegidos y, con «Cargar más», 10 más cada vez (`limit=20&offset=0`, después `limit=10&offset=20`, y así).

**Búsqueda por texto escaneado (`/products/match`).** A diferencia de `/products/suggest` (que busca dentro del nombre), compara el texto leído con el nombre, la marca y la descripción de cada producto del usuario, tolera abreviaturas y palabras de más, y devuelve hasta 10 productos de mejor a peor. El escaneo de etiquetas usa el mismo criterio para armar las coincidencias del borrador.

**Stock total (`/products/stock-total`).** Acepta los mismos filtros que el listado (`search` por nombre o marca, `categoria` y `ubicacion`) y devuelve `{ "stock_total": N, "products": M }` con la suma del stock y la cantidad de **todos** los productos que coinciden (no solo los de una página). La app lo muestra arriba del buscador del Inventario y lo vuelve a pedir cada vez que cambia la lista.

**Últimos cambios (`/products/changes`).** Parámetros `limit` (1 a 50, default 5) y `offset`. Cada cambio trae el stock antes y después, que se reconstruye hacia atrás desde el stock actual con los movimientos del producto; las correcciones no aparecen, queda el movimiento corregido. Un producto con fecha de carga aporta además su entrada inicial.

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
App → POST /products/scan ──► ocr_service ──► image_storage_service (tpp/ocr-temp)
                                    │                    ▲
                                    │  worker            │ DELETE al terminar
                                    ▼                    │
                          tesseract · paddleocr ×2
App → GET  /products/scan/{id} ─► { status, result: { draft } }
App → POST /products/            (el alta de siempre, con el borrador corregido)
```

Tres cosas que definen la integración:

- **Este backend habla con un solo servicio del módulo**: `ocr_service`, que es el coordinador. Los tres motores viven detrás de él y sus URLs no se conocen acá, así que cambiar la estrategia de reconocimiento no toca este repositorio.
- **La foto no se guarda acá ni en la base.** El coordinador la sube a `image_storage_service` en su carpeta temporal (`tpp/ocr-temp`, TTL 15 min, sin recomprimir de más para no degradar el reconocimiento) y la descarta cuando termina de procesarla. La foto que alguien saca para escanear un producto no tiene por qué sobrevivir al escaneo; lo único que queda es la lectura.
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

### Alertas (requieren `Authorization: Bearer <token>`)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/alerts/` | Todas las alertas del usuario |
| GET | `/alerts/critical_alerts` | Solo las críticas |
| GET | `/alerts/stock_alerts` | Solo las de stock bajo (`stock_low_coverage`) |
| GET | `/alerts/expiry_alerts` | Las de vencimiento y de ritmo lento (`expiry`, `slow_pace`) |
| GET | `/alerts/summary` | Cantidad de alertas por nivel: `critical`, `warning`, `info` |

Cada alerta trae, además de su tipo, nivel y los datos del motivo (`days_until_stockout`, `units_wasted`), lo que la app necesita para mostrarla sin pedir el producto aparte: `product_name`, `image_url`, `product_stock` (un stock de `0` se devuelve como `0`, no como vacío), `product_expiry`, `product_category` y `product_brand`. La app los usa en la ventana «Detalle de Alerta» que se abre al tocar una entrada.

### Perfil (requieren `Authorization: Bearer <token>`)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/profile/` | Perfil del usuario (se crea con los valores por defecto si no existe) |
| PUT | `/profile/` | Actualizar datos personales, tipo de cuenta y configuración de alertas |
| GET | `/profile/username-available?username=` | Si el nombre de usuario se puede usar: `{"available": true/false}` (el nombre de la propia cuenta cuenta como disponible) |

**Nombre de usuario único.** Como máximo una cuenta puede tener un nombre de usuario, sin distinguir mayúsculas ni espacios en los bordes. `PUT /profile/` responde `409` con `profile.username_taken` si otra cuenta ya lo tiene. La regla solo mira los **cambios**: una cuenta que ya tenía un nombre repetido (de antes de esta regla) puede seguir guardando su perfil sin tocarlo. No hay índice único en la base justamente para no fallar con esos duplicados, y no requiere migración.

Límites que valida `PUT /profile/` (responde `422` si no se cumplen; son los mismos que aplica la app):

| Campo | Límite |
|-------|--------|
| `firstName`, `lastName`, `username` | hasta 20 caracteres |
| `coverageDaysThreshold` (días de stock) | entero de 2 a 90 |
| `expiryDaysThreshold` (días por vencer) | entero de 2 a 90 |
| `alertCheckHour` | entero de 0 a 23, **en hora UTC** |

`alertCheckHour` es siempre una hora UTC: el chequeo diario de alertas corre cada hora en punto (UTC) y avisa a los usuarios cuya `alertCheckHour` coincide con la hora UTC actual. La app muestra y pide la hora de Argentina (UTC-3) y hace la conversión: **05:00 de Argentina se guarda como 8**, 08:00 de Argentina como 11.

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
│   │   ├── products.py     # CRUD de productos, cambios de stock y stock total por producto
│   │   ├── alerts.py       # Alertas del usuario (con los datos del producto)
│   │   └── health.py       # Health check
│   ├── core/
│   │   ├── config.py       # Settings (pydantic-settings)
│   │   ├── database.py     # Engine + sesión SQLAlchemy
│   │   └── security.py     # Validación JWT local
│   ├── models/
│   │   └── product.py      # Modelo Product (user_id, nombre, stock, ...)
│   ├── schemas/
│   │   ├── product.py      # ProductCreate / ProductUpdate / ProductResponse / grupos y cambios
│   │   └── alert.py        # AlertResponse
│   └── utils/
│       └── sorting.py      # Orden alfabético sin mayúsculas ni tildes
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

**450 tests, 99 % de cobertura.** No necesitan PostgreSQL (se usa SQLite en memoria de archivo) ni ningún otro servicio: el módulo de OCR se dobla en tres niveles según lo que cada test pregunta —la traducción de una lectura a un borrador con diccionarios, el cliente HTTP contra un transporte de mentira de `httpx` (que sí ejercita el multipart, el reenvío del token y la traducción de errores) y los endpoints con el cliente doblado—.

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
