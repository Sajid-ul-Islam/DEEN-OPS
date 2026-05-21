import os
import pandas as pd
import duckdb
import numpy as np
from datetime import datetime
import warnings
from src.services.woocommerce.client import load_from_woocommerce

warnings.filterwarnings('ignore')

CACHE_DIR = "BackEnd/cache"
DB_PATH = f"{CACHE_DIR}/operations.db"
os.makedirs(CACHE_DIR, exist_ok=True)

def crunch_heavy_calculations():
    print(f"[{datetime.now()}] Starting incremental snapshot sync...")
    
    # 1. Connect to DuckDB and find latest Order ID for incremental sync
    conn = duckdb.connect(DB_PATH)
    latest_order_id = 0
    
    # Check if table exists
    tables = conn.execute("SHOW TABLES").fetchall()
    table_exists = any(t[0] == "orders" for t in tables)
    
    if table_exists:
        try:
            latest = conn.execute("SELECT MAX(\"Order ID\") FROM orders").fetchone()
            if latest and latest[0]:
                latest_order_id = int(latest[0])
                print(f"[{datetime.now()}] Found existing snapshot. Latest Order ID: {latest_order_id}")
        except Exception as e:
            print(f"[{datetime.now()}] Error reading latest ID: {e}")

    # 2. Fetch live data (simulated incremental fetch based on latest_order_id)
    print(f"[{datetime.now()}] Fetching new records...")
    try:
        import streamlit as st
        if not hasattr(st, "session_state"):
            st.session_state = {}
        st.session_state.wc_sync_mode = "Operational Cycle"
        
        results = load_from_woocommerce()
        df_new = results.get("df_to_return", pd.DataFrame())
        
        if not df_new.empty:
            # Incremental logic: filter only new orders
            df_new = df_new[df_new["Order ID"] > latest_order_id].copy()
    except Exception as e:
        print(f"[{datetime.now()}] WooCommerce fetch failed, generating dummy data...")
        # Mock incremental data
        start_id = latest_order_id + 1
        df_new = pd.DataFrame({
            "Order ID": range(start_id, start_id + 50),
            "Item Name": [f"Product {i}" for i in range(start_id, start_id + 50)],
            "Amount": np.random.rand(50) * 100
        })

    if df_new.empty:
        print(f"[{datetime.now()}] No new records to sync. Snapshot is up to date.")
        conn.close()
        return

    print(f"[{datetime.now()}] Found {len(df_new)} new records to process.")

    # 3. Generate Embeddings (Mocked 128-dim vectors)
    print(f"[{datetime.now()}] Generating embeddings for DuckDB VSS...")
    embeddings = np.random.rand(len(df_new), 128).astype(np.float32)
    # DuckDB arrays need to be passed as list of lists
    df_new["embedding_vector"] = list(embeddings)

    # 4. Insert or Append to DuckDB
    print(f"[{datetime.now()}] Upserting to DuckDB...")
    if not table_exists:
        # Create table with array type for vectors
        conn.execute("CREATE TABLE orders AS SELECT * FROM df_new")
    else:
        # Append new records
        conn.execute("INSERT INTO orders SELECT * FROM df_new")

    # Save to Parquet as a backup/alternative
    print(f"[{datetime.now()}] Exporting full snapshot to Parquet...")
    conn.execute(f"COPY orders TO '{CACHE_DIR}/orders_snapshot.parquet' (FORMAT PARQUET)")
    
    conn.close()
    
    # We no longer need the separate .npy file!
    npy_path = f"{CACHE_DIR}/vector_index.npy"
    if os.path.exists(npy_path):
        os.remove(npy_path)
        print(f"[{datetime.now()}] Cleaned up legacy .npy vector index.")

    print(f"[{datetime.now()}] Incremental snapshot generation complete!")

if __name__ == "__main__":
    crunch_heavy_calculations()

