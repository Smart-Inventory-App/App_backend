# 📚 Guía Completa: Crear Schemas y Subirlos a la BD

Este documento explica paso a paso cómo crear nuevos **modelos** (tablas en BD) y **schemas** (validación de API) en el backend.

---

## ⚙️ 0. Configurar el Ambiente (MUY IMPORTANTE)

Antes de hacer NADA, necesitas instalar las dependencias de Python.

### 🔧 Paso 0.1: Crear Virtual Environment (venv)

```bash
cd ~/TPP/App_backend

# Crear venv
python -m venv venv
```

### ✅ Paso 0.2: Activar venv

**En Linux/WSL (Ubuntu):**
```bash
source venv/bin/activate
```

**En Windows PowerShell:**
```bash
.\venv\Scripts\Activate.ps1
```

**En Windows CMD:**
```bash
venv\Scripts\activate.bat
```

📍 **Verás que el prompt cambia:**
```bash
# Antes
bigmak@DESKTOP-RS6CTER:~/TPP/App_backend$

# Después (venv activado)
(venv) bigmak@DESKTOP-RS6CTER:~/TPP/App_backend$
```

### 📦 Paso 0.3: Instalar Dependencias desde requirements.txt

```bash
# Con venv activado
pip install -r requirements.txt
```

**¿Qué hace esto?**
- Lee el archivo `requirements.txt`
- Instala todas las librerías necesarias:
  - `sqlalchemy` (ORM para BD)
  - `alembic` (migraciones)
  - `pydantic` (validación)
  - `fastapi` (API)
  - Y mucho más...

### 🔍 Verificar que está instalado

```bash
# Ver paquetes instalados
pip list | grep -E "sqlalchemy|alembic|pydantic"

# O simplemente
pip list
```

### 🚪 Paso 0.4: Salir del venv (cuando termines)

```bash
deactivate
```

---

### ⚠️ REGLA DE ORO

**Siempre ejecuta comandos de Python/Alembic dentro del venv:**

```bash
# ❌ MAL - Sin activar venv
$ alembic revision --autogenerate -m "Testeo"
Command 'alembic' not found

# ✅ BIEN - Con venv activado
(venv) $ alembic revision --autogenerate -m "Testeo"
Generating migration...
```

---

## 🏗️ Conceptos Previos

### **Models (SQLAlchemy)**
- **Qué es:** Representa una tabla en la base de datos
- **Ubicación:** `app/models/`
- **Propósito:** Definir estructura de datos persistente
- **Tecnología:** SQLAlchemy ORM

### **Schemas (Pydantic)**
- **Qué es:** Contrato de validación de datos de entrada/salida
- **Ubicación:** `app/schemas/`
- **Propósito:** Validar datos de API antes de guardar
- **Tecnología:** Pydantic V2

### **Relación**
```
Cliente → Schema (validación) → Model (guardar) → BD (PostgreSQL)
         ↓
    Pydantic           SQLAlchemy
```

---

## 🎯 Resumen de Pasos (Quick Reference)

```
1️⃣  Configurar Python Environment (venv + requirements)
2️⃣  Crear Model (SQLAlchemy) → app/models/
3️⃣  Crear Schema (Pydantic) → app/schemas/
4️⃣  Importar Model → app/models/__init__.py
5️⃣  Inicializar Alembic (solo primera vez)
6️⃣  Generar migración → alembic revision --autogenerate
7️⃣  Ejecutar migración → alembic upgrade head
8️⃣  Crear Servicio (opcional) → app/services/
9️⃣  Crear Rutas → app/routers/
🔟 Probar en http://localhost:8000/docs
```

---

## 📋 Paso 1: Crear el Model (SQLAlchemy)

### Ubicación
```
App_backend/
└── app/
    └── models/
        ├── __init__.py
        ├── user.py          ← Aquí
        └── transaction.py
```

### Ejemplo: Crear tabla de "Productos"

**Archivo:** `app/models/product.py`

```python
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class Product(Base):
    """Modelo de Productos"""
    __tablename__ = "products"
    
    # Campos obligatorios
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String(1000), nullable=True)
    
    # Relaciones
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Auditoría
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

### Tipos de Columnas Comunes

```python
# Texto
Column(String(50))              # String con límite
Column(String)                  # String sin límite
Column(Text)                    # Para textos muy largos

# Números
Column(Integer)                 # Entero
Column(Float)                   # Decimal
Column(Numeric(10, 2))          # Precisión: 10 dígitos, 2 decimales

# Booleanos y fechas
Column(Boolean, default=False)
Column(DateTime(timezone=True), server_default=func.now())

