"""Product schema validation tests."""
import pytest
from pydantic import ValidationError

from app.schemas.product import ProductCreate, ProductUpdate


def test_create_valid():
    p = ProductCreate(nombre="Leche", categoria="Lacteos", stock=10)
    assert p.nombre == "Leche"
    assert p.stock == 10


def test_create_nombre_too_long():
    with pytest.raises(ValidationError):
        ProductCreate(nombre="A" * 21, categoria="Cat", stock=5)


def test_create_nombre_max_allowed():
    p = ProductCreate(nombre="A" * 20, categoria="Cat", stock=5)
    assert len(p.nombre) == 20


def test_create_categoria_too_long():
    with pytest.raises(ValidationError):
        ProductCreate(nombre="Prod", categoria="C" * 21, stock=5)


def test_create_categoria_max_allowed():
    p = ProductCreate(nombre="Prod", categoria="C" * 20, stock=5)
    assert len(p.categoria) == 20


def test_create_descripcion_too_long():
    with pytest.raises(ValidationError):
        ProductCreate(nombre="Prod", categoria="Cat", stock=5, descripcion="D" * 401)


def test_create_descripcion_max_allowed():
    p = ProductCreate(nombre="Prod", categoria="Cat", stock=5, descripcion="D" * 400)
    assert len(p.descripcion) == 400


def test_create_stock_zero_invalid():
    with pytest.raises(ValidationError):
        ProductCreate(nombre="Prod", categoria="Cat", stock=0)


def test_create_stock_negative_invalid():
    with pytest.raises(ValidationError):
        ProductCreate(nombre="Prod", categoria="Cat", stock=-1)


def test_create_stock_one_valid():
    p = ProductCreate(nombre="Prod", categoria="Cat", stock=1)
    assert p.stock == 1


def test_create_optional_fields_default_none():
    p = ProductCreate(nombre="Prod", categoria="Cat", stock=5)
    assert p.marca is None
    assert p.descripcion is None
    assert p.imagen_url is None
    assert p.ubicacion is None
    assert p.vencimiento is None


def test_update_partial_fields():
    u = ProductUpdate(stock=20)
    assert u.stock == 20
    assert u.nombre is None


def test_update_stock_zero_invalid():
    with pytest.raises(ValidationError):
        ProductUpdate(stock=0)


def test_update_nombre_too_long():
    with pytest.raises(ValidationError):
        ProductUpdate(nombre="A" * 21)


def test_update_categoria_too_long():
    with pytest.raises(ValidationError):
        ProductUpdate(categoria="C" * 21)


def test_update_descripcion_too_long():
    with pytest.raises(ValidationError):
        ProductUpdate(descripcion="D" * 401)


def test_update_all_none_is_valid():
    u = ProductUpdate()
    assert u.nombre is None
    assert u.stock is None
