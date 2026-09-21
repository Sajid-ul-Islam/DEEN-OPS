"""Processing-tab rerun regressions, using real ETL and in-memory UI inputs."""

from io import BytesIO

import pandas as pd
import pytest

from src.pages.pathao_orders import processing_tab, shared


class SessionState(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


class FakeUI:
    def __init__(self):
        self.session_state = SessionState()
        self.source = shared.SOURCE_UPLOAD
        self.upload = None
        self.clicked = set()
        self.selections = {}
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.messages.append((name, args))
            return self

        return record

    def columns(self, widths):
        return [self] * (widths if isinstance(widths, int) else len(widths))

    def pills(self, *_args, **_kwargs):
        return self.source

    def file_uploader(self, *_args, **_kwargs):
        return self.upload

    def button(self, label, *, key=None, disabled=False, **_kwargs):
        return not disabled and (key or label) in self.clicked

    def selectbox(self, _label, options, *, key, index=0, **_kwargs):
        selected = self.selections.get(key, self.session_state.get(key, options[index]))
        self.session_state[key] = selected
        return selected


def upload(df, name="orders.csv"):
    file = BytesIO(df.to_csv(index=False).encode())
    file.name = name
    return file


@pytest.fixture
def orders():
    return pd.DataFrame(
        [
            {
                "Phone (Billing)": "01712345678",
                "First Name (Shipping)": "Sample Customer",
                "Address 1&2 (Shipping)": "House 12, Road 5, Mirpur",
                "City (Shipping)": "Mirpur",
                "State Code (Shipping)": "Dhaka",
                "Order ID": "1001",
                "Item Name": "Oxford Shirt - Navy",
                "Quantity": 2,
                "Item Cost": 250,
                "Order Total Amount": 500,
                "Payment Method Title": "Cash on delivery",
            }
        ]
    )


@pytest.fixture
def page(monkeypatch):
    ui = FakeUI()
    monkeypatch.setattr(processing_tab, "st", ui)
    monkeypatch.setattr(shared, "st", ui)
    for helper in ("render_reset_confirm", "render_status_toggle", "section_card"):
        monkeypatch.setattr(processing_tab, helper, lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        processing_tab,
        "render_sticky_action_bar",
        lambda **_kwargs: (
            "pathao_process_btn" in ui.clicked,
            "pathao_clear_btn" in ui.clicked,
        ),
    )
    monkeypatch.setattr(
        processing_tab,
        "render_dataframe_search",
        lambda df, *_args, **_kwargs: df,
    )
    monkeypatch.setattr(processing_tab, "save_state", lambda: None)
    monkeypatch.setattr(processing_tab, "log_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        processing_tab, "export_to_styled_excel", lambda *_args, **_kwargs: b"xlsx"
    )
    process = processing_tab.process_orders_dataframe
    ui.processed = []

    def process_and_record(df):
        ui.processed.append(df.copy())
        return process(df)

    monkeypatch.setattr(processing_tab, "process_orders_dataframe", process_and_record)
    return ui


def render(page, *clicked):
    page.clicked = set(clicked)
    processing_tab._render_processing_tab()


def test_confirm_processes_upload_and_survives_reruns(page, orders):
    page.upload = upload(orders)
    render(page)
    assert page.session_state.pathao_res_df is None
    assert not page.processed

    render(page, "confirm_columns")
    result = page.session_state.pathao_res_df
    assert len(page.processed) == 1
    assert result.iloc[0]["MerchantOrderId"] == "1001"
    assert result.iloc[0]["RecipientPhone(*)"] == "01712345678"
    assert result.iloc[0]["AmountToCollect(*)"] == 500

    page.upload = upload(orders)  # Same content in a fresh uploader object.
    render(page)
    assert len(page.processed) == 1
    pd.testing.assert_frame_equal(page.session_state.pathao_res_df, result)
    render(page, "pathao_process_btn")
    assert len(page.processed) == 2
    pd.testing.assert_frame_equal(page.session_state.pathao_res_df, result)


@pytest.mark.parametrize("change", ["contents", "name", "removed"])
def test_replacing_or_removing_file_invalidates_previous_output(page, orders, change):
    page.upload = upload(orders)
    render(page, "confirm_columns")
    page.session_state.pathao_vlink_df = pd.DataFrame({"old": [1]})
    page.session_state.show_vlink_gen = True
    if change == "contents":
        page.upload = upload(orders.assign(**{"Order ID": "2002"}))
    elif change == "name":
        page.upload = upload(orders, "replacement.csv")
    else:
        page.upload = None

    render(page, "pathao_process_btn")
    assert page.session_state.pathao_res_df is None
    assert page.session_state.pathao_vlink_df is None
    assert page.session_state.pathao_mapping_confirmation is None
    assert not page.session_state.show_vlink_gen
    assert len(page.processed) == 1


def test_manual_mapping_survives_reruns_and_changes_require_confirmation(page, orders):
    custom_names = {
        "Phone (Billing)": "Buyer contact",
        "First Name (Shipping)": "Buyer fullname",
        "Address 1&2 (Shipping)": "Delivery destination",
        "Order ID": "Purchase reference",
        "Item Name": "Product title",
        "Quantity": "Units ordered",
        "Item Cost": "Price per unit",
        "Order Total Amount": "Gross amount",
    }
    custom = orders.rename(columns=custom_names)
    custom["Alternate contact"] = "01812345678"
    page.upload = upload(custom)
    page.selections = {
        f"pathao_map_{standard}": source for standard, source in custom_names.items()
    }
    render(page, "confirm_columns")
    render(page, "pathao_process_btn")
    assert len(page.processed) == 2
    assert page.processed[-1]["Phone (Billing)"].iloc[0] == 1712345678
    result = page.session_state.pathao_res_df.iloc[0]
    assert result["MerchantOrderId"] == "1001"
    assert result["RecipientName(*)"] == "Sample Customer"
    assert result["AmountToCollect(*)"] == 500

    page.selections["pathao_map_Phone (Billing)"] = "Alternate contact"
    render(page, "pathao_process_btn")
    assert page.session_state.pathao_res_df is None
    assert len(page.processed) == 2
    render(page, "confirm_columns")
    assert (
        page.session_state.pathao_res_df.iloc[0]["RecipientPhone(*)"] == "01812345678"
    )


@pytest.mark.parametrize(
    "missing", processing_tab.REQUIRED_UPLOAD_COLUMNS + ["Order ID"]
)
def test_missing_required_column_cannot_be_confirmed(page, orders, missing):
    page.upload = upload(orders.drop(columns=missing))
    render(page, "confirm_columns", "pathao_process_btn")
    assert not page.processed
    assert page.session_state.pathao_res_df is None
    assert page.session_state.pathao_mapping_confirmation is None
    assert any(name == "error" and missing in args[0] for name, args in page.messages)


def test_blank_phone_is_not_a_valid_mapping(page, orders):
    page.upload = upload(orders.assign(**{"Phone (Billing)": ""}))
    render(page, "confirm_columns")
    assert not page.processed
    assert page.session_state.pathao_res_df is None


def test_supported_export_aliases_map_before_processing(page, orders):
    aliases = {
        "Phone (Billing)": "Phone (Shipping)",
        "First Name (Shipping)": "Full Name (Shipping)",
        "Order ID": "Order Number",
        "Quantity": "Quantity(-Refund)",
        "Item Cost": "Item Price",
        "Order Total Amount": "Total Amount",
        "State Code (Shipping)": "Shipping State",
    }
    page.upload = upload(orders.rename(columns=aliases))
    render(page, "confirm_columns")
    assert len(page.processed) == 1
    result = page.session_state.pathao_res_df.iloc[0]
    assert result["MerchantOrderId"] == "1001"
    assert result["RecipientPhone(*)"] == "01712345678"
    assert result["AmountToCollect(*)"] == 500


def test_corrupt_replacement_file_clears_previous_result(page, orders, monkeypatch):
    page.upload = upload(orders)
    render(page, "confirm_columns")
    page.upload = upload(orders, "broken.csv")

    def fail_read(_file):
        raise ValueError("Malformed CSV")

    monkeypatch.setattr(processing_tab, "read_uploaded", fail_read)
    render(page)
    assert page.session_state.pathao_res_df is None
    assert page.session_state.pathao_preview_df is None


def test_processing_failure_clears_previous_result(page, orders, monkeypatch):
    page.upload = upload(orders)
    render(page, "confirm_columns")

    def fail_process(_df):
        raise ValueError("Invalid input")

    monkeypatch.setattr(processing_tab, "process_orders_dataframe", fail_process)
    render(page, "pathao_process_btn")
    assert page.session_state.pathao_res_df is None


def test_woocommerce_pull_processes_only_processing_orders(page, orders):
    page.source = shared.SOURCE_WOOCOM
    active = orders.assign(**{"Order Status": "processing"})
    cancelled = orders.assign(**{"Order Status": "cancelled", "Order ID": "2002"})
    page.session_state.wc_curr_df = pd.concat([active, cancelled], ignore_index=True)
    render(page, "pathao_live")
    assert len(page.processed) == 1
    assert page.session_state.pathao_res_df["MerchantOrderId"].tolist() == ["1001"]
    render(page, "pathao_process_btn")
    assert len(page.processed) == 2

    page.source = shared.SOURCE_UPLOAD
    render(page)
    assert page.session_state.pathao_res_df is None
    assert page.session_state.pathao_preview_df is None


@pytest.mark.parametrize("status_column", ["Order Status", "Status"])
def test_woocommerce_status_filter_trims_case_and_excludes_other_statuses(
    status_column,
):
    source = pd.DataFrame(
        {
            status_column: [
                "  Processing ",
                "PROCESSING",
                "pending",
                "on-hold",
                "cancelled",
                None,
            ],
            "Order ID": [1, 2, 3, 4, 5, 6],
        }
    )
    result, used_filter = shared._filter_processing_orders(source)
    assert used_filter
    assert result["Order ID"].tolist() == [1, 2]


def test_woocommerce_pull_without_status_fails_closed(page, orders):
    page.source = shared.SOURCE_WOOCOM
    page.session_state.wc_curr_df = orders
    render(page, "pathao_live")
    assert not page.processed
    assert page.session_state.pathao_preview_df is None
    assert page.session_state.pathao_res_df is None
    assert any(
        name == "error" and "missing its order status column" in args[0]
        for name, args in page.messages
    )


def test_failed_woocommerce_refresh_clears_previous_result(page, orders, monkeypatch):
    page.source = shared.SOURCE_WOOCOM
    page.session_state.wc_curr_df = orders.assign(**{"Order Status": "processing"})
    render(page, "pathao_live")

    def fail_fetch():
        raise ValueError("WooCommerce unavailable")

    monkeypatch.setattr(
        processing_tab, "_load_processing_orders_from_woocommerce", fail_fetch
    )
    render(page, "pathao_live")
    assert page.session_state.pathao_res_df is None
    assert page.session_state.pathao_preview_df is None


def test_reset_clears_mapping_and_uploaded_source_state(page, orders, monkeypatch):
    page.upload = upload(orders)
    render(page, "confirm_columns")
    page.session_state.pathao_up = page.upload
    page.session_state["pathao_map_Quantity"] = "Qty"

    def clear(keys):
        for key in keys:
            page.session_state.pop(key, None)

    monkeypatch.setattr(shared, "clear_state_keys", clear)
    shared._reset_pathao_state()
    assert "pathao_up" not in page.session_state
    assert "pathao_upload_fingerprint" not in page.session_state
    assert "pathao_mapping_confirmation" not in page.session_state
    assert "pathao_map_Quantity" not in page.session_state
    assert "pathao_res_df" not in page.session_state


def test_order_processor_accepts_full_name_directly():
    """When Full Name column is provided, processor takes it directly."""
    from src.processing.order_processor import clean_dataframe, process_orders_dataframe

    df = pd.DataFrame(
        [
            {
                "Order ID": "2001",
                "Phone (Billing)": "01711223344",
                "Full Name": "Rahim Uddin",
                "Address 1&2 (Shipping)": "Road 1, Dhanmondi, Dhaka",
                "Item Name": "Polo Shirt",
                "Quantity": 1,
                "Item Cost": 500,
                "Order Total Amount": 500,
            }
        ]
    )
    cleaned = clean_dataframe(df)
    assert cleaned["Full Name (Shipping)"].iloc[0] == "Rahim Uddin"

    result = process_orders_dataframe(df)
    assert result["RecipientName(*)"].iloc[0] == "Rahim Uddin"


def test_order_processor_merges_first_and_last_name():
    """When First Name and Last Name are provided without Full Name, processor merges them."""
    from src.processing.order_processor import clean_dataframe, process_orders_dataframe

    df = pd.DataFrame(
        [
            {
                "Order ID": "2002",
                "Phone (Billing)": "01811223344",
                "First Name": "Karim",
                "Last Name": "Chowdhury",
                "Address 1&2 (Shipping)": "Road 2, Gulshan, Dhaka",
                "Item Name": "Casual Shirt",
                "Quantity": 1,
                "Item Cost": 800,
                "Order Total Amount": 800,
            }
        ]
    )
    cleaned = clean_dataframe(df)
    assert cleaned["Full Name (Shipping)"].iloc[0] == "Karim Chowdhury"

    result = process_orders_dataframe(df)
    assert result["RecipientName(*)"].iloc[0] == "Karim Chowdhury"


def test_order_processor_prefers_full_name_over_first_last():
    """When both Full Name and First/Last name exist, processor takes Full Name."""
    from src.processing.order_processor import clean_dataframe, process_orders_dataframe

    df = pd.DataFrame(
        [
            {
                "Order ID": "2003",
                "Phone (Billing)": "01911223344",
                "Full Name": "Dr. Mohammad Ali",
                "First Name": "Mohammad",
                "Last Name": "Ali",
                "Address 1&2 (Shipping)": "Road 3, Banani, Dhaka",
                "Item Name": "Panjabi",
                "Quantity": 1,
                "Item Cost": 1200,
                "Order Total Amount": 1200,
            }
        ]
    )
    cleaned = clean_dataframe(df)
    assert cleaned["Full Name (Shipping)"].iloc[0] == "Dr. Mohammad Ali"

    result = process_orders_dataframe(df)
    assert result["RecipientName(*)"].iloc[0] == "Dr. Mohammad Ali"


def test_detect_and_map_columns_handles_full_or_first_last():
    """Verify _detect_and_map_columns accepts either Full Name or First + Last name."""
    # Case A: Full Name provided
    df_full = pd.DataFrame(
        {
            "Phone": ["01711111111"],
            "Customer Name": ["Tanvir Ahmed"],
            "Address": ["House 1, Uttara, Dhaka"],
            "Item": ["Shirt"],
            "Qty": [1],
            "Price": [500],
            "Total": [500],
            "Order #": ["9001"],
        }
    )
    mapped_full, mapping_full, missing_full = processing_tab._detect_and_map_columns(
        df_full
    )
    assert mapped_full["Full Name (Shipping)"].iloc[0] == "Tanvir Ahmed"
    assert mapped_full["First Name (Shipping)"].iloc[0] == "Tanvir Ahmed"
    assert "Full Name (Shipping)" not in missing_full

    # Case B: First Name and Last Name provided
    df_split = pd.DataFrame(
        {
            "Phone": ["01722222222"],
            "First Name": ["Sabbir"],
            "Last Name": ["Hossain"],
            "Address": ["House 2, Mirpur, Dhaka"],
            "Item": ["Pants"],
            "Qty": [1],
            "Price": [700],
            "Total": [700],
            "Order #": ["9002"],
        }
    )
    mapped_split, mapping_split, missing_split = processing_tab._detect_and_map_columns(
        df_split
    )
    assert mapped_split["Full Name (Shipping)"].iloc[0] == "Sabbir Hossain"
    assert "Full Name (Shipping)" not in missing_split
