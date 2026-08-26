import sys
import paramiko
import json

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

# 1. Containers ativos
cmd0 = 'docker ps --filter name=solo_cmv --format "table {{.Names}}\t{{.Status}}"'
_, out0, _ = ssh.exec_command(cmd0)
print("=== CONTAINERS ===")
print(out0.read().decode('utf-8'))

# 2. Logs da Evolution API
cmd1 = 'docker logs --tail 25 solo_cmv_whatsapp'
_, out1, _ = ssh.exec_command(cmd1)
print("=== LOGS EVOLUTION API ===")
print(out1.read().decode('utf-8', errors='replace'))

# 3. Testa /instance/connect/solo_cmv
cmd3 = 'curl -s -H "apikey: solo-cmv-evolution-key-2026" http://localhost:8080/instance/connect/solo_cmv'
_, out3, _ = ssh.exec_command(cmd3)
raw3 = out3.read().decode('utf-8')
try:
    dados3 = json.loads(raw3)
    print("\n=== RESPOSTA CONNECT ===")
    print("code:", bool(dados3.get("code")))
    print("base64 length:", len(dados3.get("base64") or ""))
    print("count:", dados3.get("count"))
    print("estado:", dados3.get("state") or dados3.get("status"))
except Exception as e:
    print("Erro parse:", e, raw3)

ssh.close()
