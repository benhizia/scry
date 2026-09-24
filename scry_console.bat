@echo off
rem ===========================================================================
rem  Scry - console de travail
rem
rem  Double-cliquer ce fichier ouvre une console prete a l'emploi : venv actif,
rem  commande 'scry' disponible, scry.ini present. Taper 'aide' dans la console
rem  reaffiche la liste des commandes, 'tests' lance les tests.
rem
rem  PREMIER LANCEMENT (deploiement)
rem    1. cherche Python 3.9 ou plus : lanceur 'py -3', sinon 'python' du PATH ;
rem    2. cree le venv dans .venv, ou dans le dossier donne par SCRY_VENV ;
rem    3. pip install -e ".[ui,dev]" : installation EDITABLE, le code de src\
rem       est utilise en place. Modifier un .py ne demande aucune reinstallation ;
rem    4. copie scry.ini.example en scry.ini s'il manque. Le renseigner ensuite :
rem       chemin de castxml s'il n'est pas dans le PATH, headers a parser.
rem
rem  LANCEMENTS SUIVANTS
rem    Rien n'est reinstalle. pip n'est relance que si pyproject.toml a change
rem    depuis la derniere installation (nouvelle dependance, nouveau point
rem    d'entree), ou sur demande. La comparaison se fait avec la copie
rem    .venv\scry_pyproject.stamp posee apres chaque installation reussie.
rem
rem    scry_console.bat              prepare si besoin, puis ouvre la console
rem    scry_console.bat reinstall    force pip install -e ".[ui,dev]"
rem    scry_console.bat setup        prepare seulement, sans console
rem    scry_console.bat aide         affiche la liste des commandes
rem
rem  Relance depuis une console Scry deja ouverte : le venv n'est pas reactive
rem  et aucune console imbriquee n'est ouverte.
rem
rem  PREREQUIS NON INSTALLES PAR CE SCRIPT
rem    - castxml 0.6 ou plus, dans le PATH ou via [paths] castxml de scry.ini ;
rem    - Visual Studio 2022 avec les outils C++, detecte par vswhere.
rem    'scry check' verifie les deux.
rem
rem  REPARTIR DE ZERO : supprimer le dossier .venv puis relancer ce script.
rem ===========================================================================

cd /d "%~dp0"
if not defined SCRY_VENV set "SCRY_VENV=%~dp0.venv"

if /i "%~1"=="aide" goto :aide
if /i "%~1"=="shell" goto :shell

call :setup "%~1"
if errorlevel 1 goto :echec
if /i "%~1"=="setup" exit /b 0
call :aide
goto :shell


rem ---------------------------------------------------------------------------
rem  Preparation : venv, activation, dependances, scry.ini
rem ---------------------------------------------------------------------------
:setup
set "SCRY_PY=%SCRY_VENV%\Scripts\python.exe"
set "SCRY_STAMP=%SCRY_VENV%\scry_pyproject.stamp"

if exist "%SCRY_PY%" goto :venv_ok
call :find_python
if errorlevel 1 exit /b 1
echo [scry] Creation du venv : %SCRY_VENV%
%SCRY_BASEPY% -m venv "%SCRY_VENV%"
if errorlevel 1 exit /b 1

:venv_ok
rem Rentrance : venv deja actif dans cette console, on ne le reactive pas.
if /i "%VIRTUAL_ENV%"=="%SCRY_VENV%" goto :active
call "%SCRY_VENV%\Scripts\activate.bat"
:active

if /i "%~1"=="reinstall" goto :install
if not exist "%SCRY_VENV%\Scripts\scry.exe" goto :install
rem Venv deja equipe mais anterieur a ce script : on pose la reference sans
rem reinstaller.
if not exist "%SCRY_STAMP%" copy /y "pyproject.toml" "%SCRY_STAMP%" >nul
fc /b "pyproject.toml" "%SCRY_STAMP%" >nul 2>&1
if errorlevel 1 goto :install_changed
goto :config

:install_changed
echo [scry] pyproject.toml a change depuis la derniere installation.
:install
echo [scry] Installation des dependances : pip install -e ".[ui,dev]"
"%SCRY_PY%" -m pip install --quiet --upgrade pip
"%SCRY_PY%" -m pip install -e ".[ui,dev]"
if errorlevel 1 exit /b 1
copy /y "pyproject.toml" "%SCRY_STAMP%" >nul

:config
if exist "scry.ini" exit /b 0
copy "scry.ini.example" "scry.ini" >nul
echo [scry] scry.ini cree depuis scry.ini.example, a renseigner.
exit /b 0


rem ---------------------------------------------------------------------------
rem  Recherche d'un Python de base pour creer le venv
rem ---------------------------------------------------------------------------
:find_python
set "SCRY_BASEPY="
where py >nul 2>&1 && set "SCRY_BASEPY=py -3"
if not defined SCRY_BASEPY where python >nul 2>&1 && set "SCRY_BASEPY=python"
if not defined SCRY_BASEPY goto :no_python
%SCRY_BASEPY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 goto :old_python
exit /b 0

:no_python
echo [scry] Python introuvable. Installer Python 3.9 ou plus depuis python.org,
echo        en cochant le lanceur py.
exit /b 1

:old_python
echo [scry] Python 3.9 minimum requis, trouve :
%SCRY_BASEPY% --version
exit /b 1


rem ---------------------------------------------------------------------------
rem  Aide et console interactive
rem ---------------------------------------------------------------------------
:aide
echo.
echo  ============================== Scry ==============================
echo   venv   : %VIRTUAL_ENV%
echo   config : %~dp0scry.ini
echo.
echo   scry check                  config, castxml et MSVC
echo   scry dump                   arbre des structures des headers de scry.ini
echo   scry dump -v                idem, avec origine des types et doublons
echo   scry dump -H Data\x.h       autre header, -H cumulable, glob accepte
echo   scry gen                    ecrit Generated\introspection.generated.h
echo   scry json modele.json       exporte le modele brut
echo   scry ui                     visualiseur ImGui
echo   scry verify                 compile les assertions ABI avec cl, release et debug
echo   scry producer --run         publie le motif de demo en memoire partagee
echo   scry watch                  affiche en continu les valeurs publiees
echo   scry --help                 toutes les options
echo.
echo   tests                       lance les tests, arguments pour pytest
echo   viewer                      compile et lance le visualiseur C++ natif
echo   aide                        reaffiche cette liste
echo   scry_console.bat reinstall  reinstalle les dependances
echo   exit                        ferme la console
echo  ==================================================================
echo.
exit /b 0

:shell
doskey aide="%~f0" aide
doskey tests="%~dp0scry_tests.bat" $*
doskey viewer="%~dp0scry_viewer.bat" $*
if defined SCRY_CONSOLE exit /b 0
set "SCRY_CONSOLE=1"
cmd /k
exit /b 0

:echec
echo.
echo [scry] Preparation interrompue, voir le message ci-dessus.
if /i "%~1"=="setup" exit /b 1
if not defined SCRY_CONSOLE cmd /k
exit /b 1
