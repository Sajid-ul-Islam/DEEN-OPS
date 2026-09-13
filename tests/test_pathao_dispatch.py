"""Exercise the real processing-to-dispatch flow without merchant API writes."""

from unittest.mock import Mock

import pandas as pd
import pytest
from streamlit.runtime.state.session_state_proxy import SessionStateProxy
from streamlit.testing.v1 import AppTest

from src.pages.pathao_orders import dispatch_tab as dispatch
from src.processing.order_processor import process_orders_dataframe
from src.services.pathao.dispatch_ledger import DispatchLedger
from src.services.pathao.orders import PathaoOrderError


@pytest.fixture
def processed_orders():
    rows = []
    for order_id, phone, location, quantity in (
        ("12345", "01712345678", "Ecom-Mirpur", 2),
        ("12345", "01712345678", "Cumilla", 1),
        ("12346", "01812345678", "Ecom-Mirpur", 1),
    ):
        rows.append(
            {
                "Order ID": order_id,
                "Order Number": order_id,
                "Phone (Billing)": phone,
                "First Name (Shipping)": "Test",
                "Last Name (Shipping)": "Buyer",
                "Address 1&2 (Shipping)": "House 1, Dhanmondi, Dhaka",
                "City (Shipping)": "Dhanmondi",
                "State Code (Shipping)": "Dhaka",
                "Item Name": "Formal Shirt",
                "Quantity": quantity,
                "Item Cost": 100,
                "Order Total Amount": 360 if order_id == "12345" else 160,
                "Payment Method Title": "Cash on delivery",
                "Dispatch Suggestion": location,
            }
        )
    return process_orders_dataframe(pd.DataFrame(rows))


@pytest.fixture
def prepared(processed_orders):
    entries, errors = dispatch._prepare_dispatch(
        processed_orders,
        {"Ecom Mirpur": 11, "Cumilla Outlet": 22},
        "test-account",
        special_instructions="Call before delivery",
    )
    assert not errors
    return entries


def test_real_processor_uses_correct_store_customer_cod_and_split_parcels(prepared):
    assert len(prepared) == 3
    payloads = [entry["payload"] for entry in prepared]
    assert {p["merchant_order_id"] for p in payloads} == {"12345", "12345 c", "12346"}
    assert sum(p["amount_to_collect"] for p in payloads) == 520
    for entry in prepared:
        payload = entry["payload"]
        assert payload["store_id"] == (
            22 if entry["outlet"] == "Cumilla Outlet" else 11
        )
        assert payload["recipient_name"] == "Test Buyer"
        assert payload["recipient_address"] == "House 1, Dhanmondi, Dhaka"
        assert "Call before delivery" in payload["special_instruction"]
        assert "recipient_city" not in payload
        assert "recipient_zone" not in payload
    assert (
        next(p for p in payloads if p["merchant_order_id"] == "12345")["item_quantity"]
        == 2
    )


def test_missing_store_and_duplicate_rows_block_batch_validation(processed_orders):
    entries, errors = dispatch._prepare_dispatch(processed_orders, {}, "test-account")
    assert not entries and len(errors) == 3
    duplicated = pd.concat([processed_orders.iloc[:1], processed_orders.iloc[:1]])
    _, errors = dispatch._prepare_dispatch(
        duplicated, {"Cumilla Outlet": 22, "Ecom Mirpur": 11}, "test-account"
    )
    assert len(errors) == 1
    assert "Duplicate" in errors[0]["Error"]


def test_successful_creation_is_skipped_after_restart(tmp_path, prepared):
    client = Mock()
    client.create_order.side_effect = [
        {"consignment_id": f"TEST-{i}"} for i in range(3)
    ]
    path = tmp_path / "dispatch.sqlite3"
    with DispatchLedger(path) as ledger:
        report = dispatch._dispatch_batch(client, ledger, prepared)
    assert all(row["Status"] == "Created" for row in report)
    with DispatchLedger(path) as ledger:
        repeated = dispatch._dispatch_batch(client, ledger, prepared)
    assert all(row["Status"] == "Already created" for row in repeated)
    assert [r["Consignment"] for r in repeated] == [r["Consignment"] for r in report]
    assert client.create_order.call_count == 3


def test_retry_sends_only_known_rejections(tmp_path, prepared):
    client = Mock()
    client.create_order.side_effect = [
        {"consignment_id": "TEST-1"},
        PathaoOrderError("Invalid store"),
        {"consignment_id": "TEST-3"},
        {"consignment_id": "TEST-2"},
    ]
    with DispatchLedger(tmp_path / "dispatch.sqlite3") as ledger:
        report = dispatch._dispatch_batch(client, ledger, prepared)
        assert [r["Status"] for r in report] == ["Created", "Failed", "Created"]
        retry = dispatch._dispatch_batch(client, ledger, prepared)
    assert [r["Status"] for r in retry] == [
        "Already created",
        "Created",
        "Already created",
    ]
    assert client.create_order.call_count == 4


