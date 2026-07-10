$w = New-Object -ComObject WScript.Shell
$d = [Environment]::GetFolderPath('Desktop')
$s = $w.CreateShortcut("$d\jiangshu.lnk")
$s.TargetPath = 'D:\讲书工作流\start.bat'
$s.IconLocation = '%SystemRoot%\System32\imageres.dll,179'
$s.WorkingDirectory = 'D:\讲书工作流'
$s.Description = 'Launch book workflow'
$s.Save()
Write-Host 'OK'
