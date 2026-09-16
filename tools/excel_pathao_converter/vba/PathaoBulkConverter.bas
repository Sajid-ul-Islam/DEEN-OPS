Attribute VB_Name = "PathaoBulkConverter"
Option Explicit

' ==============================================================================
' Pathao Bulk Upload Converter - Excel VBA Add-in Module
'
' Purpose: Converts any active product-wise e-commerce order list sheet
'          into the official 15-column Pathao Bulk Upload format.
'
' Features:
'   - Works on any Excel sheet or opened CSV file.
'   - Creates a clean new workbook with the 15 Pathao bulk columns.
'   - Safely handles Protected View, missing columns, and Excel error cells.
'   - Automatically formats 11-digit phone numbers and sums quantities.
' ==============================================================================

Public Sub ConvertToPathaoBulk()
    Dim wsSource As Worksheet
    Dim wbSource As Workbook
    Dim wbDest As Workbook
    Dim wsDest As Worksheet
    
    Dim lastRow As Long, lastCol As Long
    Dim r As Long, c As Long
    Dim currentStep As String
    Dim currentRow As Long
    
    Dim colOrderID As Long, colPhone As Long, colName As Long
    Dim colAddress As Long, colCity As Long, colState As Long
    Dim colItemName As Long, colQty As Long, colTotal As Long, colPayMethod As Long
    
    Dim headerText As String
    Dim orderDict As Object ' Scripting.Dictionary
    Dim key As Variant
    Dim orderKey As String
    
    Dim rawOrderID As String, rawPhone As String, rawName As String
    Dim rawAddr As String, rawCity As String, rawState As String
    Dim rawItem As String, rawQty As Long, rawTotal As Double, rawPay As String
    
    Dim destRow As Long
    Dim fullAddress As String, cleanPhone As String
    Dim summaryItems As String
    Dim amtCollect As Long
    Dim destCity As String
    
    On Error GoTo ErrorHandler
    
    ' Check if Excel is in Protected View
    currentStep = "Checking workbook status"
    If Application.ProtectedViewWindows.Count > 0 Then
        If Not Application.ActiveProtectedViewWindow Is Nothing Then
            MsgBox "Excel is currently in Protected View." & vbCrLf & vbCrLf & _
                   "Please click the yellow 'Enable Editing' button at the top of your Excel window, then run this macro again.", _
                   vbExclamation, "Protected View Detected"
            Exit Sub
        End If
    End If
    
    Set wbSource = ActiveWorkbook
    If wbSource Is Nothing Then
        MsgBox "Please open a workbook containing your order list first.", vbExclamation, "No Active Workbook"
        Exit Sub
    End If
    
    Set wsSource = ActiveSheet
    If wsSource Is Nothing Then
        MsgBox "No active worksheet found.", vbExclamation, "No Active Sheet"
        Exit Sub
    End If
    
    ' Determine last used row and column safely
    currentStep = "Detecting data dimensions"
    On Error Resume Next
    lastRow = wsSource.Cells.Find(What:="*", After:=wsSource.Cells(1, 1), _
                                  LookIn:=xlFormulas, LookAt:=xlPart, _
                                  SearchOrder:=xlByRows, SearchDirection:=xlPrevious).Row
    lastCol = wsSource.Cells.Find(What:="*", After:=wsSource.Cells(1, 1), _
                                  LookIn:=xlFormulas, LookAt:=xlPart, _
                                  SearchOrder:=xlByColumns, SearchDirection:=xlPrevious).Column
    On Error GoTo ErrorHandler
    
    If lastRow < 2 Or lastCol < 1 Then
        MsgBox "The active sheet appears to be empty or does not contain data rows.", _
               vbExclamation, "No Data Found"
        Exit Sub
    End If
    
    ' Initialize column indexes
    colOrderID = 0: colPhone = 0: colName = 0: colAddress = 0: colCity = 0
    colState = 0: colItemName = 0: colQty = 0: colTotal = 0: colPayMethod = 0
    
    ' Detect columns from header row (Row 1)
    currentStep = "Scanning column headers"
    For c = 1 To lastCol
        headerText = LCase(SafeCellText(wsSource.Cells(1, c)))
        
        If colOrderID = 0 And (InStr(headerText, "order id") > 0 Or InStr(headerText, "order number") > 0 Or InStr(headerText, "order #") > 0 Or InStr(headerText, "invoice") > 0 Or headerText = "id") Then
            colOrderID = c
        ElseIf colPhone = 0 And (InStr(headerText, "phone") > 0 Or InStr(headerText, "mobile") > 0 Or InStr(headerText, "contact") > 0) Then
            colPhone = c
        ElseIf colName = 0 And (InStr(headerText, "full name") > 0 Or InStr(headerText, "customer name") > 0 Or InStr(headerText, "recipient") > 0 Or headerText = "name" Or InStr(headerText, "billing name") > 0) Then
            colName = c
        ElseIf colAddress = 0 And (InStr(headerText, "address") > 0 Or InStr(headerText, "street") > 0) Then
            colAddress = c
        ElseIf colCity = 0 And (InStr(headerText, "city") > 0 Or InStr(headerText, "district") > 0 Or InStr(headerText, "town") > 0) Then
            colCity = c
        ElseIf colState = 0 And (InStr(headerText, "state") > 0 Or InStr(headerText, "division") > 0) Then
            colState = c
        ElseIf colItemName = 0 And (InStr(headerText, "item name") > 0 Or InStr(headerText, "product") > 0 Or InStr(headerText, "title") > 0 Or headerText = "item") Then
            colItemName = c
        ElseIf colQty = 0 And (InStr(headerText, "qty") > 0 Or InStr(headerText, "quantity") > 0) Then
            colQty = c
        ElseIf colTotal = 0 And (InStr(headerText, "total") > 0 Or InStr(headerText, "amount") > 0 Or InStr(headerText, "grand total") > 0) Then
            colTotal = c
        ElseIf colPayMethod = 0 And (InStr(headerText, "payment") > 0 Or InStr(headerText, "pay method") > 0) Then
            colPayMethod = c
        End If
    Next c
    
    ' Check critical headers
    If colOrderID = 0 And colPhone = 0 Then
        MsgBox "Could not find an 'Order ID' or 'Phone' column in Row 1." & vbCrLf & vbCrLf & _
               "Please ensure Row 1 contains headers like: Order ID, Phone, Customer Name, Address, Item Name, Quantity, Total.", _
               vbCritical, "Missing Key Headers"
        Exit Sub
    End If
    
    currentStep = "Initializing dictionary"
    Set orderDict = CreateObject("Scripting.Dictionary")
    
    Application.ScreenUpdating = False
    Application.Calculation = xlCalculationManual
    
    ' Group product-wise rows by Order ID or Phone
    For r = 2 To lastRow
        currentRow = r
        currentStep = "Reading Row " & r
        
        rawOrderID = IIf(colOrderID > 0, SafeCellText(wsSource.Cells(r, colOrderID)), "")
        rawPhone = IIf(colPhone > 0, CleanBDPhone(SafeCellText(wsSource.Cells(r, colPhone))), "")
        
        If Len(rawOrderID) > 0 Then
            orderKey = rawOrderID
        ElseIf Len(rawPhone) > 0 Then
            orderKey = rawPhone
        Else
            orderKey = "Row_" & r
        End If
        
        rawName = IIf(colName > 0, SafeCellText(wsSource.Cells(r, colName)), "Customer")
        If Len(Trim(rawName)) = 0 Then rawName = "Customer"
        
        rawAddr = IIf(colAddress > 0, SafeCellText(wsSource.Cells(r, colAddress)), "")
        rawCity = IIf(colCity > 0, SafeCellText(wsSource.Cells(r, colCity)), "")
        rawState = IIf(colState > 0, SafeCellText(wsSource.Cells(r, colState)), "")
        rawItem = IIf(colItemName > 0, SafeCellText(wsSource.Cells(r, colItemName)), "Item")
        
        rawQty = 1
        If colQty > 0 Then
            Dim qtyText As String
            qtyText = SafeCellText(wsSource.Cells(r, colQty))
            If IsNumeric(qtyText) Then
                rawQty = CLng(Val(qtyText))
            End If
        End If
        If rawQty <= 0 Then rawQty = 1
        
        rawTotal = 0
        If colTotal > 0 Then
            Dim totalText As String
            totalText = SafeCellText(wsSource.Cells(r, colTotal))
            If IsNumeric(totalText) Then
                rawTotal = CDbl(Val(totalText))
            End If
        End If
        
        rawPay = IIf(colPayMethod > 0, SafeCellText(wsSource.Cells(r, colPayMethod)), "")
        
        If Not orderDict.Exists(orderKey) Then
            Dim rec As Object
            Set rec = CreateObject("Scripting.Dictionary")
            rec("OrderID") = rawOrderID
            rec("Phone") = rawPhone
            rec("Name") = rawName
            rec("Address") = rawAddr
            rec("City") = rawCity
            rec("State") = rawState
            rec("TotalQty") = rawQty
            rec("TotalAmount") = rawTotal
            rec("PaymentMethod") = rawPay
            
            Dim itemColl As Object
            Set itemColl = CreateObject("Scripting.Dictionary")
            itemColl(SimplifyItemName(rawItem)) = rawQty
            Set rec("Items") = itemColl
            
            Set orderDict(orderKey) = rec
        Else
            Set rec = orderDict(orderKey)
            rec("TotalQty") = rec("TotalQty") + rawQty
            
            Dim sItem As String
            sItem = SimplifyItemName(rawItem)
            If rec("Items").Exists(sItem) Then
                rec("Items")(sItem) = rec("Items")(sItem) + rawQty
            Else
                rec("Items")(sItem) = rawQty
            End If
        End If
    Next r
    
    ' Create a fresh, standalone workbook for Pathao Bulk Upload
    currentStep = "Creating destination workbook"
    Set wbDest = Application.Workbooks.Add(xlWBATWorksheet)
    Set wsDest = wbDest.Worksheets(1)
    
    On Error Resume Next
    wsDest.Name = "Pathao_Bulk_Upload"
    On Error GoTo ErrorHandler
    
    ' Define 15 official Pathao bulk headers
    currentStep = "Writing headers"
    Dim headers As Variant
    headers = Array( _
        "ItemType", "StoreName", "MerchantOrderId", "RecipientName(*)", _
        "RecipientPhone(*)", "RecipientAddress(*)", "RecipientCity(*)", _
        "RecipientZone(*)", "RecipientArea", "AmountToCollect(*)", _
        "ItemQuantity", "ItemWeight", "ItemDesc", "SpecialInstruction", "WarehouseOutlet" _
    )
    
    For c = 0 To UBound(headers)
        wsDest.Cells(1, c + 1).Value = headers(c)
    Next c
    
    ' Style Header Row
    With wsDest.Range(wsDest.Cells(1, 1), wsDest.Cells(1, UBound(headers) + 1))
        .Font.Bold = True
        .Font.Color = RGB(255, 255, 255)
        .Interior.Color = RGB(30, 58, 138) ' Dark Royal Blue
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .RowHeight = 26
    End With
    
    currentStep = "Populating Pathao orders"
    destRow = 2
    For Each key In orderDict.Keys
        Set rec = orderDict(key)
        
        ' Address without duplicates
        fullAddress = rec("Address")
        If Len(rec("City")) > 0 And InStr(LCase(fullAddress), LCase(rec("City"))) = 0 Then
            fullAddress = fullAddress & IIf(Len(fullAddress) > 0, ", ", "") & rec("City")
        End If
        If Len(rec("State")) > 0 And InStr(LCase(fullAddress), LCase(rec("State"))) = 0 And LCase(rec("State")) <> LCase(rec("City")) Then
            fullAddress = fullAddress & IIf(Len(fullAddress) > 0, ", ", "") & rec("State")
        End If
        If Len(Trim(fullAddress)) = 0 Then fullAddress = "Address Not Provided"
        
        ' Summary items (e.g. 2x Drop Shoulder, 1x Jeans)
        summaryItems = ""
        Dim itmKey As Variant
        For Each itmKey In rec("Items").Keys
            If Len(summaryItems) > 0 Then summaryItems = summaryItems & ", "
            summaryItems = summaryItems & rec("Items")(itmKey) & "x " & itmKey
        Next itmKey
        If Len(summaryItems) = 0 Then summaryItems = "General Items"
        
        ' Amount to collect (0 for prepaid)
        amtCollect = CLng(Round(rec("TotalAmount")))
        Dim pmLower As String
        pmLower = LCase(rec("PaymentMethod"))
        If InStr(pmLower, "bkash") > 0 Or InStr(pmLower, "nagad") > 0 Or _
           InStr(pmLower, "card") > 0 Or InStr(pmLower, "paid") > 0 Or _
           InStr(pmLower, "online") > 0 Or InStr(pmLower, "rocket") > 0 Then
            amtCollect = 0
        End If
        
        cleanPhone = rec("Phone")
        If Len(cleanPhone) < 11 Then cleanPhone = "01700000000"
        
        destCity = rec("City")
        If Len(destCity) = 0 Then destCity = rec("State")
        If Len(destCity) = 0 Then destCity = "Dhaka"
        
        ' Populate destination cells
        wsDest.Cells(destRow, 1).Value = "Parcel"
        wsDest.Cells(destRow, 2).Value = "Deen Commerce"
        
        wsDest.Cells(destRow, 3).NumberFormat = "@"
        wsDest.Cells(destRow, 3).Value = CStr(rec("OrderID"))
        
        wsDest.Cells(destRow, 4).Value = StrConv(rec("Name"), vbProperCase)
        
        wsDest.Cells(destRow, 5).NumberFormat = "@"
        wsDest.Cells(destRow, 5).Value = cleanPhone
        
        wsDest.Cells(destRow, 6).Value = fullAddress
        wsDest.Cells(destRow, 7).Value = StrConv(destCity, vbProperCase)
        wsDest.Cells(destRow, 8).Value = StrConv(destCity, vbProperCase)
        wsDest.Cells(destRow, 9).Value = ""
        wsDest.Cells(destRow, 10).Value = amtCollect
        wsDest.Cells(destRow, 11).Value = rec("TotalQty")
        wsDest.Cells(destRow, 12).Value = "0.5"
        wsDest.Cells(destRow, 13).Value = summaryItems
        wsDest.Cells(destRow, 14).Value = IIf(Len(rec("PaymentMethod")) > 0, "Payment: " & rec("PaymentMethod"), "")
        wsDest.Cells(destRow, 15).Value = ""
        
        destRow = destRow + 1
    Next key
    
    currentStep = "Autofitting columns"
    On Error Resume Next
    wsDest.Columns("A:O").AutoFit
    On Error GoTo ErrorHandler
    
    Application.Calculation = xlCalculationAutomatic
    Application.ScreenUpdating = True
    
    MsgBox "Successfully converted " & (destRow - 2) & " orders into Pathao Bulk format!" & vbCrLf & vbCrLf & _
           "A new workbook has been opened with your Pathao Bulk sheet." & vbCrLf & _
           "You can now click 'File -> Save As' to save it as an Excel file.", _
           vbInformation, "Conversion Complete"
    Exit Sub

