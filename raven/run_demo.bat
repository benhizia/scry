@echo off
rem ===========================================================================
rem  RAVEN : demo complete sous Windows, en une commande.
rem
rem    run_demo.bat              construit, lance la chaine et le visualiseur
rem    run_demo.bat --no-view    sans IHM : simulateur et enregistreur seuls
rem
rem  ETAPES
rem    1. prepare le venv comme scry_console.bat (scry est appele par le build
rem       pour generer la glue de la demo) ;
rem    2. cmake configure et construit raven en Release (Visual Studio 2022) ;
rem    3. lance demo_sim et raven dans deux fenetres, puis raven-view ici.
rem
rem  Dans le visualiseur : colonne Enr. pour choisir les champs, bouton D pour
rem  le declencheur, Armer pour enregistrer, Sent. pour les sentinelles.
rem  g_flight.gear_down ne passe a true qu'une seule trame au milieu du vol :
rem  c'est ce que la sentinelle doit attraper.
rem
rem  A la fermeture du visualiseur, les deux fenetres sont arretees.
rem
rem  PREREQUIS : Visual Studio 2022 (outils C++), CMake 3.16 ou plus, castxml
rem  (dans le PATH ou via [paths] castxml de scry.ini), et les sources d'ImGui
rem  dans third_party\imgui pour raven-view (voir third_party\README.md).
rem  Sans IHM : cmake -S raven -B build\raven -DRAVEN_VIEW=OFF
rem ===========================================================================

cd /d "%~dp0.."
set "SCRY_RC=1"
set "BUILD=%~dp0..\build\raven"

call "%~dp0..\scry_console.bat" setup
if errorlevel 1 goto :fin

echo.
echo [raven] 1/3 cmake
cmake -S "%~dp0." -B "%BUILD%" -G "Visual Studio 17 2022" -A x64 ^
      -DPython3_EXECUTABLE="%SCRY_VENV%\Scripts\python.exe"
if errorlevel 1 goto :fin

echo.
echo [raven] 2/3 compilation
cmake --build "%BUILD%" --config Release
if errorlevel 1 goto :fin

echo.
echo [raven] 3/3 demo : simulateur, enregistreur, visualiseur
start "demo_sim" "%BUILD%\Release\demo_sim.exe" --name demo
start "raven" "%BUILD%\Release\raven.exe" --desc "%BUILD%\demo_gen\demo.rvndesc" --source shm:demo
rem Laisser l'enregistreur ouvrir son port avant que le visualiseur s'y connecte.
ping -n 3 127.0.0.1 >nul

rem --no-view sert a l'automatisation : on rend la main tout de suite, sans
rem ouvrir de console interactive.
if /i "%~1"=="--no-view" (
  echo [raven] --no-view : demo_sim et raven tournent dans leurs fenetres.
  echo [raven] Les arreter : taskkill /IM raven.exe /F puis /IM demo_sim.exe /F
  exit /b 0
)

"%BUILD%\Release\raven-view.exe"
set "SCRY_RC=%ERRORLEVEL%"
taskkill /IM raven.exe /F >nul 2>&1
taskkill /IM demo_sim.exe /F >nul 2>&1
echo [raven] visualiseur ferme, simulateur et enregistreur arretes.

:fin
if not defined SCRY_CONSOLE echo [scry] Console Scry prete : 'aide' pour les commandes.
call "%~dp0..\scry_console.bat" shell
exit /b %SCRY_RC%
