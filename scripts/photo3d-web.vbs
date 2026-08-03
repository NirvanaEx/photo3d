' Беззвучный запуск photo3d-web.ps1.
'
' Нужен ровно затем, зачем make-shortcut.ps1 делает .lnk вместо .bat: чтобы
' перед открытием браузера не мигало чёрное окно консоли. powershell.exe даже
' с -WindowStyle Hidden успевает показать окно на долю секунды - оно создаётся
' до того, как параметр применится. wscript не создаёт его вовсе.
'
' Путь к .ps1 берётся от собственного расположения, а не зашивается: скрипты
' лежат рядом, и репозиторий может стоять на любом диске.

Set fso = CreateObject("Scripting.FileSystemObject")
script = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "photo3d-web.ps1")

Set shell = CreateObject("WScript.Shell")
' 0 - окно не показывать, False - не ждать завершения: браузер откроет сам
' скрипт, держать процесс запуска незачем.
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & script & """", 0, False
