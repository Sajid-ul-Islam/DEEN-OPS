"""Abstract Base Courier Client Interface for DEEN-OPS.

Defines the contract for multi-courier integrations (Pathao, Steadfast, RedX).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseCourierClient(ABC):
    """Abstract interface defining required courier client operations."""

    @abstractmethod
    def create_order(
        self,
        order_id: str | int,
        recipient_name: str,
        recipient_phone: str,
        recipient_address: str,
        amount_to_collect: float | int,
        item_description: str = "",
        special_instruction: str = "",
        store_id: Optional[int | str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a single parcel delivery order."""
        pass

    @abstractmethod
    def get_order_status(
        self,
        consignment_id: Optional[str] = None,
        order_id: Optional[str | int] = None,
    ) -> dict[str, Any]:
        """Retrieve tracking status and delivery history for a consignment."""
        pass

    @abstractmethod
    def get_stores(self) -> list[dict[str, Any]]:
        """Retrieve list of registered merchant pickup locations/warehouses."""
        pass
