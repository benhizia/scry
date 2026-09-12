@echo off
rem ===========================================================================
rem  Scry - visualiseur C++ natif
rem
rem  Compile le header genere par Scry dans un vrai executable ImGui, puis le
rem  lance. L'IHM Python montre ce que Scry a compris des headers ; cet exe
rem  montre ce que le COMPILATEUR en fait : il inclut les static_assert d'ABI
rem  et dessine les structures avec les fonctions generees.
rem
rem    scry_viewer.bat                   compile et lance
rem    scry_viewer.bat -H Data\x.h       arguments transmis a 'scry viewer'
rem
rem  PREMIER LANCEMENT
rem    - prepare le venv comme scry_console.bat ;
rem    - clone Dear ImGui dans third_party\imgui, au tag [viewer] imgui_tag
rem      de scry.ini (git requis). pyimgui n'embarque pas les sources C++ ;
rem    - compile les objets ImGui une fois pour toutes, par jeu d'options.
rem  Lancements suivants : seul le visualiseur est recompile, en secondes.
rem
rem  SORTIE : build\viewer\scry_viewer.exe, ou [viewer] build_dir.
rem
rem  COHERENCE : l'exe est compile avec le runtime de [castxml] cl_flags, /MD
rem  a defaut, c'est-a-dire dans la configuration que le modele decrit. Si la
rem  compilation casse sur un static_assert, le modele ne correspond pas a
rem  cette configuration : voir 'scry verify'.
rem
rem  Dans l'exe, le mode 'motif de demo' lit les memes octets que l'IHM
rem  Python en mode demo : les valeurs affichees doivent coincider.
rem
rem  PREREQUIS : Visual Studio 2022 avec les outils C++ et le Windows SDK
rem  (DirectX 11), castxml, git. 'scry check' verifie les deux premiers.
rem ===========================================================================

cd /d "%~dp0"
set "SCRY_RC=1"

call "%~dp0scry_console.bat" setup
if errorlevel 1 goto :fin

echo.
echo [scry] scry viewer --run %*
"%SCRY_VENV%\Scripts\scry.exe" viewer --run %*
set "SCRY_RC=%ERRORLEVEL%"
echo.
if "%SCRY_RC%"=="0" (echo [scry] Visualiseur compile et lance.) else (echo [scry] Echec, code %SCRY_RC%. Voir les erreurs ci-dessus.)

:fin
if not defined SCRY_CONSOLE echo [scry] Console Scry prete : 'aide' pour les commandes, 'viewer' pour recompiler.
call "%~dp0scry_console.bat" shell
exit /b %SCRY_RC%
