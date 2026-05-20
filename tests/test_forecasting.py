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

def test_predictive_intelligence_selects_xgboost():
    """Test that XGBoost is used when available and produces valid results."""
    try:
        import xgboost
    except ImportError:
        pytest.skip("xgboost not installed, skipping test.")
        
    # Generate a simple linear trend that XGBoost should easily fit
    series = pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    
    results, standings = PredictiveIntelligence.forecast(series, steps=5)
    
    assert results is not None
    assert len(results) <= 3  # Top 3 models returned
    
    # Check if XGBoost made it into the tournament standings
    assert "Tree: XGBoost" in standings["model"].values
    
    # Verify the XGBoost result payload specifically
    xgb_result = next((r for r in results if r["name"] == "Tree: XGBoost"), None)
    if xgb_result:
        assert len(xgb_result["forecast"]) == 5