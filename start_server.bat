@echo off
title 讲书升级Agent
cd /d D:\讲书升级Agent
python -u web_app.py > web_server.log 2>&1
exit
