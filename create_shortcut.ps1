$wshell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')

$sc = $wshell.CreateShortcut("$desktop\讲书工作台.lnk")
$sc.TargetPath = "D:\讲书工作流\start.bat"
$sc.IconLocation = "%SystemRoot%\System32\imageres.dll,179"
$sc.WorkingDirectory = "D:\讲书工作流"
$sc.Description = "启动讲书工作流 Web 服务"
$sc.Save()

Write-Host "快捷方式已创建到桌面"
