# Ярлык «photo3d — игры» на рабочем столе: вход в лаунчер сцен.
#
# Рядом лежат два соседа, и это не дублирование, а три разных входа:
#   make-web-shortcut.ps1   — библиотека моделей в браузере;
#   make-shortcut.ps1       — сразу в одну заданную сцену, минуя выбор;
#   этот                    — лаунчер, где видны все сцены с превью.
#
# Сцена в аргументах НЕ передаётся нарочно: лаунчер это главная сцена проекта
# (project.godot), и движок без аргументов открывает его сам. Одно место, где
# записано «что запускается первым», а не два.
#
#   powershell -ExecutionPolicy Bypass -File scripts\make-games-shortcut.ps1

param(
    # Сборка без консоли: консольная нужна инструментам, они разбирают её
    # вывод, а человеку она даёт лишнее чёрное окно поверх игры.
    [string]$Godot = "C:\Tools\Godot\Godot_v4.7.1-stable_win64.exe",
    [string]$Game  = "D:\Develop\photo3d\game",
    [string]$Name  = "photo3d — игры"
)

if (-not (Test-Path $Godot)) {
    throw "движок не найден: $Godot. Положи портативный Godot 4.7 туда или передай -Godot"
}
if (-not (Test-Path (Join-Path $Game "project.godot"))) {
    throw "в $Game нет project.godot - это не проект Godot"
}

# Рабочий стол берётся у системы, а не склеивается из $env:USERPROFILE:
# при включённом OneDrive он лежит в C:\Users\<имя>\OneDrive\Рабочий стол,
# и склеенный путь молча создал бы ярлык там, где его никто не увидит.
$desktop = [Environment]::GetFolderPath("Desktop")
$path = Join-Path $desktop "$Name.lnk"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($path)
$lnk.TargetPath = $Godot
$lnk.Arguments = "--path `"$Game`""
$lnk.WorkingDirectory = $Game
$lnk.IconLocation = "$Godot,0"
$lnk.Description = "photo3d: выбор сцены - архипелаг, прогулка, класс"
$lnk.Save()

"ярлык: $path"
"открывает: лаунчер сцен (game/scenes/launcher.tscn)"
"превью карточек: wsl -e /opt/photo3d/venv/bin/python scripts/make-previews.py"