@pytest.mark.parametrize(
    "error", [PathaoOrderError("Timed out", uncertain=True), RuntimeError("unexpected")]
)
def test_unconfirmed_attempts_cannot_be_reposted(tmp_path, prepared, error):
    client = Mock()
    client.create_order.side_effect = error
    with DispatchLedger(tmp_path / "dispatch.sqlite3") as ledger:
        first = dispatch._dispatch_batch(client, ledger, prepared[:1])
        retry = dispatch._dispatch_batch(client, ledger, prepared[:1])
    assert first[0]["Status"] == retry[0]["Status"] == "Check Pathao"
    assert client.create_order.call_count == 1


def test_failed_parcel_prevents_premature_wc_update(monkeypatch):
    update = Mock(return_value=(True, "Success"))
    monkeypatch.setattr(dispatch, "update_order_status", update)
    report = [
        {"Order": "12345, 12346", "Status": "Created", "Consignment": "TEST-1"},
        {"Order": "12345 c", "Status": "Failed", "Consignment": ""},
    ]
    messages = dispatch._sync_created_orders(report)
    assert update.call_count == 1
    assert update.call_args.args == ("12346", "confirmed")
    assert any(m["Order"] == "12345" and "Not updated" in m["Result"] for m in messages)


def test_split_retry_syncs_each_merged_wc_order_once(monkeypatch):
    update = Mock(return_value=(True, "Success"))
    monkeypatch.setattr(dispatch, "update_order_status", update)
    report = [
        {"Order": "12345, 12346", "Status": "Already created", "Consignment": "TEST-1"},
        {"Order": "12345 c, 12346 c", "Status": "Created", "Consignment": "TEST-2"},
    ]
    dispatch._sync_created_orders(report)
    assert [call.args[0] for call in update.call_args_list] == ["12345", "12346"]
    assert all(
        "TEST-1, TEST-2" in call.kwargs["note"] for call in update.call_args_list
    )
    for row in report:
        row["Status"] = "Already created"
    dispatch._sync_created_orders(report)
    assert update.call_count == 2


def test_wc_failure_keeps_successful_consignment(monkeypatch, tmp_path, prepared):
    client = Mock()
    client.create_order.return_value = {"consignment_id": "TEST-CREATED"}
    monkeypatch.setattr(
        dispatch,
        "update_order_status",
        Mock(return_value=(False, "WooCommerce unavailable")),
    )
    with DispatchLedger(tmp_path / "dispatch.sqlite3") as ledger:
        report = dispatch._dispatch_batch(client, ledger, prepared[:1])
        messages = dispatch._sync_created_orders(report)
        retry = dispatch._dispatch_batch(client, ledger, prepared[:1])
    assert report[0]["Status"] == "Created"
    assert messages[0]["Result"] == "WooCommerce unavailable"
    assert retry[0]["Consignment"] == "TEST-CREATED"
    assert client.create_order.call_count == 1


def test_dispatch_screen_store_selection_creation_and_rerun(
    monkeypatch, tmp_path, processed_orders
):
    # Other legacy tests replace the global proxy. Restore a real proxy for AppTest.
    monkeypatch.setattr(dispatch.st, "session_state", SessionStateProxy())
    client = Mock(
        base_url="https://pathao.invalid", client_id="test-client", username="test-user"
    )
    client.get_stores.return_value = (
        [{"store_id": 11, "store_name": "Test Pickup", "is_active": 1}],
        None,
    )
    client.create_order.return_value = {"consignment_id": "TEST-UI"}
    monkeypatch.setattr(dispatch, "_get_pathao_client", lambda: client)
    monkeypatch.setattr(
        dispatch, "DispatchLedger", lambda: DispatchLedger(tmp_path / "ui.sqlite3")
    )
    update = Mock()
    monkeypatch.setattr(dispatch, "update_order_status", update)
    app = AppTest.from_string(
        "from src.pages.pathao_orders.dispatch_tab import _render_auto_dispatch_tab\n_render_auto_dispatch_tab()",
        default_timeout=10,
    )
    app.session_state["pathao_res_df"] = processed_orders.iloc[:1]
    app.run(timeout=10)
    assert not app.exception
    assert app.button(key="pathao_autodispatch_btn").disabled
    client.create_order.assert_not_called()
    app.button(key="pathao_load_stores").click().run(timeout=10)
    assert not app.exception
    app.selectbox[0].set_value(11).run(timeout=10)
    assert not app.button(key="pathao_autodispatch_btn").disabled
    app.button(key="pathao_autodispatch_btn").click().run(timeout=10)
    assert not app.exception
    assert app.session_state["pathao_dispatch_report"][0]["Status"] == "Created"
    app.run(timeout=10)
    app.button(key="pathao_autodispatch_btn").click().run(timeout=10)
    assert not app.exception
    assert app.session_state["pathao_dispatch_report"][0]["Status"] == "Already created"
    client.create_order.assert_called_once()
    update.assert_not_called()
