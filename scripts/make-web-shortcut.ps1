# Ярлык «photo3d» на рабочем столе - вход в веб-интерфейс.
#
# Рядом лежит make-shortcut.ps1: тот открывает сцену в Godot, этот - библиотеку
# моделей и прогулку в браузере. Два разных входа, поэтому два ярлыка, а не
# один с параметром: человек нажимает на то, что хочет, а не выбирает в диалоге.
#
#   powershell -ExecutionPolicy Bypass -File scripts\make-web-shortcut.ps1

param(
    [string]$Scripts = "D:\Develop\photo3d\scripts",
    [string]$Name    = "photo3d",
    # Иконка проекта - изометрический куб в палитре интерфейса. Собирается
    # scripts/make-icon.py, в .ico лежат все размеры от 16 до 256: систему
    # надо кормить готовыми, иначе она ужимает большой и мылит панель задач.
    [string]$Icon    = ""
)

$launcher = Join-Path $Scripts "photo3d-web.vbs"
if (-not (Test-Path $launcher)) {
    throw "не найден $launcher - передай -Scripts с путём к папке scripts репозитория"
}

if (-not $Icon) {
    $ico = Join-Path (Split-Path $Scripts -Parent) "web\static\icons\photo3d.ico"
    if (Test-Path $ico) {
        # Индекс 0 обязателен: без него оболочка иногда берёт из .ico только
        # первое изображение вместо подходящего по размеру.
        $Icon = "$ico,0"
    } else {
        # Своей иконки нет - собери её, но ярлык всё равно поставим: отсутствие
        # картинки не повод оставлять человека без запуска.
        Write-Warning "нет $ico - собери: python scripts/make-icon.py. Ставлю системный глобус."
        $Icon = "$env:SystemRoot\System32\SHELL32.dll,14"
    }
}

# Рабочий стол берётся у системы, а не склеивается из $env:USERPROFILE:
# при включённом OneDrive он лежит в C:\Users\<имя>\OneDrive\Рабочий стол,
# и склеенный путь молча создал бы ярлык там, где его никто не увидит.
$desktop = [Environment]::GetFolderPath("Desktop")
$path = Join-Path $desktop "$Name.lnk"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($path)
# Цель - wscript, а не сам .vbs: у .vbs по умолчанию может быть назначен
# cscript, и тогда консольное окно всё-таки появится.
$lnk.TargetPath = "$env:SystemRoot\System32\wscript.exe"
$lnk.Arguments = "`"$launcher`""
$lnk.WorkingDirectory = $Scripts
$lnk.IconLocation = $Icon
$lnk.Description = "photo3d: библиотека моделей, просмотр и прогулка в браузере"
$lnk.Save()

"ярлык: $path"
"открывает: http://localhost:8765 (сервер поднимается сам, если не запущен)"
