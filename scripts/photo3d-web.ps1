# Запуск веб-интерфейса photo3d одним действием: поднять сервер, если он не
# поднят, дождаться порта и открыть браузер.
#
# Почему не просто ярлык на http://localhost:8765 (.url):
# такой ярлык открывает браузер всегда, но сервер не запускает, и человек
# получает «не удаётся открыть страницу» без единого намёка, что делать.
#
# Сервер живёт в WSL, а ярлык - на Windows. Связь через localhostForwarding:
# Windows достаёт до 127.0.0.1 внутри дистрибутива. Это же причина, по которой
# порт проверяется реальным подключением, а не Get-NetTCPConnection: слушает
# сокет чужая система, и в таблице Windows он выглядит иначе, чем свой.

param(
    [int]$Port = 8765,
    [string]$Distro = "Ubuntu",
    [string]$ProjectPath = "/mnt/d/Develop/photo3d",
    [string]$Python = "/opt/photo3d/venv/bin/python",
    # Сколько ждать подъёма. Холодный старт uvicorn с импортом Starlette в WSL
    # укладывается в 3-5 с; 30 взято с запасом на первый запуск после ребута,
    # когда сама виртуальная машина WSL ещё не поднята.
    [int]$TimeoutSec = 30
)

$url = "http://localhost:$Port"

function Test-WebUp {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Open-Interface {
    param([string]$Url)

    # Режим приложения: окно без адресной строки, вкладок и закладок, со своей
    # кнопкой в панели задач. От установленного приложения на глаз не отличить,
    # а стоит одного ключа - никакой упаковки не нужно.
    #
    # Браузер ищется в App Paths реестра, а не по путям вида
    # "C:\Program Files (x86)\Microsoft\Edge\...": Edge и Chrome ставятся то в
    # Program Files, то в Program Files (x86), то в профиль пользователя, и
    # список путей устаревал бы молча.
    foreach ($exe in @("msedge.exe", "chrome.exe")) {
        $key = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe"
        $path = (Get-ItemProperty -Path $key -Name "(default)" -ErrorAction SilentlyContinue)."(default)"
        if ($path -and (Test-Path $path)) {
            Start-Process -FilePath $path -ArgumentList "--app=$Url"
            return
        }
    }

    # Ни Edge, ни Chrome - открываем чем открывается. Firefox режима приложения
    # не имеет вовсе, и обычная вкладка тут не запасной вариант, а
    # единственный возможный.
    Start-Process $Url
}

if (Test-WebUp -Port $Port) {
    # Уже запущен - второй uvicorn на том же порту просто упал бы с ошибкой
    # «address already in use», а человеку нужен интерфейс, а не сообщение.
    Open-Interface -Url $url
    exit 0
}

# -e, а не -- : с -e аргументы уходят исполняемому файлу напрямую, минуя
# оболочку дистрибутива. Иначе путь с /mnt/d разбирал бы bash, и кавычки
# пришлось бы экранировать дважды.
Start-Process -FilePath "wsl.exe" `
    -ArgumentList @("-d", $Distro, "--cd", $ProjectPath, "-e", $Python, "-m", "web.app") `
    -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if (Test-WebUp -Port $Port) {
        Start-Process $url
        exit 0
    }
    Start-Sleep -Milliseconds 400
}

# Ошибка несёт, что делать дальше (CLAUDE.md): без этой строки человек видит
# молчаливо не открывшийся браузер и не знает, где смотреть причину.
$msg = @"
photo3d: веб-интерфейс не поднялся за $TimeoutSec секунд.

Запусти вручную и посмотри, что пишет:

  wsl -d $Distro --cd $ProjectPath -e $Python -m web.app

Частые причины:
  - дистрибутив WSL называется не "$Distro" (проверь: wsl -l -q)
  - venv переехал: ожидается $Python
  - порт $Port занят другой программой
"@
Add-Type -AssemblyName System.Windows.Forms | Out-Null
[System.Windows.Forms.MessageBox]::Show($msg, "photo3d") | Out-Null
exit 1
