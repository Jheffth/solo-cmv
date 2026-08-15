@echo off
title Solo CMV - Controle de Estoque e CMV

echo.
echo ========================================================
echo   SOLO CMV - v0.1.0
echo   Controle de Estoque, Compras e CMV
echo   Unidades: Josefina / Casa Josefina
echo ========================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado. Instale Python 3.11+
    pause
    exit /b 1
)

cd /d "%~dp0backend"

if exist ".deps_ok" (
    echo [1/3] Verificando dependencias...
) else (
    echo [1/3] Instalando dependencias Python ^(primeira vez, pode demorar^)...
    pip install -r requirements.txt
)

python -c "import fastapi, uvicorn, sqlalchemy, jose, bcrypt" >nul 2>&1
if %errorlevel% neq 0 (
    del /q ".deps_ok" >nul 2>&1
    echo.
    echo [ERRO] Dependencias nao instaladas corretamente.
    echo Veja as mensagens acima ^(role para cima^) para o motivo exato.
    echo Dica: confirme que "python" aponta para Python 3.11 a 3.13.
    pause
    exit /b 1
)
echo . > .deps_ok
echo [OK] Dependencias instaladas!

echo [2/3] Inicializando banco de dados...
python seed.py

echo [3/3] Abrindo navegador...
timeout /t 2 /nobreak >nul
start http://localhost:8095

echo.
echo ========================================================
echo  Sistema iniciado! Acesse: http://localhost:8095
echo  Login: Jh3ffth  ^|  Senha: 1601Jcs33@2503
echo  Porta 8000 e 8080 sao do Solo Rotinas - nao usar aqui.
echo  Para encerrar: Ctrl+C
echo ========================================================
echo.

python -m uvicorn main:app --host 127.0.0.1 --port 8095 --reload
if %errorlevel% neq 0 (
    echo.
    echo ========================================================
    echo  [ERRO] O servidor nao conseguiu abrir a porta 8095.
    echo  Isso normalmente e o Windows recusando a porta
    echo  ^(firewall/antivirus, ou faixa reservada pelo Hyper-V/WSL^),
    echo  e nao falta de programa nenhum instalado.
    echo.
    echo  Como resolver:
    echo   1. Tente outra porta: abra backend\.env.example, copie
    echo      para backend\.env e troque PORT=8095 por outra
    echo      ^(ex.: PORT=8096^), depois rode este arquivo de novo.
    echo   2. Ou verifique se a porta esta reservada, rodando no
    echo      Prompt de Comando como Administrador:
    echo      netsh interface ipv4 show excludedportrange protocol=tcp
    echo ========================================================
    pause
)
