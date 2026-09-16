Dim dict, rec, items
Set dict = CreateObject("Scripting.Dictionary")
Set rec = CreateObject("Scripting.Dictionary")
Set items = CreateObject("Scripting.Dictionary")
items("Shirt") = 1
Set rec("Items") = items
Set dict("1001") = rec

' Now try modifying
Set rec = dict("1001")
rec("Items")("Shirt") = rec("Items")("Shirt") + 1
WScript.Echo "Result: " & rec("Items")("Shirt")
