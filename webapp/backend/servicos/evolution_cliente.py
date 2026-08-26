"""
Cliente HTTP para comunicação com a Evolution API v2 (usando urllib nativo).

A Evolution API gerencia as conexões do WhatsApp usando Baileys em container Docker.
Este cliente lida com:
- Verificação e inicialização automática da instância 'solo_cmv'
- Obtenção do QR Code para conexão do WhatsApp no painel
- Envio de mensagens de texto e respostas para os usuários
"""
import json
import logging
import os
import urllib.request
import urllib.error
from typing import Optional, Dict, Any

log = logging.getLogger("servicos.evolution_cliente")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://whatsapp:8080").rstrip("/")
AUTHENTICATION_API_KEY = os.getenv("AUTHENTICATION_API_KEY", "solo-cmv-evolution-key-2026")
INSTANCIA_PADRAO = os.getenv("EVOLUTION_INSTANCE_NAME", "solo_cmv")


class ErroEvolution(Exception):
    pass


class EvolutionCliente:
    def __init__(self, base_url: str = None, api_key: str = None, instancia: str = None):
        self.base_url = (base_url or EVOLUTION_API_URL).rstrip("/")
        self.api_key = api_key or AUTHENTICATION_API_KEY
        self.instancia = instancia or INSTANCIA_PADRAO

    def _fazer_requisicao(self, metodo: str, caminho: str, payload: dict = None, timeout: int = 10) -> Dict[str, Any]:
        url = f"{self.base_url}{caminho}"
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "SoloCMV-Backend"
        }
        corpo = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=corpo, headers=headers, method=metodo)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                dados_raw = resp.read().decode("utf-8")
                try:
                    return {"status_code": status, "dados": json.loads(dados_raw) if dados_raw else {}}
                except Exception:
                    return {"status_code": status, "texto": dados_raw}
        except urllib.error.HTTPError as e:
            err_raw = e.read().decode("utf-8", errors="replace")
            log.warning("Evolution API HTTP %s em %s: %s", e.code, caminho, err_raw)
            return {"status_code": e.code, "erro": err_raw}
        except Exception as e:
            log.warning("Falha de conexão com Evolution API em %s: %s", caminho, e)
            return {"status_code": 0, "erro": str(e)}

    def verificar_saude(self) -> bool:
        """Verifica se o container da Evolution API está acessível."""
        res = self._fazer_requisicao("GET", "/", timeout=4)
        return res.get("status_code") in (200, 201)

    def obter_status_instancia(self, instancia: str = None) -> Dict[str, Any]:
        """Obtém o estado da conexão da instância (open, connecting, close)."""
        inst = instancia or self.instancia
        res = self._fazer_requisicao("GET", f"/instance/connectionState/{inst}", timeout=6)
        if res.get("status_code") == 200:
            dados = res.get("dados") or {}
            inst_data = dados.get("instance") or {}
            estado = inst_data.get("state") or dados.get("state") or "close"
            return {"conectado": estado == "open", "estado": estado, "dados": dados}
        return {"conectado": False, "estado": "close", "detalhe": res.get("erro")}

    def criar_instancia_se_necessario(self, instancia: str = None) -> Dict[str, Any]:
        """Cria a instância com webhook configurado para o Solo CMV se ainda não existir."""
        inst = instancia or self.instancia
        webhook_url = os.getenv("SOLO_API_WHATSAPP_WEBHOOK", "http://app:8095/api/whatsapp/webhook")

        payload = {
            "instanceName": inst,
            "token": "",
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS",
            "webhook": webhook_url,
            "webhook_by_events": False,
            "events": [
                "MESSAGES_UPSERT",
                "CONNECTION_UPDATE",
                "QRCODE_UPDATED"
            ]
        }

        res = self._fazer_requisicao("POST", "/instance/create", payload=payload, timeout=12)
        if res.get("status_code") in (200, 201):
            return res.get("dados") or {}
        return {"status": "resultado", "detalhes": res.get("erro")}

    def obter_qrcode(self, instancia: str = None, numero_telefone: str = None) -> Dict[str, Any]:
        """Obtém o QR Code em Base64 ou pairing code para conectar o WhatsApp."""
        inst = instancia or self.instancia
        self.criar_instancia_se_necessario(inst)

        caminho = f"/instance/connect/{inst}"
        if numero_telefone:
            num_limpo = "".join(c for c in str(numero_telefone) if c.isdigit())
            caminho += f"?number={num_limpo}"

        res = self._fazer_requisicao("GET", caminho, timeout=12)
        if res.get("status_code") in (200, 201):
            dados = res.get("dados") or {}
            qrcode_base64 = dados.get("base64") or (dados.get("qrcode") or {}).get("base64")
            code = dados.get("code") or (dados.get("qrcode") or {}).get("code")
            pairing_code = dados.get("pairingCode")
            return {
                "sucesso": True,
                "base64": qrcode_base64,
                "code": code,
                "pairing_code": pairing_code,
                "estado": dados.get("state") or "connecting"
            }
        return {"sucesso": False, "erro": res.get("erro")}

    def enviar_texto(self, destinatario: str, texto: str, instancia: str = None) -> bool:
        """
        Envia mensagem de texto via WhatsApp.
        destinatario: JID (ex: 5511999999999@s.whatsapp.net) ou número limpo (5511999999999).
        """
        inst = instancia or self.instancia
        numero = destinatario.replace("@s.whatsapp.net", "").strip()

        payload = {
            "number": numero,
            "text": texto,
            "delay": 200,
            "linkPreview": False
        }

        res = self._fazer_requisicao("POST", f"/message/sendText/{inst}", payload=payload, timeout=10)
        if res.get("status_code") in (200, 201):
            return True
        log.warning("Evolution API recusou envio para %s: %s", numero, res.get("erro"))
        return False


cliente_evolution = EvolutionCliente()
