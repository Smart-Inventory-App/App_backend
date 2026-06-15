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
