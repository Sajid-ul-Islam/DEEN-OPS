# Product-Wise Order List to Pathao Bulk Upload Converter

A portable, standalone toolkit that converts product-wise e-commerce order list Excel or CSV files (where each product line item is a separate row) into the official 15-column **Pathao Bulk Upload** Excel format.

---

## 📁 Package Directory Structure

This folder is **completely self-contained**. You can move, copy, or zip this entire folder anywhere on your computer or share it to another computer:

```text
tools/excel_pathao_converter/
├── convert_to_pathao.py        # Python conversion engine (CLI + GUI file picker)
├── run_converter.bat           # 1-click Windows launcher (double-click or drag-and-drop)
├── requirements.txt            # Minimal dependencies (pandas, openpyxl)
├── README.md                   # This documentation
├── templates/
│   ├── sample_product_wise_orders.xlsx     # Sample multi-item input file
│   └── pathao_bulk_template.xlsx           # Empty official Pathao bulk schema
└── vba/
    ├── PathaoBulkConverter.bas # Native Excel VBA module (can be saved as .xlam)
    ├── INSTALL_EXCEL_ADDIN.md  # 1-minute step-by-step setup guide for Excel
    └── create_addin.py         # Automated COM builder for Excel Add-in
```

---

## 🚀 How to Use

You have **two easy methods** to convert your files:

### Option 1: Standalone Desktop Converter (No Excel Setup Needed)

#### A. Double-Click GUI
1. Double-click `run_converter.bat`.
2. A clean window will appear.
3. Click **Browse...** to select your product-wise Excel or CSV file.
4. Click **Convert to Pathao Bulk**.
5. Your Pathao bulk file is instantly created with `_Pathao_Bulk.xlsx` appended to the name!

#### B. Drag-and-Drop
- Drag your order Excel file and drop it directly onto `run_converter.bat`. It will automatically convert the file in the same folder.

#### C. Command Line (CLI)
```bash
# Basic conversion
python convert_to_pathao.py -i my_orders.xlsx

# Specify custom output name and store name
python convert_to_pathao.py -i my_orders.xlsx -o final_pathao.xlsx --store-name "Deen Commerce"
```

---

### Option 2: Native Microsoft Excel Add-in (Run Inside Excel)

If you prefer to work entirely inside Microsoft Excel:

1. Follow the 1-minute instructions in [`vba/INSTALL_EXCEL_ADDIN.md`](vba/INSTALL_EXCEL_ADDIN.md) to import `PathaoBulkConverter.bas` or save it as `Pathao_Bulk_Converter.xlam`.
2. Whenever you open any product-wise order sheet in Excel:
   - Press **`Alt + F8`** and run **`ConvertToPathaoBulk`** (or click your custom Ribbon button).
   - A new worksheet titled **`Pathao_Bulk_Upload`** will appear immediately with your converted orders!

---

## 📋 Pathao Bulk Upload Columns Produced

The converter produces the exact 15 columns required by Pathao Courier:

| Column Header | Description / Auto-Detection |
| :--- | :--- |
| `ItemType` | Default: `Parcel` |
| `StoreName` | Default: `Deen Commerce` (customizable) |
| `MerchantOrderId` | Preserves Order ID / Invoice Number |
| `RecipientName(*)` | Full Name or First + Last Name |
| `RecipientPhone(*)` | Formatted to 11-digit BD mobile (`01XXXXXXXXX`) |
| `RecipientAddress(*)` | Full shipping address (without redundant duplicates) |
| `RecipientCity(*)` | Normalized recipient city (e.g. Dhaka, Chattogram) |
| `RecipientZone(*)` | Extracted zone or city fallback |
| `RecipientArea` | Specific area / neighborhood if available |
| `AmountToCollect(*)` | Cash on Delivery (COD) amount (`0` if prepaid via bKash/Card/Nagad) |
| `ItemQuantity` | Sum of all product quantities for this order |
| `ItemWeight` | Default: `0.5` kg |
| `ItemDesc` | Smart category summary (e.g., `2x Panjabi, 1x Pajama`) |
| `SpecialInstruction` | Payment method note / split instructions |
| `WarehouseOutlet` | Pickup outlet / warehouse mapping |

---

## 🚚 Moving This Folder Later

To move this tool to your Desktop, USB drive, or another machine:
1. Copy or move the `excel_pathao_converter` folder anywhere.
2. If Python is installed on that machine:
   ```bash
   pip install -r requirements.txt
   ```
3. Run `run_converter.bat` or use the Excel VBA module!
