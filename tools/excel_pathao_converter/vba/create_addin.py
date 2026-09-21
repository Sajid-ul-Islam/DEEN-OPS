#!/usr/bin/env python3
"""
Helper script to compile PathaoBulkConverter.bas into an Excel Add-in (.xlam)
or macro-enabled template (.xlsm) using Excel COM automation.
"""

import os


def build_excel_addin():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bas_file = os.path.join(base_dir, "PathaoBulkConverter.bas")
    output_xlam = os.path.join(base_dir, "Pathao_Bulk_Converter.xlam")
    output_xlsm = os.path.join(base_dir, "Pathao_Bulk_Template.xlsm")

    if not os.path.exists(bas_file):
        print(f"[ERROR] VBA module not found: {bas_file}")
        return False

    try:
        import win32com.client
    except ImportError:
        print(
            "[INFO] pywin32 is not installed. To build .xlam automatically: pip install pywin32"
        )
        return False

    print("[*] Launching Excel in background to create Add-in...")
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
    except Exception as e:
        print(f"[INFO] Could not launch Excel COM: {e}")
        print(
            "[INFO] You can manually import 'PathaoBulkConverter.bas' into Excel anytime."
        )
        return False

    try:
        wb = excel.Workbooks.Add()
        try:
            wb.VBProject.VBComponents.Import(bas_file)
            print("[+] Successfully imported VBA module into workbook.")
        except Exception as e:
            print(
                f"[WARN] Access to VBA project object model is disabled in Excel Trust Center: {e}"
            )
            print(
                "[INFO] To enable: Excel Options -> Trust Center -> Trust Center Settings -> Macro Settings -> Trust access to the VBA project object model."
            )
            wb.Close(False)
            excel.Quit()
            return False

        # File format constants:
        # xlOpenXMLAddIn = 55 (.xlam)
        # xlOpenXMLWorkbookMacroEnabled = 52 (.xlsm)

        # Save as .xlsm
        if os.path.exists(output_xlsm):
            try:
                os.remove(output_xlsm)
            except OSError:
                pass
        wb.SaveAs(output_xlsm, FileFormat=52)
        print(f"[SUCCESS] Saved Macro-Enabled Workbook: {output_xlsm}")

        # Save as .xlam
        if os.path.exists(output_xlam):
            try:
                os.remove(output_xlam)
            except OSError:
                pass
        wb.SaveAs(output_xlam, FileFormat=55)
        print(f"[SUCCESS] Saved Excel Add-In (.xlam): {output_xlam}")

        wb.Close(False)
        excel.Quit()
        return True

    except Exception as e:
        print(f"[ERROR] Error generating Excel add-in: {e}")
        try:
            wb.Close(False)
            excel.Quit()
        except Exception:
            pass
        return False


if __name__ == "__main__":
    success = build_excel_addin()
    if success:
        print("[+] Excel Add-in created successfully!")
    else:
        print("[i] See INSTALL_EXCEL_ADDIN.md for simple 1-minute manual setup.")
