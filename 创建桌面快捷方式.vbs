Set shell = CreateObject("WScript.Shell")
desktop = shell.SpecialFolders("Desktop")

' 启动工作台快捷方式
Set sc = shell.CreateShortcut(desktop & "\讲书工作台.lnk")
sc.TargetPath = "D:\讲书工作流\start.bat"
sc.IconLocation = "%SystemRoot%\System32\imageres.dll,179"
sc.WorkingDirectory = "D:\讲书工作流"
sc.Description = "启动讲书工作流 Web 服务"
sc.Save

' 网页启动器快捷方式（双击可直接打开）
Set sc2 = shell.CreateShortcut(desktop & "\讲书工作台(网页).lnk")
sc2.TargetPath = "D:\讲书工作流\启动工作台.html"
sc2.IconLocation = "%SystemRoot%\System32\imageres.dll,23"
sc2.WorkingDirectory = "D:\讲书工作流"
sc2.Description = "讲书工作台网页启动器"
sc2.Save

MsgBox "快捷方式已创建到桌面！" & vbCrLf & vbCrLf & "双击「讲书工作台」启动服务" & vbCrLf & "双击「讲书工作台(网页)」查看状态", 64, "完成"
