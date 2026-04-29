"""Filter orchestration for the Sales Ingestion dashboard mode."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from src.config.constants import COMMON_CATS
from src.processing.categorization import get_category_for_sales, get_sub_category_for_sales
from src.processing.data_processing import prepare_granular_data, aggregate_data
from src.services.woocommerce.client import load_from_woocommerce
from src.utils.product import get_base_product_name, get_size_from_name
from src.utils.snapshots import save_sales_snapshot


@st.cache_data(ttl=3600)
def _get_category(name: str) -> str:
    return get_category_for_sales(name)


def render_ingestion_filters(
    granular_df: pd.DataFrame | None,
    dummy_mapping: dict,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, dict | None, pd.DataFrame | None]:
    """Render the high-density filter intelligence bar for Sales Ingestion mode.

    Handles date range selection (with auto-fetch), hierarchical
    Category / Sub-Category multiselect, item filter, size filter, and the
    manual sync button.

    Args:
        granular_df: Granular row-level DataFrame (may be None).
        dummy_mapping: Standard column mapping for re-aggregation.

    Returns:
        Tuple of (drill, summ, top, basket, active_df). Any may be None if no
        data is available.
    """
    is_manual = st.session_state.get("manual_tab_active", False)
    drill, summ, top, basket = None, None, None, None
    active_df = granular_df

    if granular_df is None and not is_manual:
        return drill, summ, top, basket, active_df

    with st.expander("\U0001f6e0\ufe0f Filter Intelligence", expanded=True):
        working_df = granular_df.copy() if granular_df is not None else pd.DataFrame(
            columns=["Category", "Product Name", "Size", "Date"]
        )
        if not working_df.empty:
            if "Category" not in working_df.columns or "Sub-Category" not in working_df.columns or "Clean_Product" not in working_df.columns:
                working_df, _ = prepare_granular_data(working_df, dummy_mapping)

            # Clean trailing spaces from string columns to prevent filter mismatches
            for col in ["Category", "Sub-Category", "Filter_Identity", "Size"]:
                if col in working_df.columns:
                    try:
                        working_df[col] = working_df[col].str.strip()
                    except AttributeError:
                        pass

        c1, c2, c3, c4, c5 = st.columns([1.2, 1.2, 1, 1, 0.3])

        with c1:
            last_range = st.session_state.get("last_synced_range")
            sel_range = st.date_input(
                "Select Date Range",
                value=st.session_state.get(
                    "ingest_range",
                    ((datetime.now() - timedelta(days=30)).date(), datetime.now().date()),
                ),
                min_value=datetime(2021, 8, 31).date(),
                max_value=datetime.now().date(),
                key="ingest_range",
            )

            if isinstance(sel_range, tuple) and len(sel_range) == 2:
                if sel_range != last_range:
                    st.session_state["last_synced_range"] = sel_range
                    s_d, e_d = sel_range
                    st.session_state["wc_sync_mode"] = "Custom Range"
                    st.session_state["wc_sync_start_date"] = s_d
                    st.session_state["wc_sync_start_time"] = datetime.strptime("00:00", "%H:%M").time()
                    st.session_state["wc_sync_end_date"] = e_d
                    st.session_state["wc_sync_end_time"] = datetime.strptime("23:59", "%H:%M").time()

                    with st.spinner(f"\U0001f680 Syncing {s_d} to {e_d}..."):
                        try:
                            wc_res = load_from_woocommerce()
                            df_res = wc_res["df_to_return"]
                            if not df_res.empty:
                                st.session_state.manual_df = df_res
                                st.session_state.manual_source_name = wc_res["sync_desc"]
                                save_sales_snapshot(df_res)
                                st.toast("\u2705 Auto-Sync Complete!")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Auto-sync failed: {e}")

            if not working_df.empty and isinstance(sel_range, tuple) and len(sel_range) == 2:
                sd, ed = pd.to_datetime(sel_range[0]), pd.to_datetime(sel_range[1])
                working_df = working_df[(working_df["Date"] >= sd) & (working_df["Date"] <= (ed + timedelta(days=1)))]

        active_df = working_df

        with c2:
            unified_options = COMMON_CATS

            sel_unified = st.multiselect(
                "Select Category / Fit",
                unified_options,
                placeholder="All Categories",
                key="fallback_filter_unified",
            )

            if not working_df.empty and sel_unified:
                mask = pd.Series(False, index=working_df.index)
                for opt in sel_unified:
                    if "  \u21b3 " in opt:
                        sub_name = opt.replace("  \u21b3 ", "")
                        mask |= (working_df["Sub-Category"] == sub_name)
                    else:
                        mask |= (working_df["Category"] == opt)
                working_df = working_df[mask]

        with c3:
            all_prods = sorted(working_df["Filter_Identity"].unique().tolist()) if not working_df.empty else []
            sel_prods = st.multiselect("Select Item", all_prods, placeholder="All Products", key="fallback_filter_prod")
            if not working_df.empty:
                working_df = working_df[working_df["Filter_Identity"].isin(sel_prods)] if sel_prods else working_df

        with c4:
            all_sizes = sorted(working_df["Size"].unique().tolist()) if not working_df.empty and "Size" in working_df.columns else []
            sel_sizes = st.multiselect("Select Size", all_sizes, placeholder="All Sizes", key="fallback_filter_size")
            if not working_df.empty and "Size" in working_df.columns:
                working_df = working_df[working_df["Size"].isin(sel_sizes)] if sel_sizes else working_df

        with c5:
            st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True)
            if st.button("\U0001f504", use_container_width=True, type="primary", help="Sync Fresh Data"):
                if isinstance(sel_range, tuple) and len(sel_range) == 2:
                    s_d, e_d = sel_range
                    st.session_state["wc_sync_mode"] = "Custom Range"
                    st.session_state["wc_sync_start_date"] = s_d
                    st.session_state["wc_sync_start_time"] = datetime.strptime("00:00", "%H:%M").time()
                    st.session_state["wc_sync_end_date"] = e_d
                    st.session_state["wc_sync_end_time"] = datetime.strptime("23:59", "%H:%M").time()

                    try:
                        with st.spinner("\U0001f504 Fetching..."):
                            wc_res = load_from_woocommerce()
                            df_res = wc_res["df_to_return"]
                            if not df_res.empty:
                                if sel_unified:
                                    df_res["_TmpCat"] = df_res["Item Name"].apply(_get_category)
                                    df_res["_TmpSub"] = df_res.apply(
                                        lambda r: get_sub_category_for_sales(r["Item Name"], r["_TmpCat"]), axis=1
                                    )
                                    mask = pd.Series(False, index=df_res.index)
                                    for opt in sel_unified:
                                        if "  \u21b3 " in opt:
                                            sub_name = opt.replace("  \u21b3 ", "")
                                            mask |= (df_res["_TmpSub"] == sub_name)
                                        else:
                                            mask |= (df_res["_TmpCat"] == opt)
                                    df_res = df_res[mask]
                                    if "_TmpCat" in df_res.columns:
                                        df_res = df_res.drop(columns=["_TmpCat"])
                                    if "_TmpSub" in df_res.columns:
                                        df_res = df_res.drop(columns=["_TmpSub"])

                                if sel_prods:
                                    df_res["_TmpIdent"] = df_res.apply(
                                        lambda r: f"{get_base_product_name(r['Item Name'])} [{r['SKU']}]", axis=1
                                    )
                                    df_res = df_res[df_res["_TmpIdent"].isin(sel_prods)].drop(columns=["_TmpIdent"])
                                if sel_sizes:
                                    df_res["_TmpSize"] = df_res["Item Name"].apply(get_size_from_name)
                                    df_res = df_res[df_res["_TmpSize"].isin(sel_sizes)].drop(columns=["_TmpSize"])

                                if not df_res.empty:
                                    st.session_state.manual_df = df_res
                                    st.session_state.manual_source_name = wc_res["sync_desc"]
                                    save_sales_snapshot(df_res)
                                    st.toast("\u2705 API Sync Complete!")
                                    st.rerun()
                                else:
                                    st.warning("No data found for the selected Category/Item/Size combination.")
                            else:
                                st.warning("No data found for the selected range.")
                    except Exception as e:
                        st.error(f"Ingestion failed: {e}")
                else:
                    st.error("Please select both a start and end date.")

        active_df = working_df
        if not working_df.empty:
            drill, summ, top, basket = aggregate_data(working_df, dummy_mapping)

    return drill, summ, top, basket, active_df