# Restricciones
nullable=False                  # Campo obligatorio
unique=True                     # Valor único
index=True                      # Indexado para búsquedas rápidas
ForeignKey("tabla.id")          # Relación con otra tabla
```

---

## 📋 Paso 2: Crear el Schema (Pydantic)

### Ubicación
```
App_backend/
└── app/
    └── schemas/
        ├── __init__.py
        ├── user.py          ← Ya existe
        └── product.py       ← Crear aquí
```

### Ejemplo: Schema de Productos

**Archivo:** `app/schemas/product.py`

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# ============================================
# Schemas de Creación/Actualización
# ============================================

class ProductCreate(BaseModel):
    """Schema para CREAR un producto"""
    name: str = Field(..., min_length=1, max_length=255)
    price: float = Field(..., gt=0)  # Mayor a 0
    description: Optional[str] = Field(None, max_length=1000)
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Laptop Dell",
                "price": 999.99,
                "description": "Laptop de 15 pulgadas"
            }
        }


class ProductUpdate(BaseModel):
    """Schema para ACTUALIZAR un producto"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    price: Optional[float] = Field(None, gt=0)
    description: Optional[str] = Field(None, max_length=1000)


# ============================================
# Schemas de Respuesta
# ============================================

class ProductResponse(BaseModel):
    """Schema para DEVOLVER un producto en la API"""
    id: int
    name: str
    price: float
    description: Optional[str] = None
    user_id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True  # ⭐ Crucial: mapea modelos SQLAlchemy


class ProductListResponse(BaseModel):
    """Schema para listar productos"""
    id: int
    name: str
    price: float
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
```

### Diferencias entre Schemas

| Schema | Uso | Campos |
|--------|-----|--------|
| `ProductCreate` | POST /products | name, price, description |
| `ProductUpdate` | PATCH /products/{id} | Todos opcionales |
| `ProductResponse` | GET /products | Todos + id, timestamps |

---

## 🗄️ Paso 3: Importar el Model en `__init__.py`

Para que SQLAlchemy encuentre todas las tablas, debes importar el modelo.

**Archivo:** `app/models/__init__.py`

```python
from app.models.user import User, Transaction
from app.models.product import Product  # ← Agregar esto

__all__ = ["User", "Transaction", "Product"]
```

---

## 🔄 Paso 4: Crear Migración (Alembic)

Las migraciones versionan los cambios de BD. PostgreSQL necesita que le digas qué tablas crear.

### Opción A: Migración automática (Recomendado)

**SIEMPRE** usa esto cuando cambias un modelo:

```bash
cd ~/TPP/App_backend

# ⚠️ IMPORTANTE: Activar venv primero
source venv/bin/activate

# Generar migración automáticamente
alembic revision --autogenerate -m "Descripción del cambio"
```

Esto crea un archivo: `alembic/versions/001_descripcion_del_cambio.py`

**Ejemplos:**
```bash
alembic revision --autogenerate -m "Add products table"
alembic revision --autogenerate -m "Add phone to users"
alembic revision --autogenerate -m "Change price column to float"
```

### Opción B: Migración manual

Si la automática no funciona o necesitas control total:

```bash
alembic revision -m "Descripción"
```

Editas manualmente el archivo generado en `alembic/versions/`

### 🔍 Revisar la migración

**Archivo generado:** `alembic/versions/xxx_descripcion.py`

```python
def upgrade() -> None:
    """Aplicar cambios"""
    # Código SQL generado automáticamente
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        # ... más columnas
    )


def downgrade() -> None:
    """Revertir cambios"""
    op.drop_table('products')
```

**⚠️ REVISA SIEMPRE antes de ejecutar**

### 🚀 Ejecutar la Migración

```bash
cd ~/TPP/App_backend

# Con venv activado (si no está, ejecuta: source venv/bin/activate)
alembic upgrade head

# Revertir último cambio (si algo sale mal)
alembic downgrade -1
```

### Verificar en PostgreSQL

```bash
# Conectar a BD
psql -U user -d tpp_db -h localhost

# Ver tablas
\dt

# Ver estructura de tabla
\d products

# Ver datos
SELECT * FROM products;
```

---

## 💻 Paso 6: Usar en Rutas de FastAPI

### Crear el servicio

**Archivo:** `app/services/product_service.py`

