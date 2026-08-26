import urllib.request
import json
import time

req_login = urllib.request.Request(
    'https://solocmv.duckdns.org/api/auth/login',
    data=json.dumps({"login": "Jh3ffth", "senha": "1601Jcs332503"}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
token = json.loads(urllib.request.urlopen(req_login).read().decode())['access_token']

# 1. Primeira chamada solicita o pairing code ao WhatsApp
req_pair = urllib.request.Request(
    'https://solocmv.duckdns.org/api/whatsapp/qrcode?numero=5561999998888',
    headers={'Authorization': f'Bearer {token}'}
)
res1 = json.loads(urllib.request.urlopen(req_pair).read().decode())
print("Tentativa 1:", res1.get("pairing_code"), res1.get("code"))

time.sleep(2)

# 2. Segunda chamada pega o pairing code gerado
req_pair2 = urllib.request.Request(
    'https://solocmv.duckdns.org/api/whatsapp/qrcode?numero=5561999998888',
    headers={'Authorization': f'Bearer {token}'}
)
res2 = json.loads(urllib.request.urlopen(req_pair2).read().decode())
print("Tentativa 2 (após 2s):", res2.get("pairing_code"), res2.get("code"))
