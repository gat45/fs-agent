@echo off
REM Lance l'agent de scan/comparaison de systeme de fichiers.
REM Par defaut, scanne tous les disques disponibles.
REM Toutes les sorties vont dans E:\ (aucun fichier dans C:).
cd /d E:\agent_fs
if "%~1"=="" (
    python cli.py --all-drives %*
) else (
    python cli.py %*
)
pause