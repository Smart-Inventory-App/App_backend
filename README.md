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

Copiar el ejemplo y completar los valores:

```bash
cp .env.example .env
```

### 2. Crear el virtualenv e instalar dependencias

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

En Windows usar `.venv\Scripts\pip`.

### 3. Levantar Postgres y Keycloak

```bash
docker compose up -d db keycloak
```

Esto levanta:
- `tpp_db` — PostgreSQL en el puerto `5432`
- `tpp_keycloak` — Keycloak en http://localhost:8080 (admin / admin)

Esperar ~15 segundos a que Keycloak termine de iniciar antes del siguiente paso.

### 4. Crear las tablas en la DB

```bash
.venv/bin/alembic upgrade head
```

### 5. Configurar Keycloak (primera vez)

El realm `tpp` y el cliente `tpp-app` se deben crear una sola vez. Ejecutar el siguiente script:

```bash
.venv/bin/python scripts/setup_keycloak.py
```

> Si el script no existe todavía, crear el realm y cliente manualmente desde http://localhost:8080 con los valores del `.env`, o pedirle al equipo el dump de configuración.

### 6. Levantar el backend

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verificar en: http://localhost:8000  
Swagger: http://localhost:8000/docs

---

## Estructura del proyecto

```
App_backend/
├── app/
│   ├── api/
│   │   ├── auth.py          # Endpoints de autenticación (Keycloak)
│   │   ├── health.py
│   │   └── transactions.py
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── database.py
│   │   └── security.py      # Validación de token via Keycloak introspection
│   ├── models/
│   │   └── user.py          # User, Transaction, PasswordRecoveryCode
│   ├── schemas/
│   │   └── user.py          # Pydantic schemas
│   └── services/
│       ├── keycloak_service.py  # Wrapper sobre la REST API de Keycloak
│       └── user_service.py
├── alembic/
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── d363a82a2827_testeo.py
│       └── a1b2c3d4e5f6_add_password_recovery_codes.py
├── docker-compose.yml
├── requirements.txt
├── .env                     # No se commitea
└── .env.example
```

---

## Endpoints de autenticación

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/auth/register` | Crear usuario en Keycloak |
| POST | `/auth/login` | Login → devuelve JWT de Keycloak |
| GET | `/auth/me` | Info del usuario autenticado |
| POST | `/auth/check-email` | Verifica si un email ya está registrado |
| POST | `/auth/forgot-password` | Envía código de 6 dígitos por mail (o lo imprime en consola si SMTP no está configurado) |
| POST | `/auth/verify-code` | Valida el código → devuelve `reset_token` |
| POST | `/auth/reset-password` | Cambia la contraseña usando el `reset_token` |

---

## Migraciones

```bash
# Aplicar todas las migraciones
.venv/bin/alembic upgrade head

# Ver estado actual
.venv/bin/alembic current

# Crear nueva migración (después de cambiar un modelo)
.venv/bin/alembic revision --autogenerate -m "descripción"
```

---

## Acceso directo a la DB

```bash
docker exec -it tpp_db psql -U user -d tpp_db
```

---

## Arquitectura de autenticación

El backend **no genera ni almacena tokens propios**. Actúa como proxy entre el frontend y Keycloak:

```
Frontend → Backend → Keycloak
  login()    POST /auth/login    Direct Grant (usuario + contraseña)
  register() POST /auth/register Admin API (crea usuario en Keycloak)
  request()  Bearer token        Keycloak introspection por request
```

Los códigos de recuperación de contraseña (6 dígitos, validez 1h) sí se almacenan en la tabla `password_recovery_codes`.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'pydantic_settings'`**
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

**`connection refused` en puerto 5432 o 8080**
```bash
docker compose up -d db keycloak
# Esperar ~15s y reintentar
```

**`Auth service unavailable`** al llamar `/auth/register` o `/auth/login`
- Keycloak no terminó de iniciar. Esperá y reintentá.
- Verificar: `curl http://localhost:8080` debe devolver un redirect.

**`Account is not fully set up`** al hacer login en Keycloak
- El realm `tpp` no tiene el perfil de usuario configurado correctamente.
- Seguir el paso 5 de Setup para reconfigurar el realm.
