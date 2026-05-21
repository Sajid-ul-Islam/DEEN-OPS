import pandas as pd
import polars as pl
from typing import Dict, Optional
import urllib.parse
import re


class WhatsAppOrderProcessor:
    def __init__(self, config: Optional[Dict] = None):
        """Initialize with configuration for column mappings."""
        self.config = config or {
            "phone_col": "Phone (Billing)",
            "name_col": "Full Name (Billing)",
            "order_id_col": "Order ID",
            "product_col": "Product Name (main)",
            "sku_col": "SKU",
            "quantity_col": "Quantity",
            "price_col": "Item cost",
            "payment_method_col": "Payment Method Title",
            "address_col": "Address 1&2 (Billing)",
            "order_total_col": "Order Total Amount",
            "city_col": "City, State, Zip (Billing)",
        }

    def clean_phone_number(self, phone: str) -> str:
        """Clean and format phone number for WhatsApp."""
        if pd.isna(phone):
            return ""
        phone = "".join(filter(str.isdigit, str(phone)))
        if phone.startswith("0"):
            return "0" + phone[1:]
        elif not phone.startswith(("88", "+88")):
            return "0" + phone
        return phone

    def format_text(self, text: str) -> str:
        """Standardize text formatting (capitalization, spacing)."""
        if not isinstance(text, str) or not text.strip():
            return ""

        # Helper to capitalize words properly
        def capitalize_word(w):
            if "-" in w:
                return "-".join(p.capitalize() for p in w.split("-"))
            if "'" in w:
                return "'".join(p.capitalize() for p in w.split("'"))
            if "." in w and not w.endswith("."):
                return ". ".join(p.capitalize() for p in w.split("."))
            return w.capitalize()

        # Handle comma-separated parts (addresses)
        if "," in text:
            parts = [p.strip() for p in text.split(",")]
            formatted_parts = []
            for part in parts:
                if not part:
                    continue
                formatted_parts.append(
                    " ".join(capitalize_word(w) for w in part.split())
                )
            return ", ".join(formatted_parts)

        # Handle regular text
        text = re.sub(r"\.(\w)", r". \1", text.strip())
        return " ".join(capitalize_word(w) for w in text.split())

    def format_name(self, name):
        return self.format_text(str(name)) if pd.notna(name) else ""

    def format_address(self, *address_parts):
        parts = [
            self.format_text(str(p))
            for p in address_parts
            if pd.notna(p) and str(p).strip()
        ]
        return "\n".join(parts)

    def detect_gender_salutation(self, name: str) -> str:
        """Detect gender from name for appropriate salutation."""
        if not isinstance(name, str):
            return "Sir"

        name_lower = name.lower()
        female_indicators = {
            "ms",
            "miss",
            "mrs",
            "mst",
            "begum",
            "khatun",
            "akter",
            "parvin",
            "sultana",
            "jahan",
            "bibi",
            "rani",
            "devi",
            "nahar",
            "ferdous",
            "ara",
            "banu",
            "fatema",
            "aisha",
            "khadija",
            "nusrat",
            "farhana",
            "sadia",
            "jannatul",
            "sumaiya",
            "tanjina",
            "fariha",
            "sharmin",
            "nasrin",
            "salma",
            "shirin",
            "rumana",
            "sabina",
            "moumita",
        }

        # Check parts for indicators
        parts = name_lower.replace(".", " ").split()
        if any(part in female_indicators for part in parts):
            return "Madam"
        return "Sir"

    def _find_best_column(self, df_cols, target_keys, default):
        """Find the best matching column from a list of keys."""
        cols_lower = [str(c).lower().strip() for c in df_cols]
        for key in target_keys:
            key_l = key.lower()
            if key_l in cols_lower:
                return df_cols[cols_lower.index(key_l)]
        # Try partial match fallback
        for key in target_keys:
            key_l = key.lower()
            for i, c_l in enumerate(cols_lower):
                if key_l in c_l:
                    return df_cols[i]
        return default

    def process_orders(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process raw dataframe into grouped orders with fuzzy matching."""
        df.columns = [str(col).strip() for col in df.columns]

        # Fuzzy Match Configuration Columns
        mapping = {
            "phone_col": (
                ["phone", "mobile", "contact", "billing phone"],
                "Phone (Billing)",
            ),
            "name_col": (
                ["full name", "billing name", "name", "first name", "customer"],
                "Full Name (Billing)",
            ),
            "order_id_col": (["order id", "order #", "id", "order number"], "Order ID"),
            "product_col": (
                ["product name", "item name", "product", "item"],
                "Product Name (main)",
            ),
            "sku_col": (["sku", "item sku", "code"], "SKU"),
            "quantity_col": (["quantity", "qty", "item qty"], "Quantity"),
            "price_col": (["item cost", "price", "cost"], "Item cost"),
            "payment_method_col": (
                ["payment method", "gateway"],
                "Payment Method Title",
            ),
            "address_col": (
                ["address", "shipping address", "billing address"],
                "Address 1&2 (Billing)",
            ),
            "order_total_col": (
                ["order total", "total amount", "total"],
                "Order Total Amount",
            ),
            "city_col": (
                ["city", "state", "zip", "location"],
                "City, State, Zip (Billing)",
            ),
        }

        # Update config with whatever we find in the dataframe
        for config_key, (targets, default) in mapping.items():
            best_col = self._find_best_column(df.columns, targets, default)
            self.config[config_key] = best_col

        # Validate core required columns are present
        required = ["phone_col", "name_col", "product_col"]
        missing = [
            self.config[col] for col in required if self.config[col] not in df.columns
        ]
        if missing:
            raise ValueError(
                f"Required data columns not found. Partial match failed for: {missing}"
            )

        phone_col = self.config["phone_col"]

        # Clean data
        df[phone_col] = df[phone_col].apply(self.clean_phone_number)
        df[self.config["name_col"]] = df[self.config["name_col"]].apply(
            self.format_name
        )

        # Clean and standardize product names
        product_col = self.config["product_col"]
        df[product_col] = df[product_col].astype(str).str.replace("Executive Formal Shirt", "Formal Shirt", regex=False)

        # Format address columns
        for col_type in ["address_col", "city_col"]:
            col_name = self.config.get(col_type)
            if col_name and col_name in df.columns:
                df[col_name] = df[col_name].apply(
                    lambda x: self.format_text(str(x)) if pd.notna(x) else ""
                )

        # SKU Integration
        sku_col = self.config.get("sku_col")
        if sku_col and sku_col in df.columns:
            # Vectorized SKU integration for better performance
            p_series = df[product_col].fillna("").astype(str)
            s_series = df[sku_col].fillna("").astype(str)
            
            valid_sku = (s_series.str.strip() != "") & (s_series.str.lower() != "nan")
            
            df.loc[valid_sku, product_col] = p_series[valid_sku] + " - " + s_series[valid_sku]
            df.loc[~valid_sku, product_col] = p_series[~valid_sku]

        # Enforce string types for categorical columns to prevent Polars mixed-type errors
        for col in [self.config["order_id_col"], product_col, self.config["quantity_col"], self.config["price_col"]]:
            if col in df.columns:
                df[col] = df[col].astype(str)
                
        # Clean order total amount for numeric aggregation
        total_col = self.config.get("order_total_col")
        if total_col and total_col in df.columns:
            df[total_col] = pd.to_numeric(df[total_col].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce").fillna(0)

        # Convert to Polars LazyFrame for optimized execution
        lazy_df = pl.from_pandas(df).lazy()
        
        name_col = self.config["name_col"]
        order_id_col = self.config["order_id_col"]
        product_col = self.config["product_col"]
        quantity_col = self.config["quantity_col"]
        price_col = self.config["price_col"]

        agg_exprs = [
            pl.col(name_col).first(),
            pl.col(order_id_col).cast(pl.String).drop_nulls().unique().str.join(", "),
            pl.col(product_col).cast(pl.String).drop_nulls().str.join("\n- "),
            pl.col(quantity_col).cast(pl.String).drop_nulls().str.join("\n- "),
            pl.col(price_col).cast(pl.String).drop_nulls().str.join("\n- "),
        ]

        # Add optional columns to aggregation
        for key in ["address_col", "city_col", "payment_method_col"]:
            col = self.config.get(key)
            if col and col in df.columns:
                agg_exprs.append(pl.col(col).first())

        grouped_lazy = lazy_df.group_by(phone_col).agg(agg_exprs)

        # Calculate correct total amount (sum of unique order totals per phone)
        if total_col and total_col in df.columns:
            # Get one row per order to capture the Order Total once
            totals_lazy = (
                lazy_df.select([phone_col, order_id_col, total_col])
                .unique(subset=[order_id_col])
                .group_by(phone_col)
                .agg(pl.col(total_col).sum())
            )
            # Join the calculated totals back to the grouped dataframe
            grouped_lazy = grouped_lazy.join(totals_lazy, on=phone_col, how="left")

        # Execute query graph and convert back to Pandas
        return grouped_lazy.collect().to_pandas()

    def create_whatsapp_links(
        self, df: pd.DataFrame, custom_template: str = None
    ) -> pd.DataFrame:
        """Generate formatted WhatsApp messages and links."""
        whatsapp_links = []
        order_summaries = []
        phone_col = self.config["phone_col"]
        name_col = self.config["name_col"]
        order_id_col = self.config["order_id_col"]
        address_col = self.config.get("address_col")
        city_col = self.config.get("city_col")
        product_col = self.config["product_col"]
        quantity_col = self.config["quantity_col"]
        price_col = self.config["price_col"]
        order_total_col = self.config["order_total_col"]
        payment_method_col = self.config.get("payment_method_col")

        for row in df.to_dict("records"):
            phone = row.get(phone_col, "")
            if not phone:
                whatsapp_links.append(None)
                order_summaries.append(None)
                continue

            # Determine Salutation
            name = row.get(name_col, "")
            salutation = self.detect_gender_salutation(name)
            order_id = str(row.get(order_id_col, ""))

            # Format Address
            formatted_address = self.format_address(
                row.get(address_col, ""),
                row.get(city_col, ""),
            )

            # Build Product List & Totals for template use
            product_list = []
            products = str(row.get(product_col, "")).split("\n- ")
            quantities = str(row.get(quantity_col, "")).split("\n- ")
            prices = str(row.get(price_col, "")).split("\n- ")

            for i, prod in enumerate(products):
                item_line = f"- {prod.strip()}"
                if i < len(quantities):
                    item_line += f" - Qty: {quantities[i].strip()}"
                if i < len(prices):
                    item_line += f" - Price: {prices[i].strip()} BDT"
                product_list.append(item_line)

            products_str = "\n".join(product_list)

            total_amount = float(row.get(order_total_col, 0.0))
            collectable_amount = total_amount
            is_paid = False
            
            payment_method = row.get(payment_method_col)
            if payment_method and pd.notna(payment_method):
                method = str(payment_method).lower()
                if any(x in method for x in ["bkash", "online", "ssl", "paid"]):
                    collectable_amount = 0
                    is_paid = True

            total_str = f"{total_amount:.2f} BDT"
            if is_paid:
                total_str += " (PAID)"
            elif collectable_amount != total_amount:
                total_str += f" (Collectable: {collectable_amount:.2f} BDT)"

            if custom_template:
                message = (
                    custom_template.replace("{name}", str(name))
                    .replace("{salutation}", salutation)
                    .replace("{order_id}", order_id)
                    .replace("{products_list}", products_str)
                    .replace("{total}", total_str)
                    .replace("{address}", formatted_address)
                )
            else:
                lines = [
                    f"*Order Verification From DEEN Commerce*",
                    "",
                    f"Assalamu Alaikum, {salutation}!",
                    "",
                    f"Dear {name},",
                    "",
                    "Please verify your order details:",
                    "",
                    f"*Order ID:* {order_id}",
                    "",
                    "*Your Order:*",
                    products_str,
                    "",
                    f"*Total Amount:* {total_str}",
                    "",
                    "*Shipping Address:*",
                    formatted_address,
                    "",
                    "Please confirm the order and address.",
                    "If any correction is needed, please let us know the possible adjustment.",
                    "",
                    "*Delivery fees apply for returns.*",
                    "",
                    "Thank you for shopping with DEEN Commerce! Grab our latest collection on: https://deencommerce.com/",
                ]
                message = "\n".join(lines)
            
            encoded_message = urllib.parse.quote(message)
            whatsapp_links.append(f"https://wa.me/+88{phone}?text={encoded_message}")

            # Simple Summary for copy-pasting
            summary_parts = [prod.strip() for prod in products]
            summary_text = f"Order {order_id}: " + ", ".join(summary_parts)
            summary_text += f" | Total: {total_amount:.0f} BDT"
            order_summaries.append(summary_text)

        df["whatsapp_link"] = whatsapp_links
        df["order_summary"] = order_summaries

        return df
