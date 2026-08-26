/* Cliente HTTP simples para a API do Solo CMV. */
const API_BASE = '/api';
const TOKEN_KEY = 'solo_cmv_token';

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function setToken(token) { localStorage.setItem(TOKEN_KEY, token); }
function limparToken() { localStorage.removeItem(TOKEN_KEY); }

async function apiFetch(caminho, opcoes = {}) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opcoes.headers || {});
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(API_BASE + caminho, Object.assign({}, opcoes, { headers }));

  let corpo = null;
  const texto = await resp.text();
  if (texto) {
    try { corpo = JSON.parse(texto); } catch (e) { corpo = texto; }
  }

  if (resp.status === 401) {
    if (caminho === '/auth/login') {
      const detalhe = (corpo && corpo.detail) ? corpo.detail : 'Usuário ou senha incorretos.';
      throw new Error(detalhe);
    }
    limparToken();
    mostrarTelaLogin();
    throw new Error('Sessão expirada. Faça login novamente.');
  }

  if (!resp.ok) {
    const detalhe = (corpo && corpo.detail) ? corpo.detail : `Erro ${resp.status}`;
    throw new Error(detalhe);
  }
  return corpo;
}

/* Arquivos (PDF) vêm por aqui: a rota é autenticada, então não dá para usar
   um link direto — é preciso buscar com o token e abrir o blob em memória. */
async function apiBaixar(caminho) {
  const token = getToken();
  const resp = await fetch(API_BASE + caminho, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (resp.status === 401) {
    limparToken();
    mostrarTelaLogin();
    throw new Error('Sessão expirada. Faça login novamente.');
  }
  if (!resp.ok) {
    let detalhe = `Erro ${resp.status}`;
    try { detalhe = (await resp.json()).detail || detalhe; } catch (e) { /* mantém padrão */ }
    throw new Error(detalhe);
  }
  return resp.blob();
}

const api = {
  get: (caminho) => apiFetch(caminho, { method: 'GET' }),
  post: (caminho, dados) => apiFetch(caminho, { method: 'POST', body: JSON.stringify(dados) }),
  put: (caminho, dados) => apiFetch(caminho, { method: 'PUT', body: JSON.stringify(dados) }),
  del: (caminho) => apiFetch(caminho, { method: 'DELETE' }),
  baixar: apiBaixar,
};

/* Abre um arquivo da API em nova aba, já autenticado. */
async function abrirArquivo(caminho) {
  const url = URL.createObjectURL(await api.baixar(caminho));
  window.open(url, '_blank');
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

/* Avisa as telas abertas de que um cadastro mudou, para que listas suspensas
   (Lançador, modal de inventário, filtros) se atualizem sem recarregar a
   página. Tipos: 'produto' | 'categoria' | 'fornecedor' | 'unidade'. */
function avisarCadastroAlterado(tipo, registro) {
  document.dispatchEvent(new CustomEvent('cadastro:alterado', { detail: { tipo, registro } }));
}
