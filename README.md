# App Backend - TPP

FastAPI backend para Smart Inventory Application.

---

## 📋 Tabla de Contenidos

1. [Setup Local](#setup-local)
2. [Desarrollo](#desarrollo)
3. [Testing](#testing)
4. [Preparar para Deployment](#preparar-para-deployment)
5. [Deployment](#deployment)
6. [Troubleshooting](#troubleshooting)

---

## Setup Local

### Requisitos Previos

- **Docker & Docker Compose** (para desarrollo con containers)
- **Python 3.10+** (opcional, para desarrollo sin Docker)
- **WSL 2** (en Windows)
- **Git**

### Opción 1: Setup con Docker (Recomendado)

#### Paso 1: Clonar y navegar al proyecto

```bash
cd App_backend
```

#### Paso 2: Crear archivo `.env` para desarrollo

```bash
cat > .env << 'EOF'
# Database
DATABASE_URL=postgresql://user:password@db:5432/tpp_db

# API Config
API_TITLE=TPP API
API_VERSION=1.0.0
DEBUG=True
SECRET_KEY=dev-secret-key-change-in-production

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8081,http://localhost:8100,http://localhost:19000,http://10.0.2.2:8000

# JWT
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Server
HOST=0.0.0.0
PORT=8000
EOF
```

#### Paso 3: Levantar los containers

```bash
# Inicia PostgreSQL + FastAPI
docker-compose up -d

# Verifica que esté corriendo
docker ps
```

Deberías ver dos containers:
- `tpp_db` (PostgreSQL)
- `tpp_backend` (FastAPI)

#### Paso 4: Verificar que está funcionando

```bash
# Ver logs en vivo
docker-compose logs -f backend

# Acceder a la API
curl http://localhost:8000/health
```

#### Paso 5: Acceder a la documentación

Abre tu navegador:
- **Swagger UI (interactivo):** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc


## Desarrollo

### Estructura del Proyecto

```
App_backend/
├── app/
│   ├── main.py              # Punto de entrada
│   ├── api/                 # Endpoints
│   │   ├── auth.py
│   │   ├── health.py
│   │   └── transactions.py
│   ├── core/                # Configuración
│   │   ├── config.py
│   │   ├── database.py
│   │   └── security.py
│   ├── models/              # SQLAlchemy models
│   │   └── user.py
│   ├── routers/             # FastAPI routers
│   │   ├── api.py
│   │   └── auth.py
│   ├── schemas/             # Pydantic schemas
│   │   └── user.py
│   └── services/            # Lógica de negocio
│       └── user_service.py
├── tests/                   # Tests
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env                     # Configuración (no commitar)
```

### Endpoints Principales

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/version` | Versión del API |
| GET | `/test` | Test de conexión |
| POST | `/auth/register` | Registrar usuario |
| POST | `/auth/login` | Login |

### Ver logs en desarrollo

```bash
# Con Docker
docker-compose logs -f backend

# Sin Docker
# Los logs aparecen en consola automáticamente
```

### Editar la base de datos en desarrollo

```bash
# Acceso directo a PostgreSQL
docker exec -it tpp_db psql -U user -d tpp_db

# O con psql instalado localmente
psql -U user -d tpp_db -h localhost
```

---

## Testing

### Ejecutar tests

```bash
# Con Docker
docker-compose exec backend pytest

# Sin Docker (con venv activado)
pytest
```

### Tests disponibles

```bash
# Todos los tests
pytest

# Solo tests de auth
pytest tests/test_auth.py

# Con output verbose
pytest -v

# Solo un test específico
pytest tests/test_auth.py::test_login
```


---

## Detener todo

```bash
# Detener containers
docker-compose down

# Detener y remover volúmenes (cuidado: elimina datos)
docker-compose down -v
```

---

## 🐛 Troubleshooting

**"Module not found" errors:**
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

**PostgreSQL connection refused:**
```bash
# Verifica que tpp_db esté healthy
docker ps
# Si no está healthy, espera 10 segundos y reinicia
docker-compose restart backend
```

---

## 🔗 Conexión Frontend

El frontend en `App_Frontend` se conecta a través de HTTP:
- URL: `http://localhost:8000`
- Variable de entorno: `EXPO_PUBLIC_API_URL`

Prueba la conexión con el botón "Test Backend" en la app.