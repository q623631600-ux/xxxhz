with open('web/static/app.js', 'r', encoding='utf-8') as f:
    c = f.read()

# The problematic line 102 ends with: + kpId + '\">';
# Replace the ending to avoid the \" ambiguity
# New ending: + kpId + '">'
old = """ + kpId + '\\">'"""
new = """ + kpId + '">'"""
c = c.replace(old, new)

with open('web/static/app.js', 'w', encoding='utf-8') as f:
    f.write(c)

# Verify
import subprocess
r = subprocess.run(['node', '--check', 'web/static/app.js'], capture_output=True, text=True)
if r.returncode == 0:
    print('FIX CONFIRMED: Node.js check passed')
else:
    print('STILL FAILS:', r.stderr[:200])
