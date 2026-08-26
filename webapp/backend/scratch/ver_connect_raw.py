import sys
import paramiko
import json

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

cmd1 = 'docker exec solo_cmv_app python -c "import urllib.request; req = urllib.request.Request(\'http://whatsapp:8080/instance/connect/solo_cmv\', headers={\'apikey\':\'solo-cmv-evolution-key-2026\'}); print(urllib.request.urlopen(req).read().decode())"'
_, out1, _ = ssh.exec_command(cmd1)
print("CONNECT RAW:\n", out1.read().decode('utf-8'))

cmd2 = 'docker logs --tail 30 solo_cmv_whatsapp'
_, out2, _ = ssh.exec_command(cmd2)
print("\nLOGS WHATSAPP:\n", out2.read().decode('utf-8', errors='replace'))

ssh.close()
