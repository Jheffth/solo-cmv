import sys
import paramiko

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

cmd = 'docker exec solo_cmv_app python -c "import urllib.request, json; req = urllib.request.Request(\'http://whatsapp:8080/instance/create\', data=json.dumps({\'instanceName\':\'solo_cmv\',\'qrcode\':True,\'integration\':\'WHATSAPP-BAILEYS\'}).encode(), headers={\'apikey\':\'solo-cmv-evolution-key-2026\',\'Content-Type\':\'application/json\'}); print(urllib.request.urlopen(req).read().decode())"'
_, out, err = ssh.exec_command(cmd)
print("APP -> WHATSAPP CREATE:")
print(out.read().decode('utf-8'))
print(err.read().decode('utf-8'))

cmd2 = 'docker exec solo_cmv_app python -c "import urllib.request; req = urllib.request.Request(\'http://whatsapp:8080/instance/connect/solo_cmv\', headers={\'apikey\':\'solo-cmv-evolution-key-2026\'}); print(urllib.request.urlopen(req).read().decode())"'
_, out2, err2 = ssh.exec_command(cmd2)
print("APP -> WHATSAPP CONNECT:")
print(out2.read().decode('utf-8'))
print(err2.read().decode('utf-8'))

ssh.close()
