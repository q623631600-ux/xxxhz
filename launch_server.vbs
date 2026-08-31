Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\讲书升级Agent"
WshShell.Run "python -u web_app.py", 0, False
