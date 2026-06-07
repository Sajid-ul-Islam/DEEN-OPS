import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class NeuralBrain:
    """Advanced NLP & ML logic for Data Pilot grounding."""
    
    @staticmethod
    def detect_anomalies(df: pd.DataFrame, column: str = "Total Amount") -> pd.DataFrame:
        """Vectorized ML-based anomaly detection using Z-Score."""
        if df is None or df.empty or column not in df.columns or "Date" not in df.columns:
            return pd.DataFrame()
            
        # Direct groupby without copying the entire dataframe
        dates = pd.to_datetime(df['Date']).dt.date
        series = df.groupby(dates)[column].sum()
        
        if len(series) < 5:
            return pd.DataFrame()
            
        mean = series.mean()
        std = series.std()
        if std == 0: 
            std = 1
        
        z_scores = (series - mean) / std
        anomalies_mask = np.abs(z_scores) > 1.5
        
        if not anomalies_mask.any():
            return pd.DataFrame()
            
        anomalies = series[anomalies_mask]
        anomaly_scores = np.abs(z_scores[anomalies_mask])
        
        # Vectorized dataframe creation
        return pd.DataFrame({
            "date": anomalies.index,
            "value": anomalies.values,
            "type": np.where(anomalies.values > mean, "High", "Low"),
            "score": anomaly_scores.values
        })

    @staticmethod
    def semantic_query_intent(query: str) -> dict:
        """Enhanced NLP Intent Router."""
        q = query.lower()
        
        # 1. Forecasting Intent
        if any(w in q for w in ["forecast", "predict", "next week", "future", "outlook"]):
            return {"type": "ml_forecast", "target": "sales" if "sale" in q or "rev" in q else "orders"}
            
        # 2. Anomaly/Audit Intent
        if any(w in q for w in ["anomaly", "weird", "unusual", "audit", "spike", "drop"]):
            return {"type": "ml_anomaly", "target": "general"}
            
        # 3. Fulfillment Intent
        if any(w in q for w in ["when", "stock out", "out of stock", "reorder", "velocity"]):
            return {"type": "fulfillment_prediction", "target": "inventory"}
            
        return {"type": "llm_general", "target": "context"}
