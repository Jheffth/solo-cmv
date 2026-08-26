import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

# 1. Logs da Evolution API
cmd1 = 'docker logs --tail 40 solo_cmv_whatsapp'
_, out1, _ = ssh.exec_command(cmd1)
print("=== LOGS EVOLUTION API ===")
print(out1.read().decode('utf-8', errors='replace'))

# 2. Testa conexão direta na Evolution API no servidor
cmd2 = 'curl -s -H "apikey: solo-cmv-evolution-key-2026" http://localhost:8080/instance/connectionState/solo_cmv'
_, out2, _ = ssh.exec_command(cmd2)
print("\n=== ESTADO DA INSTÂNCIA ===")
print(out2.read().decode('utf-8'))

# 3. Testa /instance/connect/solo_cmv
cmd3 = 'curl -s -H "apikey: solo-cmv-evolution-key-2026" http://localhost:8080/instance/connect/solo_cmv'
_, out3, _ = ssh.exec_command(cmd3)
raw3 = out3.read().decode('utf-8')
try:
    dados3 = json.loads(raw3)
    print("\n=== RESPOSTA CONNECT ===")
    print("code:", bool(dados3.get("code")))
    print("base64 length:", len(dados3.get("base64") or ""))
    print("base64 prefix:", (dados3.get("base64") or "")[:40])
    print("count:", dados3.get("count"))
except Exception as e:
    print("Erro parse:", e, raw3)

ssh.close()
