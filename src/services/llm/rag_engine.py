import duckdb
import os

class RAGEngine:
    """
    RAG Engine utilizing DuckDB's native array functionalities for 
    high-performance Vector Similarity Search on disk without blowing up RAM.
    """
    def __init__(self, cache_dir="BackEnd/cache"):
        self.cache_dir = cache_dir
        self.db_path = os.path.join(cache_dir, "operations.db")
        self.conn = None
        
        self.load_index()

    def load_index(self):
        """Connects to the DuckDB snapshot."""
        if os.path.exists(self.db_path):
            # Connect in read-only mode to prevent locking issues with Streamlit
            self.conn = duckdb.connect(self.db_path, read_only=True)
            print("Connected to DuckDB Vector Store.")
        else:
            print("No DuckDB snapshot found.")

    def search(self, query_vector, top_k=5):
        """
        Native DuckDB Vector Similarity Search using array_cosine_similarity.
        """
        if self.conn is None:
            return []
            
        # Ensure the query vector is formatted as a SQL list
        query_list_str = str(list(query_vector))
        
        try:
            # DuckDB 1.0.0+ natively supports array_cosine_similarity on FLOAT[] arrays
            query = f"""
                SELECT "Order ID", "Item Name", 
                       list_cosine_similarity(embedding_vector, {query_list_str}) as sim_score
                FROM orders
                ORDER BY sim_score DESC
                LIMIT {top_k};
            """
            result_df = self.conn.execute(query).df()
            return result_df.to_dict('records')
        except Exception as e:
            print(f"DuckDB Vector Search Error: {e}")
            return []

