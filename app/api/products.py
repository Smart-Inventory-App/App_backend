from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import AdminActivityLog
from app.models.product import Product
from app.models.profile import DEFAULT_DIAS_ALERTA_VENCIMIENTO, DEFAULT_STOCK_MINIMO, UserProfile
from app.models.user import AuthUser
from app.schemas.product import (
    ProductCreate,
    ProductDefaults,
    ProductResponse,
    ProductSuggestion,
    ProductUpdate,
)
from app.services.notifications import NotificationService

router = APIRouter(prefix="/products", tags=["products"])

notification_service = NotificationService(api_url=settings.NOTIFICATION_SERVICE_URL)

def _get_user_product(product_id: int, user_id: str, db: Session) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.user_id == user_id,
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    return product


def _get_or_create_profile(user_id: str, db: Session) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _find_matching_product(
    user_id: str, nombre: str, marca: Optional[str], vencimiento, db: Session
) -> Optional[Product]:
    query = db.query(Product).filter(
        Product.user_id == user_id,
        func.lower(func.trim(Product.nombre)) == nombre.strip().lower(),
    )
    if vencimiento is None:
        query = query.filter(Product.vencimiento.is_(None))
    else:
        query = query.filter(Product.vencimiento == vencimiento)
    marca_norm = marca.strip().lower() if marca else None
    if marca_norm is None:
        query = query.filter(Product.marca.is_(None))
    else:
        query = query.filter(func.lower(func.trim(Product.marca)) == marca_norm)
    return query.first()

def _log_activity(
    db: Session,
    event_type: str,
    actor_email: Optional[str],
    target_user_id: str,
    target_email: Optional[str],
    description: str,
) -> None:
    db.add(
        AdminActivityLog(
            event_type=event_type,
            actor_email=actor_email,
            target_user_id=target_user_id,
            target_email=target_email,
            description=description,
        )
    )
    db.commit()


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
    # return send_push(token, message_title, message_body)
    # guardar alerta en db
    return notification_service.send_notification(token, message_title, message_body, "")

def _notificate_expirancy(token: str, product: Product, expirancy_days: int):
    message_title = "Producto próximo a vencerse"
    message_body = "El producto "+product.nombre+" vence en "+str(expirancy_days)+"dias."
    return notification_service.send_notification(token, message_title, message_body, "")
    # guardar alerta en db

def _check_product_state(product: Product, user: AuthUser, profile: UserProfile):
    stock_warning = profile.stock_minimo or DEFAULT_STOCK_MINIMO
    expirancy_warning = profile.dias_alerta_vencimiento or DEFAULT_DIAS_ALERTA_VENCIMIENTO
    if product.stock < stock_warning:
        response, _ = _notificate_low_stock(user.firebase_token, product)
        print("\n\nse envio la notificacion de stock: "+str(response)+"\n\n")
    if product.vencimiento != None:
        expirancy_days = (product.vencimiento - date.today()).days
        if expirancy_days < expirancy_warning:
            response, _ = _notificate_expirancy(user.firebase_token, product, expirancy_days)
            print("\n\nse envio la notificacion de vencimiento: "+str(response)+"\n\n")



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
    marcas = [
        row[0] for row in base.with_entities(Product.marca).distinct().all()
        if row[0]
    ]
    return {"categorias": sorted(categorias), "ubicaciones": sorted(ubicaciones), "marcas": sorted(marcas)}


@router.get("/suggest", response_model=list[ProductSuggestion])
async def suggest_products(
    q: str = Query(..., min_length=1),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    rows = (
        db.query(Product)
        .filter(Product.user_id == user_id, Product.nombre.ilike(f"%{q}%"))
        .order_by(Product.created_at.desc())
        .limit(50)
        .all()
    )
    seen: set[str] = set()
    suggestions: list[ProductSuggestion] = []
    for p in rows:
        key = p.nombre.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            ProductSuggestion(nombre=p.nombre, marca=p.marca, categoria=p.categoria, ubicacion=p.ubicacion)
        )
        if len(suggestions) >= 8:
            break
    return suggestions


@router.get("/defaults", response_model=ProductDefaults)
async def get_defaults(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user["sub"]).first()
    if not profile:
        return ProductDefaults()
    return ProductDefaults(last_categoria=profile.last_categoria, last_ubicacion=profile.last_ubicacion)


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    actor_email = current_user.get("email")

    profile = _get_or_create_profile(user_id, db)
    profile.last_categoria = data.categoria
    profile.last_ubicacion = data.ubicacion
    db.commit()

    existing = _find_matching_product(user_id, data.nombre, data.marca, data.vencimiento, db)
    if existing:
        existing.stock += data.stock
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        db.refresh(existing)
        _log_activity(
            db, "product_updated", actor_email, user_id, actor_email,
            f"{actor_email or user_id} sumó {data.stock} unidades a \"{existing.nombre}\" (stock: {existing.stock})",
        )
        return ProductResponse.model_validate(existing, from_attributes=True).model_copy(update={"merged": True})

    product = Product(user_id=user_id, **data.model_dump())
    db.add(product)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    db.refresh(product)
    _log_activity(
        db, "product_created", actor_email, user_id, actor_email,
        f"{actor_email or user_id} cargó \"{product.nombre}\" (stock: {product.stock}) desde la app",
    )
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
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    product = _get_user_product(product_id, user_id, db)
    changed_fields = list(data.model_dump(exclude_unset=True).keys())
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    user = _get_user(user_id, db)
    profile = _get_or_create_profile(user_id, db)
    _check_product_state(product, user, profile)
    db.commit()
    db.refresh(product)
    if changed_fields:
        _log_activity(
            db, "product_updated", actor_email, user_id, actor_email,
            f"{actor_email or user_id} editó \"{product.nombre}\" ({', '.join(changed_fields)}) desde la app",
        )
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    product = _get_user_product(product_id, user_id, db)
    nombre = product.nombre
    db.delete(product)
    db.commit()
    _log_activity(
        db, "product_deleted", actor_email, user_id, actor_email,
        f"{actor_email or user_id} eliminó \"{nombre}\" desde la app",
    )
