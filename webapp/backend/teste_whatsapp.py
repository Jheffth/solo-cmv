"""
Testes unitários e de integração para o canal WhatsApp (Evolution API) no Solo CMV.
"""
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import (
    Empresa, Unidade, Usuario, PapelUsuario, EscopoUnidades,
    CodigoPareamento, TentativaVinculoWhatsApp, SessaoWhatsApp,
    MensagemProcessadaWhatsApp
)
from auth.security import hash_senha
from servicos import whatsapp as servico_wpp
from servicos.whatsapp import ErroVinculoWhatsApp


class TesteWhatsApp(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Seed básico
        self.empresa = Empresa(id=1, nome="Josefina Gastronomia")
        self.db.add(self.empresa)
        self.db.flush()

        self.unidade = Unidade(id=1, empresa_id=1, nome="Josefina")
        self.db.add(self.unidade)
        self.db.flush()

        self.arquiteto = Usuario(
            id=1,
            nome="Arquiteto Teste",
            login="arquiteto",
            senha_hash=hash_senha("SenhaForte123"),
            papel=PapelUsuario.ARQUITETO,
            escopo_unidades=EscopoUnidades.TODAS,
            ativo=True
        )
        self.operador = Usuario(
            id=2,
            empresa_id=1,
            nome="Operador Teste",
            login="operador",
            senha_hash=hash_senha("SenhaForte123"),
            papel=PapelUsuario.OPERADOR,
            escopo_unidades=EscopoUnidades.LISTA,
            ativo=True
        )
        self.db.add_all([self.arquiteto, self.operador])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_gerar_codigo_pareamento(self):
        """Gera código de 6 dígitos com validade de 10 min."""
        res = servico_wpp.gerar(self.db, self.arquiteto)
        self.assertEqual(len(res["codigo"]), 6)
        self.assertTrue(res["codigo"].isdigit())
        self.assertEqual(res["minutos"], 10)

        # Confere no banco
        p = self.db.query(CodigoPareamento).filter_by(usuario_id=self.arquiteto.id, canal="WHATSAPP").first()
        self.assertIsNotNone(p)
        self.assertEqual(p.codigo, res["codigo"])
        self.assertIsNone(p.usado_em)

    def test_vincular_com_sucesso(self):
        """Vincula o WhatsApp usando o código gerado."""
        res = servico_wpp.gerar(self.db, self.arquiteto)
        codigo = res["codigo"]
        jid = "5561999998888@s.whatsapp.net"

        vinculo = servico_wpp.vincular(self.db, codigo, jid, whatsapp_nome="Jefferson")
        self.assertEqual(vinculo["usuario_id"], self.arquiteto.id)
        self.assertEqual(vinculo["papel"], "ARQUITETO")

        # Verifica dados no usuario
        u = self.db.query(Usuario).filter_by(id=self.arquiteto.id).first()
        self.assertEqual(u.whatsapp_jid, jid)
        self.assertEqual(u.whatsapp_numero, "5561999998888")
        self.assertEqual(u.whatsapp_nome, "Jefferson")
        self.assertIsNotNone(u.whatsapp_vinculado_em)

    def test_codigo_invalido_ou_expirado(self):
        """Recusa códigos errados e expirados."""
        jid = "5561999998888@s.whatsapp.net"
        with self.assertRaises(ErroVinculoWhatsApp):
            servico_wpp.vincular(self.db, "000000", jid)

        # Código expirado
        res = servico_wpp.gerar(self.db, self.arquiteto)
        p = self.db.query(CodigoPareamento).filter_by(codigo=res["codigo"]).first()
        p.expira_em = datetime.utcnow() - timedelta(minutes=5)
        self.db.commit()

        with self.assertRaises(ErroVinculoWhatsApp):
            servico_wpp.vincular(self.db, res["codigo"], jid)

    def test_protecao_anti_forca_bruta(self):
        """5 tentativas erradas bloqueiam o JID por 15 minutos."""
        jid = "5561911112222@s.whatsapp.net"
        for _ in range(5):
            try:
                servico_wpp.vincular(self.db, "111111", jid)
            except ErroVinculoWhatsApp:
                pass

        # 6ª tentativa é bloqueada antes de checar código
        with self.assertRaises(ErroVinculoWhatsApp) as ctx:
            servico_wpp.vincular(self.db, "111111", jid)
        self.assertIn("Muitas tentativas", ctx.exception.mensagem)

    def test_desvincular(self):
        """Desvincular remove o JID e dados do WhatsApp."""
        res = servico_wpp.gerar(self.db, self.arquiteto)
        jid = "5561999998888@s.whatsapp.net"
        servico_wpp.vincular(self.db, res["codigo"], jid)

        servico_wpp.desvincular(self.db, self.arquiteto)
        u = self.db.query(Usuario).filter_by(id=self.arquiteto.id).first()
        self.assertIsNone(u.whatsapp_jid)
        self.assertIsNone(u.whatsapp_numero)

    def test_comandos_e_permissoes(self):
        """Testa resposta de ajuda e bloqueio de comandos restritos."""
        res_ajuda = servico_wpp.processar_comando(self.db, self.arquiteto, "/ajuda", "/ajuda")
        self.assertIn("Comandos disponíveis", res_ajuda)
        self.assertIn("/cmv", res_ajuda)

        # Operador não pode ver /cmv
        res_cmv_op = servico_wpp.processar_comando(self.db, self.operador, "/cmv", "/cmv")
        self.assertIn("Acesso restrito", res_cmv_op)

        # Operador não pode congelar
        res_cong_op = servico_wpp.processar_comando(self.db, self.operador, "/congelar", "/congelar")
        self.assertIn("Apenas Gerentes e Diretores", res_cong_op)


if __name__ == "__main__":
    unittest.main()
