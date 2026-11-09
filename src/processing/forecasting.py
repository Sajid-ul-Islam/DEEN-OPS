"""Lightweight forecasting engine using mathematical and statistical baselines.

Provides deterministic multi-model tournament forecasting using pure numpy and pandas,
eliminating heavy C-extension dependencies (xgboost, scikit-learn, statsmodels).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class PredictiveIntelligence:
    """Universal Forecasting Suite: Multi-Model Tournament Engine."""

    @staticmethod
    def forecast(
        series: pd.Series, steps: int = 7
    ) -> tuple[list[dict] | None, pd.DataFrame | str]:
        """Forecast future values using competitive tournament across baseline models.

        Args:
            series: Historical time series data.
            steps: Number of future time steps to forecast.

        Returns:
            Tuple of (list of top model result dicts, standings DataFrame)
            or (None, "Insufficient Evidence") if series length < 3.
        """
        if len(series) < 3:
            return None, "Insufficient Evidence"

        y = np.asarray(series.values, dtype=float)
        x = np.arange(len(y))
        f_x = np.arange(len(y), len(y) + steps)

        models: dict[str, dict] = {}

        # 1. Linear Trend Baseline
        try:
            p_linear = np.polyfit(x, y, 1)
            models["Baseline: Linear Poly"] = {
                "pred": np.polyval(p_linear, x),
                "future": np.polyval(p_linear, f_x),
            }
        except Exception:
            pass

        # 2. Quadratic Trend Baseline
        if len(y) >= 4:
            try:
                p_quad = np.polyfit(x, y, 2)
                models["Baseline: Quadratic Poly"] = {
                    "pred": np.polyval(p_quad, x),
                    "future": np.polyval(p_quad, f_x),
                }
            except Exception:
                pass

        # 3. Exponential Moving Average
        try:
            ema = pd.Series(y).ewm(alpha=0.3, adjust=False).mean().values
            models["Auto: Exponential Smoothing"] = {
                "pred": ema,
                "future": np.full(steps, ema[-1]),
            }
        except Exception:
            pass

        # 4. Moving Average (Rolling Window)
        try:
            window = max(2, min(5, len(y) // 2))
            rolling = pd.Series(y).rolling(window, min_periods=1).mean().values
            models["Baseline: Rolling Mean"] = {
                "pred": rolling,
                "future": np.full(steps, rolling[-1]),
            }
        except Exception:
            pass

        # Fallback if no model fitted
        if not models:
            models["Baseline: Naive Last"] = {
                "pred": np.full(len(y), y[-1]),
                "future": np.full(steps, y[-1]),
            }

        # Tournament Standings: Selection via MAE
        standings = []
        for name, m in models.items():
            error = float(np.nanmean(np.abs(y - m["pred"])))
            standings.append({"model": name, "error": error})

        standings_df = (
            pd.DataFrame(standings).sort_values("error").reset_index(drop=True)
        )
        top_3 = standings_df.head(3)

        results = []
        for _idx, row in top_3.iterrows():
            m_name = str(row["model"])
            best_m = models[m_name]
            v = best_m["future"]
            # Ensure no negative predictions and convert numpy array to list
            v_clean = np.maximum(v, 0).tolist()
            results.append({"name": m_name, "forecast": v_clean, "error": row["error"]})

        return results, standings_df
