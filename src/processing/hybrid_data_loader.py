import os
import pandas as pd
import duckdb
import polars as pl

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
        """Instantly load local files with Polars for maximum speed."""
        df = None
        if os.path.exists(self.parquet_path):
            df = pl.read_parquet(self.parquet_path).to_pandas()
            print(f"Instantly loaded {len(df)} rows from Parquet via Polars Engine.")
            
        # Optional: Setup DuckDB connection for fast SQL querying later
        if os.path.exists(self.db_path):
            print("DuckDB local snapshot detected and ready.")
            
        return df

    def get_db_connection(self):
        """Returns a read-only DuckDB connection to the local snapshot."""
        if os.path.exists(self.db_path):
            return duckdb.connect(self.db_path, read_only=True)
        return None

    def query_sql(self, sql_query: str) -> pd.DataFrame | None:
        """Execute a DuckDB SQL query directly against the Parquet snapshot.
        Note: Use 'sales_data' as the table name in your SQL queries.
        """
        if not os.path.exists(self.parquet_path):
            print("No parquet snapshot found for querying.")
            return None
            
        try:
            # Create an in-memory connection
            conn = duckdb.connect(':memory:')
            # Create a view of the parquet file for easy querying
            conn.execute(f"CREATE VIEW sales_data AS SELECT * FROM read_parquet('{self.parquet_path}')")
            
            # Run the user's query
            result_df = conn.execute(sql_query).df()
            conn.close()
            return result_df
        except Exception as e:
            print(f"DuckDB Query Error: {e}")
            return None
