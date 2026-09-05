from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Literal, Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse


class EventRequest(BaseModel):
    event_type: Literal["consumed", "expired"]
    quantity: int

router = APIRouter(prefix="/products", tags=["products"])


def _get_user_product(product_id: int, user_id: str, db: Session) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.user_id == user_id,
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    return product


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
    new_stock = data.model_dump(exclude_unset=True).get("stock")
    if new_stock is not None and new_stock < product.stock:
        event = ConsumptionEvent(
            product_id=product.id,
            user_id=product.user_id,
            quantity=product.stock - new_stock,
            event_type="consumed",
        )
        db.add(event)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}/consumption")
async def get_consumption_history(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_user_product(product_id, current_user["sub"], db)
    events = (
        db.query(ConsumptionEvent)
        .filter(ConsumptionEvent.product_id == product_id)
        .order_by(ConsumptionEvent.consumed_at.asc())
        .all()
    )
    return [
        {"id": e.id, "quantity": e.quantity, "event_type": e.event_type, "consumed_at": e.consumed_at}
        for e in events
    ]


@router.get("/expired", response_model=list[ProductResponse])
async def get_expired_products(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Productos vencidos con stock > 0 que aún no fueron confirmados."""
    today = date.today()
    return (
        db.query(Product)
        .filter(
            Product.user_id == current_user["sub"],
            Product.vencimiento < today,
            Product.stock > 0,
        )
        .all()
    )


@router.post("/{product_id}/events", status_code=status.HTTP_201_CREATED)
async def register_event(
    product_id: int,
    data: EventRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    El frontend llama este endpoint cuando el usuario responde al pop-up de vencimiento.
    event_type='consumed': el usuario lo consumió antes de que venciera.
    event_type='expired': el producto venció sin consumirse → stock se pone a 0.
    """
    product = _get_user_product(product_id, current_user["sub"], db)

    if data.quantity <= 0 or data.quantity > product.stock:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cantidad inválida",
        )

    event = ConsumptionEvent(
        product_id=product.id,
        user_id=product.user_id,
        quantity=data.quantity,
        event_type=data.event_type,
    )
    db.add(event)
    product.stock = max(0, product.stock - data.quantity)
    db.commit()
    return {"event_type": data.event_type, "quantity": data.quantity, "remaining_stock": product.stock}


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = _get_user_product(product_id, current_user["sub"], db)
    db.delete(product)
    db.commit()
