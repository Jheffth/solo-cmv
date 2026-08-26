import sys
import paramiko

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

cmd = 'docker logs --tail 80 solo_cmv_whatsapp'
_, out, _ = ssh.exec_command(cmd)
print("=== LOGS EVOLUTION API ===")
print(out.read().decode('utf-8', errors='replace'))

ssh.close()
