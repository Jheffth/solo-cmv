import time
import json
import urllib.request

url_login = "https://solocmv.duckdns.org/api/auth/login"
data_login = json.dumps({"login": "Jh3ffth", "senha": "1601Jcs332503"}).encode()
req_login = urllib.request.Request(url_login, data=data_login, headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req_login) as resp:
    token = json.loads(resp.read().decode()).get("access_token")

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

for i in range(3):
    time.sleep(2)
    req_qr = urllib.request.Request("https://solocmv.duckdns.org/api/whatsapp/qrcode", headers=headers)
    with urllib.request.urlopen(req_qr) as resp:
        qr = json.loads(resp.read().decode())
        print(f"Tentativa {i+1}: Sucesso={qr.get('sucesso')} | Estado={qr.get('estado')} | Tem base64={bool(qr.get('base64'))} | Tem code={bool(qr.get('code'))}")
        if qr.get('base64'):
            print("Prefix:", qr.get('base64')[:40])
            break

