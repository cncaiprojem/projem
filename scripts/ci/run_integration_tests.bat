@echo off
REM CI Integration Test Runner for Task 7.14 (Windows)
REM This script runs the complete integration test suite with golden artefacts

setlocal EnableDelayedExpansion

REM Configuration
set COMPOSE_FILE=infra\compose\docker-compose.test.yml
set TEST_TIMEOUT=600
set RESULTS_DIR=test_results

REM Colors (Windows 10+)
set RED=[91m
set GREEN=[92m
set YELLOW=[93m
set NC=[0m

REM Default test settings
if "%RUN_SLOW_TESTS%"=="" set RUN_SLOW_TESTS=false
if "%TEST_TURKISH_LOCALE%"=="" set TEST_TURKISH_LOCALE=true
if "%TEST_FILE_UPLOADS%"=="" set TEST_FILE_UPLOADS=true
if "%TEST_ASSEMBLY4%"=="" set TEST_ASSEMBLY4=true
if "%REGENERATE_GOLDEN%"=="" set REGENERATE_GOLDEN=false

REM Parse command line arguments
:parse_args
if "%~1"=="" goto :end_parse
if "%~1"=="--slow" (
    set RUN_SLOW_TESTS=true
    shift
    goto :parse_args
)
if "%~1"=="--no-turkish" (
    set TEST_TURKISH_LOCALE=false
    shift
    goto :parse_args
)
if "%~1"=="--no-uploads" (
    set TEST_FILE_UPLOADS=false
    shift
    goto :parse_args
)
if "%~1"=="--no-assembly" (
    set TEST_ASSEMBLY4=false
    shift
    goto :parse_args
)
if "%~1"=="--regenerate-golden" (
    set REGENERATE_GOLDEN=true
    shift
    goto :parse_args
)
if "%~1"=="--help" (
    echo Usage: %0 [options]
    echo Options:
    echo   --slow               Run slow tests
    echo   --no-turkish        Skip Turkish locale tests
    echo   --no-uploads        Skip file upload tests
    echo   --no-assembly       Skip Assembly4 tests
    echo   --regenerate-golden Regenerate golden artefacts
    echo   --help              Show this help message
    exit /b 0
)
echo %RED%Unknown option: %~1%NC%
exit /b 1
:end_parse

REM Create results directory
if not exist "%RESULTS_DIR%" mkdir "%RESULTS_DIR%"

echo %GREEN%[INFO]%NC% Starting integration test environment...

REM Build test images
echo %GREEN%[INFO]%NC% Building test images...
docker compose -f %COMPOSE_FILE% build --no-cache
if errorlevel 1 (
    echo %RED%[ERROR]%NC% Failed to build test images
    exit /b 1
)

REM Start services
echo %GREEN%[INFO]%NC% Starting test services...
docker compose -f %COMPOSE_FILE% up -d postgres_test redis_test minio_test rabbitmq_test freecad_test
if errorlevel 1 (
    echo %RED%[ERROR]%NC% Failed to start services
    exit /b 1
)

REM Wait for services to be healthy
echo %GREEN%[INFO]%NC% Waiting for services to be healthy...
set TIMEOUT=60
set ELAPSED=0

:health_check_loop
docker compose -f %COMPOSE_FILE% ps | findstr "unhealthy starting" >nul
if errorlevel 1 (
    echo.
    echo %GREEN%[INFO]%NC% All services are healthy!
    goto :services_ready
)
timeout /t 5 /nobreak >nul
set /a ELAPSED+=5
if %ELAPSED% LSS %TIMEOUT% (
    echo|set /p=.
    goto :health_check_loop
)

echo.
echo %RED%[ERROR]%NC% Services failed to become healthy within %TIMEOUT% seconds
docker compose -f %COMPOSE_FILE% ps
exit /b 1

:services_ready

REM Initialize MinIO buckets
echo %GREEN%[INFO]%NC% Initializing MinIO buckets...
docker compose -f %COMPOSE_FILE% exec -T minio_test mc alias set local http://localhost:9000 minioadmin minioadmin
docker compose -f %COMPOSE_FILE% exec -T minio_test mc mb local/test-artefacts --ignore-existing
docker compose -f %COMPOSE_FILE% exec -T minio_test mc mb local/test-golden --ignore-existing
docker compose -f %COMPOSE_FILE% exec -T minio_test mc mb local/test-logs --ignore-existing

REM Initialize RabbitMQ queues
echo %GREEN%[INFO]%NC% Initializing RabbitMQ queues...
docker compose -f %COMPOSE_FILE% exec -T rabbitmq_test rabbitmqctl await_startup

REM Regenerate golden artefacts if requested
if "%REGENERATE_GOLDEN%"=="true" (
    echo %GREEN%[INFO]%NC% Regenerating golden artefacts...
    docker compose -f %COMPOSE_FILE% run --rm test_runner python tools/gen_golden.py --regenerate
)

REM Run integration tests
echo %GREEN%[INFO]%NC% Running integration tests...
docker compose -f %COMPOSE_FILE% run --rm test_runner
set TEST_EXIT_CODE=%errorlevel%

REM Copy test results
echo %GREEN%[INFO]%NC% Collecting test results...
for /f "tokens=*" %%i in ('docker compose -f %COMPOSE_FILE% ps -q test_runner 2^>nul') do set CONTAINER_ID=%%i
if not "%CONTAINER_ID%"=="" (
    docker cp %CONTAINER_ID%:/test_results/. %RESULTS_DIR%/ 2>nul
)

REM Print test summary
if exist "%RESULTS_DIR%\junit.xml" (
    echo %GREEN%[INFO]%NC% Test results available in %RESULTS_DIR%\junit.xml
)

if exist "%RESULTS_DIR%\coverage.xml" (
    echo %GREEN%[INFO]%NC% Coverage report available in %RESULTS_DIR%\coverage.xml
)

REM Cleanup
echo %GREEN%[INFO]%NC% Cleaning up test environment...
docker compose -f %COMPOSE_FILE% down -v --remove-orphans

REM Check test exit code
if %TEST_EXIT_CODE%==0 (
    echo %GREEN%[INFO]%NC% All tests passed successfully!
) else (
    echo %RED%[ERROR]%NC% Tests failed with exit code: %TEST_EXIT_CODE%
)

exit /b %TEST_EXIT_CODE%