ErrorHandler:
    Application.Calculation = xlCalculationAutomatic
    Application.ScreenUpdating = True
    MsgBox "An error occurred during conversion:" & vbCrLf & _
           "Step: " & currentStep & vbCrLf & _
           "Error " & Err.Number & ": " & Err.Description & vbCrLf & vbCrLf & _
           "Tip: If your file has a yellow 'Enable Editing' bar at the top, please click it first.", _
           vbCritical, "Conversion Error"
End Sub

' ------------------------------------------------------------------------------
' Safe cell text extractor (never throws error on #N/A or formula error cells)
' ------------------------------------------------------------------------------
Private Function SafeCellText(ByVal cell As Range) As String
    On Error Resume Next
    If cell Is Nothing Then
        SafeCellText = ""
    ElseIf IsError(cell.Value) Then
        SafeCellText = ""
    Else
        SafeCellText = Trim(CStr(cell.Value))
    End If
    On Error GoTo 0
End Function

' ------------------------------------------------------------------------------
' Helper: Clean and normalize Bangladesh phone numbers
' ------------------------------------------------------------------------------
Private Function CleanBDPhone(ByVal raw As String) As String
    Dim i As Long, ch As String, digits As String
    digits = ""
    For i = 1 To Len(raw)
        ch = Mid(raw, i, 1)
        If ch >= "0" And ch <= "9" Then digits = digits & ch
    Next i
    
    If Left(digits, 3) = "880" And Len(digits) > 10 Then
        digits = Mid(digits, 4)
    End If
    If Left(digits, 1) <> "0" And Len(digits) == 10 Then
        digits = "0" & digits
    End If
    If Len(digits) > 11 Then
        digits = Right(digits, 11)
    End If
    CleanBDPhone = digits
