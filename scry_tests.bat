@echo off
rem ===========================================================================
rem  Scry - lancement des tests
rem
rem  Prepare le venv exactement comme scry_console.bat (creation et
rem  installation au premier lancement seulement), lance pytest, puis laisse
rem  la console ouverte avec le venv actif pour enchainer.
rem
rem    scry_tests.bat                  tous les tests de tests\
rem    scry_tests.bat -k padding       les arguments sont transmis a pytest
rem    scry_tests.bat -x -q            arret au premier echec, sortie courte
rem
rem  Ces tests portent sur le modele, le decodage memoire et la generation C++.
rem  Ils ne lancent ni castxml ni MSVC : pour valider la chaine complete sur ce
rem  poste, utiliser 'scry check' puis 'scry dump' dans la console.
rem
rem  La configuration de pytest est dans pyproject.toml, [tool.pytest.ini_options].
rem  Depuis une console Scry deja ouverte, taper simplement : tests
rem ===========================================================================

cd /d "%~dp0"
set "SCRY_RC=1"

call "%~dp0scry_console.bat" setup
if errorlevel 1 goto :fin

echo.
echo [scry] python -m pytest %*
"%SCRY_VENV%\Scripts\python.exe" -m pytest %*
set "SCRY_RC=%ERRORLEVEL%"
echo.
if "%SCRY_RC%"=="0" (echo [scry] Tests OK.) else (echo [scry] Tests en ECHEC, code %SCRY_RC%.)

:fin
if not defined SCRY_CONSOLE echo [scry] Console Scry prete : 'aide' pour les commandes, 'tests' pour relancer.
call "%~dp0scry_console.bat" shell
exit /b %SCRY_RC%