```python
from sqlalchemy.orm import Session
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate
from fastapi import HTTPException


class ProductService:
    """Servicio para operaciones con productos"""
    
    @staticmethod
    def create_product(db: Session, product: ProductCreate, user_id: int) -> Product:
        """Crear un producto"""
        db_product = Product(**product.dict(), user_id=user_id)
        db.add(db_product)
        db.commit()
        db.refresh(db_product)
        return db_product
    
    @staticmethod
    def get_product(db: Session, product_id: int) -> Product:
        """Obtener producto por ID"""
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return product
    
    @staticmethod
    def list_products(db: Session, user_id: int):
        """Listar productos del usuario"""
        return db.query(Product).filter(Product.user_id == user_id).all()
    
    @staticmethod
    def update_product(db: Session, product_id: int, product: ProductUpdate) -> Product:
        """Actualizar producto"""
        db_product = ProductService.get_product(db, product_id)
        for key, value in product.dict(exclude_unset=True).items():
            setattr(db_product, key, value)
        db.commit()
        db.refresh(db_product)
        return db_product
    
    @staticmethod
    def delete_product(db: Session, product_id: int) -> dict:
        """Eliminar producto"""
        db_product = ProductService.get_product(db, product_id)
        db.delete(db_product)
        db.commit()
        return {"message": "Producto eliminado"}
```

### Crear las rutas

**Archivo:** `app/routers/products.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse
from app.services.product_service import ProductService

router = APIRouter(
    prefix="/api/products",
    tags=["products"],
    dependencies=[Depends(get_current_user)]
)


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Crear un nuevo producto"""
    return ProductService.create_product(db, product, current_user.id)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    db: Session = Depends(get_db)
):
    """Obtener un producto"""
    return ProductService.get_product(db, product_id)


@router.get("", response_model=list[ProductResponse])
async def list_products(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Listar mis productos"""
    return ProductService.list_products(db, current_user.id)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Actualizar un producto"""
    return ProductService.update_product(db, product_id, product)


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Eliminar un producto"""
    return ProductService.delete_product(db, product_id)
```

### Incluir rutas en main.py

**Archivo:** `app/main.py`

```python
from fastapi import FastAPI
from app.routers import products  # ← Agregar

app.include_router(products.router)  # ← Agregar
```

---

## ✅ Checklist Completo

- [ ] Crear archivo `app/models/product.py` con la clase Model
- [ ] Crear archivo `app/schemas/product.py` con validaciones Pydantic
- [ ] Importar Model en `app/models/__init__.py`
- [ ] Ejecutar `alembic revision --autogenerate -m "mensaje"`
- [ ] Revisar migración en `alembic/versions/`
- [ ] Ejecutar `alembic upgrade head`
- [ ] Verificar tabla en PostgreSQL
- [ ] Crear archivo `app/services/product_service.py` (opcional pero recomendado)
- [ ] Crear archivo `app/routers/products.py` con endpoints
- [ ] Importar router en `app/main.py`
- [ ] Probar endpoints en `http://localhost:8000/docs`

---

## 🔄 Actualizar Modelos Existentes (ej: Users)

Si cambias un modelo que ya existe en la BD, necesitas actualizar la estructura. **Los Schemas NO necesitan migración, solo los Models.**

### Ejemplos de Cambios Comunes

#### Ejemplo 1: Agregar un campo

**Antes (model):**
```python
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    username = Column(String, unique=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

**Después (model) - Agregar teléfono:**
```python
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    username = Column(String, unique=True)
    hashed_password = Column(String)
    phone = Column(String, nullable=True)  # ← Nuevo campo
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

**Schema actualizado (opcional pero buena práctica):**
```python
class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    phone: Optional[str] = None  # ← Agregado

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    username: str
    phone: Optional[str] = None  # ← Agregado
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
```

**Actualizar BD:**
```bash
cd App_backend

# 1. Generar migración automáticamente
alembic revision --autogenerate -m "Add phone field to users"

# 2. Revisar el archivo generado en alembic/versions/

# 3. Ejecutar la migración
alembic upgrade head

# 4. Verificar en PostgreSQL
psql -U user -d tpp_db
\d users
```

---

#### Ejemplo 2: Cambiar tipo de dato

**Antes:**
```python
price = Column(Integer)  # Guardaba en centavos
```

**Después:**
```python
price = Column(Float)  # Ahora es float
```

**Proceso:**
```bash
alembic revision --autogenerate -m "Change price column type to float"
alembic upgrade head
```

---

#### Ejemplo 3: Hacer un campo obligatorio (NOT NULL)

**Antes:**
```python
description = Column(String, nullable=True)
```

**Después:**
```python
description = Column(String, nullable=False)
```

⚠️ **Cuidado:** Si hay datos existentes NULL, fallará. Solución:

