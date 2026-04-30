# App Backend - TPP

FastAPI backend para Smart Inventory Application.

## 🚀 Quick Start - Desarrollo Local

### Requisitos
- Docker & Docker Compose
- WSL 2 (en Windows)

### Levanta el Backend con Docker

```bash
cd App_backend

# Inicia PostgreSQL + FastAPI
docker-compose up -d

# Verifica que esté corriendo
docker ps
```

Deberías ver dos containers:
- `tpp_db` (PostgreSQL)
- `tpp_backend` (FastAPI)

### Ver logs en vivo

```bash
# Logs del backend
docker-compose logs -f backend

# O solo últimas líneas
docker-compose logs backend
```

### Accede a la API

- **Swagger UI (documetación interactiva):** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Health check:** http://localhost:8000/health

### Detener todo

```bash
docker-compose down
```

---

## 📝 Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/version` | Versión del API |
| GET | `/test` | Test de conexión (imprime en logs) |
| POST | `/auth/register` | Registrar usuario |
| POST | `/auth/login` | Login |

---

## 🔧 Configuración

El archivo `.env` controla:

```env
DATABASE_URL=postgresql://user:password@db:5432/tpp_db
DEBUG=True
SECRET_KEY=dev-secret-key
ALLOWED_ORIGINS=[...]
```

Cambios en `.env` se aplican automáticamente (Docker recompila).

---

## 📊 Base de datos

Las tablas se crean automáticamente:
- `users` - Usuarios registrados
- `transactions` - Transacciones

Acceso directo a PostgreSQL:
```bash
docker exec -it tpp_db psql -U user -d tpp_db
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