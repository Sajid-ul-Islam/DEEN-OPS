import pandas as pd
import pytest
from src.processing.forecasting import PredictiveIntelligence

def test_predictive_intelligence_forecast_valid():
    """Test that the forecast function returns valid predictions for a series."""
    series = pd.Series([100, 110, 120, 130, 140])
    results, standings = PredictiveIntelligence.forecast(series, steps=3)
    
    assert results is not None
    assert not standings.empty
    assert len(results) == 3
    assert "forecast" in results[0]
    assert len(results[0]["forecast"]) == 3

def test_predictive_intelligence_insufficient_data():
    """Test that the forecast function handles empty/insufficient data gracefully."""
    series = pd.Series([100, 110])
    results, msg = PredictiveIntelligence.forecast(series, steps=3)
    
    assert results is None
    assert msg == "Insufficient Evidence"