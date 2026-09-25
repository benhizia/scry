@echo off
rem ===========================================================================
rem  Demo d'autotest Python embarque dans une application C++ sequencee.
rem
rem    run_demo.bat                  tous les scenarios de demo\scenarios
rem    run_demo.bat montee           seulement ceux dont le nom ou un tag
rem                                  contient 'montee'
rem
rem  ETAPES
rem    1. prepare le venv comme scry_console.bat ;
rem    2. scry gen --pybind sur demo\legacy_app.h, sortie dans
rem       demo\build\generated : bindings, module sut genere (types et
rem       variables globales), stub sut.pyi, fragment CMake ;
rem    3. cmake configure et construit demo\legacy_app.exe en Release avec
rem       LEGACY_AUTOTEST=ON : l'interpreteur Python est embarque dans l'exe ;
rem    4. lance l'exe. A chaque cycle, apres le code metier, l'etape autotest
rem       fait avancer les scenarios Python. Code de sortie : 0 si tout passe,
rem       1 si un scenario echoue, 2 si l'autotest lui-meme plante.
rem
rem  Le scenario test_echec_volontaire.py echoue expres : il montre un echec
rem  dans le rapport sans arreter l'application. Rapport JUnit :
rem  demo\build\autotest-report.xml.
rem
rem  PREREQUIS : Visual Studio 2022 (outils C++), CMake 3.20 ou plus, castxml,
rem  et pybind11 dans le venv (extra dev ou pybind de pyproject.toml).
rem ===========================================================================

cd /d "%~dp0"
set "SCRY_RC=1"
set "DEMO_BUILD=%~dp0demo\build"

call "%~dp0..\scry_console.bat" setup
if errorlevel 1 goto :fin

echo.
echo [autotest] 1/3 scry gen --pybind
set "SCRY_PATHS_OUTPUT=%DEMO_BUILD%\generated"
rem legacy_app.h inclut Data\test_structs_complexe.h : -I pour castxml. Un
rem header en echec arrete tout plutot que de generer un module incomplet.
set "SCRY_CASTXML_INCLUDE_PATHS=%~dp0..\Data"
set "SCRY_INTROSPECTION_STOP_ON_ERROR=true"
"%SCRY_VENV%\Scripts\scry.exe" gen --pybind -H "%~dp0demo\legacy_app.h" -H "%~dp0..\Data\test_structs_complexe.h"
set "GEN_RC=%ERRORLEVEL%"
set "SCRY_PATHS_OUTPUT="
set "SCRY_CASTXML_INCLUDE_PATHS="
set "SCRY_INTROSPECTION_STOP_ON_ERROR="
if not "%GEN_RC%"=="0" goto :fin

echo.
echo [autotest] 2/3 cmake
cmake -S "%~dp0demo" -B "%DEMO_BUILD%" -DLEGACY_AUTOTEST=ON ^
      -DSCRY_GENERATED_DIR="%DEMO_BUILD%\generated" ^
      -DPython_EXECUTABLE="%SCRY_VENV%\Scripts\python.exe"
if errorlevel 1 goto :fin
cmake --build "%DEMO_BUILD%" --config Release
if errorlevel 1 goto :fin

rem python312.dll est dans l'installation de base du venv : on l'ajoute au
rem PATH de l'exe, et AUTOTEST_VENV lui indique le venv (numpy...).
"%SCRY_VENV%\Scripts\python.exe" -c "import sys; print(sys.base_prefix)" > "%DEMO_BUILD%\python_home.txt"
set /p PY_HOME=<"%DEMO_BUILD%\python_home.txt"
set "PATH=%PY_HOME%;%PATH%"
set "AUTOTEST_VENV=%SCRY_VENV%"

echo.
echo [autotest] 3/3 legacy_app.exe %*
pushd "%DEMO_BUILD%"
"%DEMO_BUILD%\Release\legacy_app.exe" %*
set "SCRY_RC=%ERRORLEVEL%"
popd
echo.
echo [autotest] code de sortie %SCRY_RC% (0 tout passe, 1 echec de scenario, 2 erreur autotest)

:fin
if not defined SCRY_CONSOLE echo [scry] Console Scry prete : 'aide' pour les commandes.
call "%~dp0..\scry_console.bat" shell
exit /b %SCRY_RC%
