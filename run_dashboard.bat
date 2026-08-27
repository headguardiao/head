@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Ambiente virtual nao encontrado. Rode primeiro:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

if not exist ".env" (
    echo Arquivo .env nao encontrado. Copie .env.example para .env e preencha FORGE_ENCRYPTION_KEY.
    pause
    exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "line=%%a"
    if not "!line!"=="" if not "!line:~0,1!"=="#" set "%%a=%%b"
)

echo Iniciando o FORGE dashboard em http://localhost:8080/dashboard
echo NAO FECHE ESTA JANELA - fechar ela para o servidor. Se der erro, o texto
echo vai ficar na tela (esta janela so fecha se voce apertar uma tecla).
echo.
start "" cmd /c "timeout /t 2 >nul && start http://localhost:8080/dashboard"
python -m forge.app
echo.
echo ==========================================================
echo O servidor parou (codigo de saida: %errorlevel%).
echo Se isso foi inesperado, tire um print desta janela e mostre.
echo ==========================================================
pause
