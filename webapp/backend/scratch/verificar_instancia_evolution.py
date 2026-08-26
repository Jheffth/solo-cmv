import sys
import paramiko
import json

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

# 1. Fetch instances
cmd1 = 'curl -s -H "apikey: solo-cmv-evolution-key-2026" http://localhost:8080/instance/fetchInstances'
_, out1, _ = ssh.exec_command(cmd1)
print("=== FETCH INSTANCES ===")
print(out1.read().decode('utf-8'))

# 2. Connection state
cmd2 = 'curl -s -H "apikey: solo-cmv-evolution-key-2026" http://localhost:8080/instance/connectionState/solo_cmv'
_, out2, _ = ssh.exec_command(cmd2)
print("\n=== CONNECTION STATE ===")
print(out2.read().decode('utf-8'))

# 3. Connect solo_cmv
cmd3 = 'curl -s -H "apikey: solo-cmv-evolution-key-2026" http://localhost:8080/instance/connect/solo_cmv'
_, out3, _ = ssh.exec_command(cmd3)
print("\n=== CONNECT solo_cmv ===")
print(out3.read().decode('utf-8'))

# 4. Logs
cmd4 = 'docker logs --tail 30 solo_cmv_whatsapp'
_, out4, _ = ssh.exec_command(cmd4)
print("\n=== LOGS solo_cmv_whatsapp ===")
print(out4.read().decode('utf-8', errors='replace'))

ssh.close()
