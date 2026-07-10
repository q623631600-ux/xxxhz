import subprocess, sys, os

# Find python.exe
python_exe = os.path.join(os.path.dirname(sys.executable), 'python.exe')
if not os.path.exists(python_exe):
    python_exe = sys.executable

log = open(r'D:\讲书升级Agent\web_server.log', 'w')

proc = subprocess.Popen(
    [python_exe, '-u', r'D:\讲书升级Agent\web_app.py'],
    stdout=log,
    stderr=subprocess.STDOUT,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True
)
print(f"Launched PID: {proc.pid}")
