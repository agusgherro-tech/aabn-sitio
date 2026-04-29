@echo off
cd /d C:\AABN\aabn-sitio
git pull origin main
python scripts\generar_portal_servidor.py
