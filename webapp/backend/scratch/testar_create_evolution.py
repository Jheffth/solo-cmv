import sys
import paramiko
import json

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

# 1. Cria a instância solo_cmv
payload = {
    "instanceName": "solo_cmv",
    "token": "solo_cmv_secret_token_2026",
    "qrcode": True,
    "integration": "WHATSAPP-BAILEYS"
}

cmd_create = f'curl -s -X POST -H "apikey: solo-cmv-evolution-key-2026" -H "Content-Type: application/json" -d \'{json.dumps(payload)}\' http://localhost:8080/instance/create'
_, out_c, _ = ssh.exec_command(cmd_create)
print("=== CREATE INSTANCE RESPONSE ===")
print(out_c.read().decode('utf-8'))

# 2. Conecta
cmd_conn = 'curl -s -H "apikey: solo-cmv-evolution-key-2026" http://localhost:8080/instance/connect/solo_cmv'
_, out_conn, _ = ssh.exec_command(cmd_conn)
print("\n=== CONNECT INSTANCE RESPONSE ===")
print(out_conn.read().decode('utf-8'))

ssh.close()
