import os
import pandas as pd
import duckdb
import numpy as np
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

CACHE_DIR = "BackEnd/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def crunch_heavy_calculations():
    print(f"[{datetime.now()}] Crunching heavy calculations...")
    
    # Mock some data as we simulate the heavy calculation part
    df = pd.DataFrame({
        "Order ID": range(1, 101),
        "Item Name": [f"Product {i}" for i in range(1, 101)],
        "Amount": np.random.rand(100) * 100
    })

    print(f"[{datetime.now()}] Generating .parquet files...")
    df.to_parquet(f"{CACHE_DIR}/orders_snapshot.parquet")
    
    print(f"[{datetime.now()}] Building .db file with DuckDB...")
    conn = duckdb.connect(f"{CACHE_DIR}/operations.db")
    conn.execute("CREATE TABLE IF NOT EXISTS orders AS SELECT * FROM df")
    conn.close()

    print(f"[{datetime.now()}] Generating .npy embeddings...")
    # Mock embeddings generation for text columns (128 dimensions)
    embeddings = np.random.rand(len(df), 128).astype(np.float32)
    np.save(f"{CACHE_DIR}/vector_index.npy", embeddings)
    
    print(f"[{datetime.now()}] Snapshot generation complete.")

if __name__ == "__main__":
    crunch_heavy_calculations()
