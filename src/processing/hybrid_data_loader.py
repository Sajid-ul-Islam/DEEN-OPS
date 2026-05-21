import os
import pandas as pd
import duckdb

class HybridDataLoader:
    """
    Detects and instantly loads offline data snapshots if available, 
    allowing Cloud App to boot up extremely fast without crunching data.
    """
    def __init__(self, cache_dir="BackEnd/cache"):
        self.cache_dir = cache_dir
        self.parquet_path = os.path.join(cache_dir, "orders_snapshot.parquet")
        self.db_path = os.path.join(cache_dir, "operations.db")
        
    def load_fast(self):
        """Instantly load local files."""
        df = None
        if os.path.exists(self.parquet_path):
            df = pd.read_parquet(self.parquet_path)
            print(f"Instantly loaded {len(df)} rows from Parquet.")
            
        # Optional: Setup DuckDB connection for fast SQL querying later
        if os.path.exists(self.db_path):
            print("DuckDB local snapshot detected and ready.")
            
        return df

    def get_db_connection(self):
        """Returns a read-only DuckDB connection to the local snapshot."""
        if os.path.exists(self.db_path):
            return duckdb.connect(self.db_path, read_only=True)
        return None
