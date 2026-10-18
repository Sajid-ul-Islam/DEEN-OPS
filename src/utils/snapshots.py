import os

import pandas as pd

from src.config.constants import RESOURCES_DIR, SALES_SNAPSHOT_PATH


def load_sales_snapshot():
    """Load sales snapshot from local CSV."""
    paths = [SALES_SNAPSHOT_PATH, os.path.join(RESOURCES_DIR, "sales_report.csv")]
    for path in paths:
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                return df
            except Exception:
                continue
    return None


def save_sales_snapshot(df):
    """Save sales snapshot to local CSV."""
    try:
        os.makedirs(RESOURCES_DIR, exist_ok=True)
        df.to_csv(SALES_SNAPSHOT_PATH, index=False)
    except Exception:
        pass
