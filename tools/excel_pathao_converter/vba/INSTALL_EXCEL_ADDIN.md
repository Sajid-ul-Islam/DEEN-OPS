# How to Install & Use the Excel Add-in

This guide explains how to install the `PathaoBulkConverter` macro/add-in directly inside Microsoft Excel so you can convert any product-wise order list into Pathao Bulk format with a single click.

---

## Method 1: Save as an Excel Add-in (`.xlam`) — Recommended

Once installed as an add-in, the conversion macro is permanently available in Excel on this computer for any workbook!

1. Open Microsoft Excel with a blank workbook.
2. Press **`Alt + F11`** to open the **Visual Basic for Applications (VBA)** editor.
3. In the top menu, click **File** -> **Import File...** (or press **`Ctrl + M`**).
4. Browse to this folder and select:
   ```
   PathaoBulkConverter.bas
   ```
   *(You will see `PathaoBulkConverter` appear under Modules in the left Project Explorer)*.
5. In Excel, go to **File** -> **Save As**.
6. In the **Save as type** dropdown, choose:
   **Excel Add-in (*.xlam)**.
7. Name it:
   ```
   Pathao_Bulk_Converter.xlam
   ```
   *(Excel will automatically save it in your default Microsoft Excel AddIns directory, or you can save it right in this folder)*.
8. To activate it in Excel:
   - Go to **File** -> **Options** -> **Add-ins**.
   - At the bottom next to *Manage: Excel Add-ins*, click **Go...**
   - Check the box for **Pathao_Bulk_Converter** (or click *Browse...* and select the `.xlam` file).
   - Click **OK**.

### How to Run it anytime:
- Open your product-wise order list file in Excel.
- Press **`Alt + F8`**, select **`ConvertToPathaoBulk`**, and click **Run**.
- A new worksheet named **`Pathao_Bulk_Upload`** is generated instantly with the official 15 columns!

---

## Method 2: Add a 1-Click Button to your Excel Ribbon / Quick Access Toolbar

For the fastest workflow, you can add a dedicated button to Excel's top toolbar:

1. In Excel, go to **File** -> **Options** -> **Quick Access Toolbar** (or **Customize Ribbon**).
2. Under **Choose commands from:**, select **Macros**.
3. Select **`ConvertToPathaoBulk`** and click **Add >>**.
4. Click **Modify...** to choose a friendly icon (like a package or truck icon 📦) and change the display name to `Convert to Pathao Bulk`.
5. Click **OK**.
6. Now, whenever you have an order sheet open, simply click that icon in your top toolbar!

---

## Method 3: One-time Use in Any Open File

If you don't want to install an add-in permanently:
1. Open your product-wise orders file in Excel.
2. Press **`Alt + F11`**, click **File** -> **Import File...**, and choose `PathaoBulkConverter.bas`.
3. Press **`F5`** (or close the VBA window, press **`Alt + F8`**, and click **Run**).
