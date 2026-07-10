"""Kill old web_app processes and restart"""
import subprocess, sys, os

# Kill old instances
result = subprocess.run(
    ['taskkill', '/F', '/IM', 'python.exe', '/FI', 'PID gt 0'],
    capture_output=True, text=True
)

# Launch new one
python = sys.executable
p = subprocess.Popen(
    [python, '-u', 'D:\\讲书升级Agent\\web_app.py'],
    stdout=open('D:\\讲书升级Agent\\web_server.log', 'w'),
    stderr=subprocess.STDOUT,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True
)
print(f'Launched PID: {p.pid}')
