import sys
import paramiko
import time

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

# 1. Reinicia container whatsapp e redis para limpar sockets em memória
cmd_restart = 'docker restart solo_cmv_redis solo_cmv_whatsapp'
_, out_r, _ = ssh.exec_command(cmd_restart)
print("RESTART CONTAINERS:", out_r.read().decode('utf-8'))

time.sleep(5)

# 2. Cria a instância solo_cmv
cmd_create = 'docker exec solo_cmv_app python -c "import urllib.request, json; req = urllib.request.Request(\'http://whatsapp:8080/instance/create\', data=json.dumps({\'instanceName\':\'solo_cmv\',\'qrcode\':True,\'integration\':\'WHATSAPP-BAILEYS\'}).encode(), headers={\'apikey\':\'solo-cmv-evolution-key-2026\',\'Content-Type\':\'application/json\'}); print(urllib.request.urlopen(req).read().decode())"'
_, out_c, _ = ssh.exec_command(cmd_create)
print("CREATE INSTANCE:\n", out_c.read().decode('utf-8'))

time.sleep(3)

# 3. Connect
cmd_conn = 'docker exec solo_cmv_app python -c "import urllib.request, json; req = urllib.request.Request(\'http://whatsapp:8080/instance/connect/solo_cmv\', headers={\'apikey\':\'solo-cmv-evolution-key-2026\'}); d = json.loads(urllib.request.urlopen(req).read().decode()); print(\'Sucesso! Base64 len:\', len(d.get(\'base64\') or \'\'), \'Count:\', d.get(\'count\'))"'
_, out_conn, err_conn = ssh.exec_command(cmd_conn)
print("CONNECT INSTANCE:\n", out_conn.read().decode('utf-8'), err_conn.read().decode('utf-8'))

ssh.close()