```bash
# 1. Generar migración
alembic revision --autogenerate -m "Make description not null"

# 2. Editar alembic/versions/xxx.py manualmente:
def upgrade() -> None:
    # Primero actualizar NULLs
    op.execute("UPDATE users SET description = 'N/A' WHERE description IS NULL")
    # Luego cambiar constraint
    op.alter_column('users', 'description', nullable=False)

def downgrade() -> None:
    op.alter_column('users', 'description', nullable=True)

# 3. Ejecutar
alembic upgrade head
```

---

#### Ejemplo 4: Cambiar restricción UNIQUE

**Antes:**
```python
email = Column(String, unique=True)  # Solo un email por usuario
```

**Después:**
```python
email = Column(String)  # Puede haber múltiples
```

**Proceso:**
```bash
alembic revision --autogenerate -m "Remove unique constraint from email"
alembic upgrade head
```

---

### 🔑 Flujo Completo de Actualización

```
1. MODIFICAR Model (app/models/user.py)
         ↓
2. EJECUTAR alembic revision --autogenerate -m "descripción"
         ↓
3. REVISAR alembic/versions/xxx.py
         ↓
4. EJECUTAR alembic upgrade head
         ↓
5. VERIFICAR en PostgreSQL (\d users)
         ↓
6. ACTUALIZAR Schemas (opcional)
         ↓
7. ACTUALIZAR código que use esos campos
```

---

### ⚡ Comandos Clave para Migraciones

```bash
cd App_backend

# Ver estado actual
alembic current

# Ver historial de migraciones
alembic history

# Ver próximas migraciones sin ejecutar
alembic history -r current:

# Generar migración automática
alembic revision --autogenerate -m "Descripción de cambio"

# Ejecutar todas las pendientes
alembic upgrade head

# Ejecutar una migración específica
alembic upgrade <revision_id>

# Revertir última migración
alembic downgrade -1

# Revertir N migraciones
alembic downgrade -2

# Revertir a una migración específica
alembic downgrade <revision_id>

# Ver diferencias entre modelo actual y migraciones
alembic stamp head  # Si algo se desincronizó

# Limpiar estado (último recurso)
alembic downgrade base  # Elimina todas las tablas
alembic upgrade head    # Recrea desde cero
```

---

### 🎯 Mejores Prácticas

1. **Siempre revisar la migración generada** antes de `upgrade head`
2. **Agregar descripciones claras** en los mensajes de migración
3. **Hacer migraciones atómicas**: un cambio por migración
4. **En producción**: hacer backup antes de `upgrade head`
5. **Documentar cambios de schema** en un CHANGELOG
6. **Nunca editar migraciones aplicadas**: crear nueva migración si falló

---

## 🚀 Ejemplo Práctico Completo (Start to Finish)

Vamos a crear una tabla de **Categorías de Productos** de inicio a fin.

### Paso 1: Crear el archivo de modelo

**Archivo:** `app/models/category.py`

```python
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

### Paso 2: Crear el archivo de schema

**Archivo:** `app/schemas/category.py`

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

class CategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True
```

### Paso 3: Importar en `__init__.py`

**Archivo:** `app/models/__init__.py`

```python
from app.models.user import User, Transaction
from app.models.product import Product
from app.models.category import Category  # ← Agregar esta línea

__all__ = ["User", "Transaction", "Product", "Category"]
```

### Paso 4: Crear la migración

```bash
cd ~/TPP/App_backend

# Activar venv (si no está ya activado)
source venv/bin/activate

# Generar migración
alembic revision --autogenerate -m "Add categories table"

# Verificar el archivo generado (ver si se ve bien)
# Está en: alembic/versions/xxxxx_add_categories_table.py

# Ejecutar la migración
alembic upgrade head
```

**Output esperado:**
```
INFO  [alembic.runtime.migration] Running upgrade  -> xxxxx, Add categories table
```

### Paso 5: Verificar en BD

```bash
# Conectar a PostgreSQL
psql -U user -d tpp_db -h localhost

# Ver la tabla
\d categories

# Ver todas las tablas
\dt
```

### Paso 6: Crear servicio (opcional)

**Archivo:** `app/services/category_service.py`

```python
from sqlalchemy.orm import Session
from app.models.category import Category
from app.schemas.category import CategoryCreate

class CategoryService:
    @staticmethod
    def create(db: Session, category: CategoryCreate) -> Category:
        db_category = Category(**category.dict())
        db.add(db_category)
        db.commit()
        db.refresh(db_category)
        return db_category
    
    @staticmethod
    def list_all(db: Session):
        return db.query(Category).all()
```