End Function

' ------------------------------------------------------------------------------
' Helper: Simplify item names for Pathao ItemDesc
' ------------------------------------------------------------------------------
Private Function SimplifyItemName(ByVal rawName As String) As String
    Dim n As String
    n = LCase(rawName)
    
    If InStr(n, "drop shoulder") > 0 Or InStr(n, "oversized") > 0 Then
        SimplifyItemName = "Drop Shoulder"
    ElseIf InStr(n, "active wear") > 0 Or InStr(n, "jersey") > 0 Then
        SimplifyItemName = "Active Wear"
    ElseIf InStr(n, "tank top") > 0 Or InStr(n, "tanktop") > 0 Then
        SimplifyItemName = "TankTop"
    ElseIf InStr(n, "polo") > 0 Then
        SimplifyItemName = "Polo"
    ElseIf InStr(n, "t-shirt") > 0 Or InStr(n, "tshirt") > 0 Or InStr(n, "tee") > 0 Then
        SimplifyItemName = "T-Shirt"
    ElseIf InStr(n, "panjabi") > 0 Or InStr(n, "punjabi") > 0 Then
        SimplifyItemName = "Panjabi"
    ElseIf InStr(n, "pajama") > 0 Or InStr(n, "pyjama") > 0 Then
        SimplifyItemName = "Pajama"
    ElseIf InStr(n, "shirt") > 0 Then
        SimplifyItemName = "Shirt"
    ElseIf InStr(n, "jeans") > 0 Or InStr(n, "denim") > 0 Then
        SimplifyItemName = "Jeans"
    ElseIf InStr(n, "pant") > 0 Or InStr(n, "trouser") > 0 Then
        SimplifyItemName = "Pant"
    ElseIf InStr(n, "hoodie") > 0 Then
        SimplifyItemName = "Hoodie"
    ElseIf InStr(n, "jacket") > 0 Then
        SimplifyItemName = "Jacket"
    ElseIf InStr(n, "attar") > 0 Then
        SimplifyItemName = "Attar"
    ElseIf InStr(n, "cap") > 0 Or InStr(n, "kufi") > 0 Then
        SimplifyItemName = "Cap"
    Else
        Dim words() As String
        words = Split(Trim(rawName), " ")
        If UBound(words) >= 1 Then
            SimplifyItemName = StrConv(words(0) & " " & words(1), vbProperCase)
        ElseIf UBound(words) = 0 And Len(words(0)) > 0 Then
            SimplifyItemName = StrConv(words(0), vbProperCase)
        Else
            SimplifyItemName = "Apparel"
        End If
    End If
End Function
