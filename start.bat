@echo off
REM SkladPro.Nod — запуск всего стека одной командой (Windows).
REM Docker + PostgreSQL + Redis + миграции + статика + health-check.
setlocal

where docker >nul 2>&1
if errorlevel 1 (
  echo [ОШИБКА] Docker не найден. Установите Docker Desktop: https://www.docker.com/products/docker-desktop/
  exit /b 1
)

echo ==^> Поднимаю стек (docker compose up --build)...
docker compose up -d --build
if errorlevel 1 (
  echo [ОШИБКА] docker compose не смог подняться.
  exit /b 1
)

echo ==^> Жду готовности приложения (health-check)...
set /a tries=0
:waitloop
curl -s -o nul -w "%%{http_code}" http://localhost:8000/api/v1/core/health/ 2>nul | findstr "200" >nul
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% GEQ 60 (
  echo [ОШИБКА] Приложение не ответило 200 за отведённое время. Логи: docker compose logs web
  exit /b 1
)
timeout /t 2 >nul
goto waitloop

:ready
echo.
echo ==============================================
echo  SkladPro запущен.
echo  Сайт:    http://localhost:8000/
echo  Health:  http://localhost:8000/api/v1/core/health/
echo  Остановить:  docker compose down
echo ==============================================
endlocal
