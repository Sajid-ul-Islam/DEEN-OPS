import numpy as np
import os

class RAGEngine:
    def __init__(self, cache_dir="BackEnd/cache"):
        self.cache_dir = cache_dir
        self.index_path = os.path.join(cache_dir, "vector_index.npy")
        self.embeddings = None
        
        self.load_index()

    def load_index(self):
        """Loads the pre-computed NumPy embeddings instantly."""
        if os.path.exists(self.index_path):
            self.embeddings = np.load(self.index_path)
            print(f"Loaded {len(self.embeddings)} vectors from local snapshot.")
        else:
            print("No vector index found in snapshot.")

    def search(self, query_vector, top_k=5):
        """
        Basic linear scan using cosine similarity.
        For larger datasets, optimize using FAISS (HNSW) or Annoy.
        """
        if self.embeddings is None:
            return []
            
        # Cosine similarity optimization
        norm_emb = np.linalg.norm(self.embeddings, axis=1)
        norm_query = np.linalg.norm(query_vector)
        
        scores = np.dot(self.embeddings, query_vector) / (norm_emb * norm_query)
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        return top_indices
