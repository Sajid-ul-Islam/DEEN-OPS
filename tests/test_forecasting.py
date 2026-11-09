"""Unit tests for PredictiveIntelligence baseline tournament forecasting."""

import pandas as pd
import pytest

from src.processing.forecasting import PredictiveIntelligence


def test_predictive_intelligence_insufficient_data():
    s = pd.Series([100.0, 150.0])
    results, msg = PredictiveIntelligence.forecast(s, steps=3)
    assert results is None
    assert msg == "Insufficient Evidence"


def test_predictive_intelligence_forecast_success():
    s = pd.Series([100.0, 120.0, 140.0, 160.0, 180.0])
    results, standings = PredictiveIntelligence.forecast(s, steps=3)

    assert results is not None
    assert len(results) > 0
    assert isinstance(standings, pd.DataFrame)
    assert not standings.empty
    assert "model" in standings.columns
    assert "error" in standings.columns

    # First result has valid forecast list with length == steps
    top_result = results[0]
    assert "name" in top_result
    assert "forecast" in top_result
    assert len(top_result["forecast"]) == 3
    # Check no negative predictions
    assert all(val >= 0 for val in top_result["forecast"])


def test_predictive_intelligence_constant_series():
    s = pd.Series([50.0, 50.0, 50.0, 50.0])
    results, standings = PredictiveIntelligence.forecast(s, steps=2)

    assert results is not None
    top_pred = results[0]["forecast"]
    assert len(top_pred) == 2
    assert pytest.approx(top_pred[0], abs=1e-2) == 50.0
