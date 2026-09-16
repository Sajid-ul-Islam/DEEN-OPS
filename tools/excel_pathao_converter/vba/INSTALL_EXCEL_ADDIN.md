# How to Install & Use the Excel Add-in

This guide explains how to make the `PathaoBulkConverter` macro available in Microsoft Excel.

---

## ⚠️ Why Did You See: *"Cannot run the macro 'Book1.xlsx'!ConvertToPathaoBulk"*?

When you first opened Excel and imported the code, Excel called the temporary blank file **`Book1`**. 
- If you clicked **Save** as a normal Excel file (`.xlsx`), Excel automatically **deleted the macro** (because standard `.xlsx` files are not allowed to contain macros!).
- When you later tried to run the macro, Excel tried to find the code inside `Book1.xlsx` and couldn't find it.
- **The macro is NOT trying to convert `Book1.xlsx`** — Excel was simply looking for the code inside `Book1.xlsx`!

---

## 🏆 Recommended Solution: Put it in your "Personal Macro Workbook" (1 Minute)

The Personal Macro Workbook (`PERSONAL.XLSB`) is a hidden workbook that opens silently with Excel every time. Any macro saved here is **permanently available in EVERY file you open forever**!

### Step 1: Make sure Personal Macro Workbook exists
1. Open Excel.
2. Go to the **View** tab at the top.
3. Click **Macros** -> **Record Macro...**.
4. In the *Store macro in:* dropdown, select **Personal Macro Workbook**.
5. Click **OK**, then immediately click **Macros** -> **Stop Recording**.
   *(This takes 3 seconds and tells Excel to create your `PERSONAL.XLSB` file).*

### Step 2: Import the Converter into Personal Workbook
1. Press **`Alt + F11`** to open the VBA Editor.
2. In the left panel (Project Explorer), look for:
   ```text
   VBAProject (PERSONAL.XLSB)
   ```
3. Right-click on **`VBAProject (PERSONAL.XLSB)`**, select **Import File...** (or press **`Ctrl + M`**).
4. Select `PathaoBulkConverter.bas`.
5. Click the **Save** icon (diskette 💾) in the VBA toolbar to save `PERSONAL.XLSB`.
6. Close the VBA window.

### Step 3: Run it on any order file!
1. Open your product-wise orders file.
2. If there is a yellow banner at the top, click **"Enable Editing"**.
3. Press **`Alt + F8`**, select **`ConvertToPathaoBulk`** (or `PERSONAL.XLSB!ConvertToPathaoBulk`), and click **Run**.
4. A clean new workbook will appear containing the official 15 Pathao bulk upload columns!

---

## 💡 Pro Tip: 1-Click Button on Excel Top Toolbar

1. In Excel, go to **File -> Options -> Quick Access Toolbar**.
2. Under *Choose commands from:*, choose **Macros**.
3. Select **`PERSONAL.XLSB!ConvertToPathaoBulk`** and click **Add >>**.
4. Click **Modify...** to choose an icon (e.g. a box 📦 or truck) and change display name to `Convert to Pathao Bulk`.
5. Click **OK**.
6. Now you have a 1-click button at the very top of Excel to convert any sheet instantly!

---

## ⚡ Alternative (No Excel Setup Needed): Use the Desktop Converter

If you don't want to configure Excel macros:
- Drag and drop your order file directly onto:
  ```text
  tools\excel_pathao_converter\run_converter.bat
  ```
- Or double-click `run_converter.bat` to choose your file. It converts in 2 seconds!