### Paso 7: Crear rutas

**Archivo:** `app/routers/categories.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.category import CategoryCreate, CategoryResponse
from app.services.category_service import CategoryService

router = APIRouter(prefix="/api/categories", tags=["categories"])

@router.post("", response_model=CategoryResponse, status_code=201)
async def create_category(category: CategoryCreate, db: Session = Depends(get_db)):
    return CategoryService.create(db, category)

@router.get("", response_model=list[CategoryResponse])
async def list_categories(db: Session = Depends(get_db)):
    return CategoryService.list_all(db)
```

### Paso 8: Registrar router en main.py

**Archivo:** `app/main.py`

```python
from app.routers import categories  # ← Agregar

app.include_router(categories.router)  # ← Agregar
```

### ✅ ¡Listo! Probar endpoints

```bash
# Iniciar servidor
uvicorn app.main:app --reload

# En otra terminal:
curl -X POST "http://localhost:8000/api/categories" \
  -H "Content-Type: application/json" \
  -d '{"name": "Electrónica", "description": "Productos electrónicos"}'

# Ver categorías
curl -X GET "http://localhost:8000/api/categories"

# O acceder a Swagger
# http://localhost:8000/docs
```

---

## 🧪 Probar los Endpoints

### 1. Acceder a Swagger
```
http://localhost:8000/docs
```

### 2. Crear un producto
```bash
curl -X POST "http://localhost:8000/api/products" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "Laptop",
    "price": 1200.00,
    "description": "Laptop gaming"
  }'
```

### 3. Listar productos
```bash
curl -X GET "http://localhost:8000/api/products" \
  -H "Authorization: Bearer <token>"
```

---

## 🐛 Troubleshooting

### Error: "Table 'products' already exists"
```bash
# Revertir última migración
alembic downgrade -1

# Editar migración y ejecutar nuevamente
alembic upgrade head
```

### Error: "from_attributes = True not working"
Asegúrate que uses Pydantic V2:
```bash
pip install pydantic==2.5.0
```

### BD no conecta
Verificar variables en `.env`:
```bash
# Debe ser PostgreSQL, no SQLite
DATABASE_URL=postgresql://user:password@localhost:5432/tpp_db
```

---

## ⚡ Cheat Sheet - Referencia Rápida

### Setup Inicial (Primera Vez)
```bash
cd ~/TPP/App_backend
python -m venv venv
source venv/bin/activate  # Linux/WSL
pip install -r requirements.txt
alembic init alembic  # Solo primera vez
```

### Crear Nueva Tabla
```bash
# 1. Crear Model en app/models/
# 2. Crear Schema en app/schemas/
# 3. Importar Model en app/models/__init__.py
# 4. Generar y ejecutar migración:
source venv/bin/activate  # Asegurar venv activado
alembic revision --autogenerate -m "Descripción"
alembic upgrade head
# 5. Crear Servicio en app/services/
# 6. Crear Rutas en app/routers/
# 7. Registrar router en app/main.py
```

### Actualizar Tabla Existente
```bash
source venv/bin/activate
# Editar Model en app/models/
# Editar Schema en app/schemas/
alembic revision --autogenerate -m "Cambio"
# Revisar archivo en alembic/versions/
alembic upgrade head
```

### Comandos Comunes de Alembic
```bash
alembic current          # Ver migración actual
alembic history          # Ver historial
alembic revision --autogenerate -m "Mensaje"  # Crear migración
alembic upgrade head     # Aplicar migraciones pendientes
alembic downgrade -1     # Revertir última migración
alembic downgrade base   # Revertir todas (último recurso)
```

### Verificar en PostgreSQL
```bash
psql -U user -d tpp_db -h localhost
\dt              # Ver tablas
\d tabla_name    # Ver estructura
SELECT * FROM tabla;
\q               # Salir
```

### Estructura de Archivos
```
app/
├── models/
│   ├── __init__.py      ← Importar Model aquí
│   ├── user.py
│   └── producto.py      ← Nuevo Model
├── schemas/
│   ├── __init__.py
│   ├── user.py
│   └── producto.py      ← Nuevo Schema
├── services/
│   ├── __init__.py
│   └── producto_service.py  ← Lógica
└── routers/
    ├── __init__.py
    └── productos.py     ← Endpoints
```

---

## 📚 Documentación Oficial

- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)
- [Pydantic V2 Docs](https://docs.pydantic.dev/latest/)
- [Alembic Docs](https://alembic.sqlalchemy.org/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)

---

**Última actualización:** 2026-05-01
