import pytest
import sys
from unittest.mock import MagicMock

@pytest.fixture(scope="session", autouse=True)
def mock_streamlit_components():
    """Mock streamlit components to prevent import errors in tests."""
    # Create mock for streamlit.components.v1
    mock_components = MagicMock()
    mock_components.html = MagicMock()
    
    # Patch before importing src modules
    sys.modules['streamlit.components.v1'] = mock_components
    
    yield