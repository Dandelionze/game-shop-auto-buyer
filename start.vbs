Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "py -3.14 """ & Replace(WScript.ScriptFullName, "start.vbs", "shop_buyer.py") & """", 0, False
