# App Backend — Smart Inventory

Test Coverage:

[![codecov](https://codecov.io/github/Smart-Inventory-App/App_backend/graph/badge.svg?token=LQMB0H4SY1)](https://codecov.io/github/Smart-Inventory-App/App_backend)

FastAPI + Keycloak backend para Smart Inventory.

---

## Requisitos

- **Docker & Docker Compose**
- **Python 3.10+**
- **Git**

---

## Setup local

### 1. Crear el `.env`

```bash
cp .env.example .env
```

Completar los valores (client secret de Keycloak, etc.).

### 2. Crear el virtualenv e instalar dependencias

```bash
python -m venv venv
source venv/bin/activate       # Linux / WSL / macOS
# venv\Scripts\activate        # Windows CMD/PowerShell
pip install -r requirements.txt
```

### 3. Levantar Postgres y Keycloak

```bash
docker-compose up -d db keycloak
```

Esto levanta:
- `tpp_db` — PostgreSQL en el puerto `5432`
- `tpp_keycloak` — Keycloak en http://localhost:8080 (admin / admin)

Esperar ~15 segundos a que Keycloak termine de iniciar.

### 4. Crear las tablas en la DB

```bash
source venv/bin/activate
alembic upgrade head
```

> Si el contenedor `app` no está corriendo (es lo normal en dev local), correr Alembic directamente con el venv activado — lee el `DATABASE_URL` del `.env`.

### 5. Levantar el backend

```bash
python main.py
```

El backend corre en: http://localhost:8000  
Swagger: http://localhost:8000/docs

---

## Levantar todo para desarrollo local

En **3 terminales WSL** (con el venv activado):

| Terminal | Comando | Qué hace |
|----------|---------|----------|
| 1 | `docker-compose up` | Postgres + Keycloak |
| 2 | `alembic upgrade head` (solo si hay migraciones nuevas) | Aplica la migración |
| 3 | `python main.py` | Backend FastAPI |

> Si el backend da 401, el token de Keycloak expiró (~5 min). Hacer logout/login en la app.

### Agregar una columna manualmente (sin contenedor `app` corriendo)

```bash
# Con el venv activado:
alembic upgrade head

# O directamente por psql si Alembic da problemas:
docker-compose exec db psql -U user -d tpp_db -c "ALTER TABLE products ADD COLUMN nueva_col VARCHAR;"
```

---

## Estructura del proyecto

```
App_backend/
├── app/
│   ├── api/
│   │   ├── auth.py          # Autenticación + perfil de usuario
│   │   ├── products.py      # CRUD de productos (Epic 2)
│   │   ├── health.py
│   │   └── transactions.py
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── database.py
│   │   └── security.py      # Validación de token via Keycloak introspection
│   ├── models/
│   │   ├── user.py
│   │   └── product.py       # Modelo de producto (Epic 2)
│   ├── schemas/
│   │   ├── user.py
│   │   └── product.py       # Schemas de producto (Epic 2)
│   └── services/
│       ├── keycloak_service.py
│       └── user_service.py
├── alembic/
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── a1b2c3d4e5f6_add_password_recovery_codes.py
│       ├── b1c2d3e4f5a6_add_products_table.py
│       └── c2d3e4f5a6b7_add_ubicacion_to_products.py
├── docker-compose.yml
├── main.py                  # Punto de entrada — uvicorn
├── requirements.txt
├── .env                     # No se commitea
└── .env.example
```

---

## Endpoints

### Autenticación

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/auth/login` | Login → devuelve JWT de Keycloak |
| POST | `/auth/register` | Crear usuario |
| GET | `/auth/me` | Info básica del usuario autenticado |
| GET | `/auth/profile` | Perfil completo (nombre, apellido, email) |
| PUT | `/auth/profile` | Actualizar nombre y apellido |
| POST | `/auth/check-email` | Verifica si un email ya está registrado |
| POST | `/auth/forgot-password` | Envía código de recuperación (consola en dev) |
| POST | `/auth/verify-code` | Valida el código → devuelve `reset_token` |
| POST | `/auth/reset-password` | Cambia la contraseña |

### Productos (requieren Bearer token)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/products/` | Listar productos del usuario (filtros: `search`, `categoria`, `ubicacion`) |
| POST | `/products/` | Crear producto |
| GET | `/products/{id}` | Obtener un producto |
| PUT | `/products/{id}` | Actualizar producto |
| DELETE | `/products/{id}` | Eliminar producto |

---

## Migraciones

```bash
# Activar venv primero
source venv/bin/activate

# Aplicar todas las migraciones
alembic upgrade head

# Ver estado actual
alembic current

# Crear nueva migración después de cambiar un modelo
alembic revision --autogenerate -m "descripción"
```

---

## Acceso directo a la DB

```bash
docker-compose exec db psql -U user -d tpp_db
```

---

## Arquitectura de autenticación

```
Frontend → Backend → Keycloak
  login()    POST /auth/login    Direct Grant (usuario + contraseña)
  register() POST /auth/register Admin API (crea usuario en Keycloak)
  request()  Bearer token        Keycloak introspection por request
  profile()  PUT /auth/profile   Admin API (actualiza datos en Keycloak)
```

---

## Troubleshooting

**`ModuleNotFoundError`**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**`connection refused` en puerto 5432 o 8080**
```bash
docker-compose up -d db keycloak
# Esperar ~15s y reintentar
```

**`Address already in use` al levantar el backend**
```bash
pkill -f "python main.py" && python main.py
```

**Token expirado (401 en todos los endpoints)**
- El token de Keycloak dura 5 minutos. Hacer logout/login en la app para obtener uno nuevo.

**Keycloak data perdida**
- Solo se pierde si corriste `docker-compose down -v`. El simple `docker-compose down` y `up` preserva los datos (Keycloak usa Postgres como backend).
