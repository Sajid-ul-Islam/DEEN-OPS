import pandas as pd
import numpy as np


class PredictiveIntelligence:
    """
    Universal Forecasting Suite: Multi-Family Tournament Engine.
    
    Integrates real machine learning models via scikit-learn, xgboost, and 
    statsmodels. Degrades gracefully to mathematical baselines if libraries 
    are not installed.
    """
    @staticmethod
    def forecast(series: pd.Series, steps: int = 7):
        if len(series) < 3:
            return None, "Insufficient Evidence"

        y = series.values
        x = np.arange(len(y))
        X_train = x.reshape(-1, 1)
        f_x = np.arange(len(y), len(y) + steps).reshape(-1, 1)

        # MODEL REPOSITORY: Multi-Family Tournament (v12.5 Industrial Suite)
        models = {}

        # 1. XGBoost
        try:
            from xgboost import XGBRegressor
            xgb = XGBRegressor(n_estimators=50, max_depth=3, random_state=42)
            xgb.fit(X_train, y)
            models["Tree: XGBoost"] = {"pred": xgb.predict(X_train), "model": xgb, "type": "sklearn"}
        except ImportError:
            pass

        # 2. Random Forest
        try:
            from sklearn.ensemble import RandomForestRegressor
            rf = RandomForestRegressor(n_estimators=50, random_state=42)
            rf.fit(X_train, y)
            models["Tree: Random Forest"] = {"pred": rf.predict(X_train), "model": rf, "type": "sklearn"}
        except ImportError:
            pass

        # 3. ARIMA (Statsmodels)
        try:
            from statsmodels.tsa.arima.model import ARIMA
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                arima = ARIMA(y, order=(1, 1, 0)).fit()
                models["Auto: ARIMA"] = {"pred": arima.predict(start=0, end=len(y)-1), "model": arima, "type": "statsmodels_forecast"}
        except Exception:
            pass
            
        # 4. Exponential Smoothing (Holt-Winters Replacement for Prophet/TBATS)
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                hw = ExponentialSmoothing(y, trend='add', seasonal=None, initialization_method="estimated").fit()
                models["Auto: Exponential Smoothing"] = {"pred": hw.fittedvalues, "model": hw, "type": "statsmodels_forecast"}
        except Exception:
            pass

        # Fallback Baseline (Poly Trend)
        if not models:
            p_base = np.polyfit(x, y, 1)
            models["Baseline: Linear Poly"] = {"pred": np.polyval(p_base, x), "fit": p_base, "type": "poly"}

        # TOURNAMENT STANDINGS: Selection via MAE
        standings = []
        for name, m in models.items():
            error = np.nanmean(np.abs(y - m["pred"]))
            standings.append({"model": name, "error": error})

        standings_df = pd.DataFrame(standings).sort_values("error")
        top_3 = standings_df.head(3)

        results = []
        for idx, row in top_3.iterrows():
            m_name = row["model"]
            best_m = models[m_name]

            if best_m["type"] == "sklearn":
                v = best_m["model"].predict(f_x)
            elif best_m["type"] == "statsmodels_forecast":
                v = best_m["model"].forecast(steps)
            elif best_m["type"] == "poly":
                v = np.polyval(best_m["fit"], f_x.flatten())
            else:
                v = np.full(steps, y[-1])

            # Ensure no negative predictions and convert numpy arrays to list
            v_clean = np.maximum(v, 0).tolist()
            results.append({"name": m_name, "forecast": v_clean, "error": row["error"]})

        return results, standings_df
