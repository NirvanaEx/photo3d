# Ярлык «войти в сцену» на рабочем столе.
#
# Лежит в репозитории, а не сделан руками один раз: ярлык теряется при
# переустановке, а путь к движку и имя сцены - те же данные, что и в конфиге,
# и держать их в голове незачем.
#
# Ярлык (.lnk), а не .bat: батник мигает чёрным окном консоли перед запуском
# и оставляет его висеть, пока идёт игра.
#
#   powershell -ExecutionPolicy Bypass -File scripts\make-shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\make-shortcut.ps1 -Scene res://scenes/main.tscn

param(
    [string]$Godot = "C:\Tools\Godot\Godot_v4.7.1-stable_win64.exe",
    [string]$Game  = "D:\Develop\photo3d\game",
    [string]$Scene = "res://scenes/walk.tscn",
    [string]$Name  = "photo3d — прогулка"
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
$lnk.Arguments = "--path `"$Game`" $Scene"
$lnk.WorkingDirectory = $Game
$lnk.IconLocation = "$Godot,0"
$lnk.Description = "Войти в сцену photo3d: WASD - идти, мышь - смотреть, Esc - выйти"
$lnk.Save()

"ярлык: $path"
"запускает: $Scene"
