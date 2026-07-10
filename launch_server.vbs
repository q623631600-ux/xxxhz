Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\讲书升级Agent"
WshShell.Run "C:\Python313\python.exe -u web_app.py", 0, False
