import sys
import paramiko

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

cmd = 'curl -i -X POST http://localhost:8080/instance/create -H "apikey: solo-cmv-evolution-key-2026" -H "Content-Type: application/json" -d \'{"instanceName":"solo_cmv","token":"solo123","qrcode":true,"integration":"WHATSAPP-BAILEYS"}\''
_, out, err = ssh.exec_command(cmd)
print("OUT:\n", out.read().decode('utf-8'))
print("ERR:\n", err.read().decode('utf-8'))

ssh.close()
