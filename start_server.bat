@echo off
cd /d D:\讲书升级Agent
start /min python -u web_app.py > web_server.log 2>&1
exit
