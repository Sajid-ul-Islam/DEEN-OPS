"""Unit tests for SQLite customer identity database module (P2)."""

import pytest

from src.utils.customer_db import (
    init_customer_db,
    lookup_customer,
    upsert_customer,
    get_phone_registry_dict,
    _get_connection,
)


@pytest.fixture(autouse=True)
def clean_test_db(tmp_path, monkeypatch):
    """Use an isolated SQLite database in a temporary directory for tests."""
    db_file = str(tmp_path / "test_customer_registry.db")
    monkeypatch.setattr("src.utils.customer_db.CUSTOMER_DB_PATH", db_file)
    init_customer_db()
    yield db_file


def test_init_creates_tables_and_indexes():
    """Verify that init_customer_db creates table and indexes."""
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='customers';"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_customers_email';"
        )
        assert cursor.fetchone() is not None


def test_upsert_and_lookup_by_phone():
    """Verify inserting and looking up customer by normalized BD phone."""
    assert (
        upsert_customer(
            phone="+8801712345678",
            first_seen="2025-01-10",
            email="test@example.com",
            name="Rahim Uddin",
            city="Dhaka",
        )
        is True
    )

    # Lookup using different phone format (e.g. without +88)
    found = lookup_customer(phone="01712345678")
    assert found is not None
    assert found["phone"] == "01712345678"
    assert found["first_seen"] == "2025-01-10"
    assert found["email"] == "test@example.com"
    assert found["name"] == "Rahim Uddin"


def test_lookup_by_email_and_name():
    """Verify secondary email and tertiary name/city lookups."""
    upsert_customer(
        phone="01811223344",
        first_seen="2025-02-15",
        email="customer@brand.com",
        name="Karim Khan",
        city="Chittagong",
    )

    # By email
    by_email = lookup_customer(email="customer@brand.com")
    assert by_email is not None
    assert by_email["phone"] == "01811223344"

    # By name and city
    by_name = lookup_customer(name="Karim Khan", city="Chittagong")
    assert by_name is not None
    assert by_name["phone"] == "01811223344"


def test_upsert_retains_earliest_first_seen():
    """Repeated orders keep the earliest first_seen date."""
    upsert_customer(phone="01999888777", first_seen="2025-05-01")
    upsert_customer(phone="01999888777", first_seen="2025-06-01")  # later date
    upsert_customer(phone="01999888777", first_seen="2025-03-01")  # earlier date

    rec = lookup_customer(phone="01999888777")
    assert rec["first_seen"] == "2025-03-01"
    assert rec["order_count"] == 3


def test_get_phone_registry_dict():
    """Verify bulk dict extraction for backwards compatibility."""
    upsert_customer(phone="01700000001", first_seen="2024-01-01")
    upsert_customer(phone="01700000002", first_seen="2024-02-01")

    mapping = get_phone_registry_dict()
    assert mapping.get("01700000001") == "2024-01-01"
    assert mapping.get("01700000002") == "2024-02-01"
