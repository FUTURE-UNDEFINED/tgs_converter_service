@echo off
setlocal

REM Директория, куда будут помещены сгенерированные файлы
set "OUT_DIR=generated_pb2"
REM Корневая директория для .proto файлов
set "PROTO_DIR=proto"
REM Конкретный proto файл для генерации (путь относительно PROTO_DIR)
set "TARGET_PROTO_FILE=v1\telegram_stickers_converter\telegram_stickers_converter.proto"

REM Полный путь к proto файлу
set "FULL_PROTO_PATH=%PROTO_DIR%\%TARGET_PROTO_FILE%"

REM Создаем выходную директорию, если ее нет
if not exist "%OUT_DIR%" (
    echo Creating directory: %OUT_DIR%
    mkdir "%OUT_DIR%"
)

echo Generating Python gRPC stubs for %FULL_PROTO_PATH%...

REM Команда для генерации
REM python -m grpc_tools.protoc вызывает компилятор protobuf с плагинами для Python и gRPC
python -m grpc_tools.protoc ^
    -I"%PROTO_DIR%" ^
    --python_out="%OUT_DIR%" ^
    --pyi_out="%OUT_DIR%" ^
    --grpc_python_out="%OUT_DIR%" ^
    "%FULL_PROTO_PATH%"

REM Проверка на ошибку после выполнения protoc
if errorlevel 1 (
    echo ERROR: protoc execution failed. Check the messages above.
    exit /b %errorlevel%
)

echo Creating __init__.py files to make generated directories Python packages...

REM protoc создаст поддиректории в OUT_DIR, соответствующие 'package' в .proto
REM например, generated_pb2\v1\telegram_stickers_converter\
REM Нам нужны __init__.py в generated_pb2, generated_pb2\v1, и generated_pb2\v1\telegram_stickers_converter

REM Создаем __init__.py в корневой папке generated_pb2
if not exist "%OUT_DIR%\__init__.py" (
    echo Creating %OUT_DIR%\__init__.py
    type NUL > "%OUT_DIR%\__init__.py"
)

REM Рекурсивно создаем __init__.py во всех поддиректориях OUT_DIR, созданных protoc.
REM Этот цикл пройдет по всем папкам внутри %OUT_DIR%
for /D /R "%OUT_DIR%" %%d in (*) do (
    if not exist "%%d\__init__.py" (
        echo Creating __init__.py in %%d
        type NUL > "%%d\__init__.py"
    )
)


echo Generation complete. Files are in %OUT_DIR%\
echo You should now be able to import them in your Python code, e.g.:
echo from generated_pb2.v1.telegram_stickers_converter import telegram_stickers_converter_pb2
echo from generated_pb2.v1.telegram_stickers_converter import telegram_stickers_converter_pb2_grpc

endlocal