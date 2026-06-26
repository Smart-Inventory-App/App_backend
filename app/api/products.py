from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.product import Product
from app.models.user import AuthUser
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse

from app.core.firebase import send_push

router = APIRouter(prefix="/products", tags=["products"])


def _get_user_product(product_id: int, user_id: str, db: Session) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.user_id == user_id,
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    return product

def _get_user(user_id: int, db: Session) -> AuthUser:
    user = db.query(AuthUser).filter(
        AuthUser.id == user_id
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return user

def _notificate_low_stock(token: str, product: Product):
    message_title = "Stock Bajo"
    message_body = "Hay pocas unidades del producto "+product.nombre+" ("+str(product.stock)+" unidades)."
    return send_push(token, message_title, message_body)
    # guardar alerta en db

def _notificate_expirancy(token: str, product: Product, expirancy_days: int):
    message_title = "Producto próximo a vencerse"
    message_body = "El producto "+product.nombre+" vence en "+str(expirancy_days)+"dias."
    return send_push(token, message_title, message_body)
    # guardar alerta en db

def _check_product_state(product: Product, user: AuthUser):
    stock_warning = 10 # valor por defecto
    expirancy_warning = 30
    expirancy_days = (product.vencimiento - date.today()).days
    if product.stock < stock_warning:
        response = _notificate_low_stock(user.firebase_token, product)
        print("\n\nse envio la noti de stock: "+response+"\n\n")
    if expirancy_days < expirancy_warning:
        response = _notificate_expirancy(user.firebase_token, product, expirancy_days)
        print("\n\nse envio la noti de vencimiento: "+response+"\n\n")



SORTABLE_FIELDS = {
    "nombre": Product.nombre,
    "stock": Product.stock,
    "vencimiento": Product.vencimiento,
    "categoria": Product.categoria,
}


@router.get("/", response_model=list[ProductResponse])
async def list_products(
    search: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    ubicacion: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, pattern="^(nombre|stock|vencimiento|categoria)$"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    query = db.query(Product).filter(Product.user_id == user_id)
    if search:
        term = f"%{search}%"
        query = query.filter(
            Product.nombre.ilike(term) | Product.marca.ilike(term)
        )
    if categoria:
        query = query.filter(Product.categoria.ilike(categoria))
    if ubicacion:
        query = query.filter(Product.ubicacion.ilike(ubicacion))
    if sort_by:
        column = SORTABLE_FIELDS[sort_by]
        query = query.order_by(column.desc() if sort_dir == "desc" else column.asc())
    else:
        query = query.order_by(Product.created_at.desc())
    return query.all()


@router.get("/filters/options")
async def get_filter_options(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    base = db.query(Product).filter(Product.user_id == user_id)
    categorias = [
        row[0] for row in base.with_entities(Product.categoria).distinct().all()
        if row[0]
    ]
    ubicaciones = [
        row[0] for row in base.with_entities(Product.ubicacion).distinct().all()
        if row[0]
    ]
    return {"categorias": sorted(categorias), "ubicaciones": sorted(ubicaciones)}


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = Product(user_id=current_user["sub"], **data.model_dump())
    db.add(product)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    db.refresh(product)
    return product


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_user_product(product_id, current_user["sub"], db)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = _get_user_product(product_id, current_user["sub"], db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    user = _get_user(current_user["sub"], db)
    _check_product_state(product, user)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = _get_user_product(product_id, current_user["sub"], db)
    db.delete(product)
    db.commit()
