/**
 * version.js — Solo CMV
 * Carrega e exibe a versão do sistema, commit SHA e ambiente no footer flutuante.
 */
(function() {
  'use strict';

  const ENV_COLORS = {
    dev:        { bg: 'rgba(16,185,129,.15)',  color: '#10b981', label: 'LOCAL' },
    production: { bg: 'rgba(251,191,36,.15)', color: '#fbbf24', label: 'CONTABO' },
    prod:       { bg: 'rgba(251,191,36,.15)', color: '#fbbf24', label: 'CONTABO' },
    staging:    { bg: 'rgba(59,130,246,.15)', color: '#3b82f6', label: 'STAGE' },
  };

  async function carregarVersao() {
    const txtEl = document.getElementById('version-text');
    const envEl = document.getElementById('version-env');
    const shaEl = document.getElementById('version-sha');
    const badge = document.getElementById('version-badge');
    if (!txtEl) return;

    try {
      const resp = await fetch('/api/versao/', { credentials: 'include' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const d = await resp.json();

      // Versão semântica
      txtEl.textContent = `v${d.versao}`;

      // Ambiente (LOCAL / CONTABO)
      const env = (d.ambiente || 'prod').toLowerCase();
      const cfg = ENV_COLORS[env] || { bg: 'rgba(251,191,36,.15)', color: '#fbbf24', label: 'CONTABO' };
      if (envEl) {
        envEl.textContent      = cfg.label;
        envEl.style.background = cfg.bg;
        envEl.style.color      = cfg.color;
        envEl.style.border     = `1px solid ${cfg.color}44`;
      }

      // SHA do commit
      if (shaEl && d.sha && d.sha !== 'unknown') {
        shaEl.textContent = `#${d.sha}`;
      }

      // Tooltip informativo no hover
      if (badge) {
        const ts = d.timestamp ? new Date(d.timestamp).toLocaleString('pt-BR') : '?';
        badge.title = `Solo CMV v${d.versao}\nAmbiente: ${cfg.label}\nCommit: ${d.sha}\nDeploy / Servidor: ${ts}`;
      }

    } catch (e) {
      if (txtEl) txtEl.textContent = 'v0.1.0';
      if (envEl) {
        envEl.textContent = 'CONTABO';
        envEl.style.background = 'rgba(251,191,36,.15)';
        envEl.style.color = '#fbbf24';
      }
      console.warn('[version.js] Aviso ao carregar versão:', e.message);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(carregarVersao, 400));
  } else {
    setTimeout(carregarVersao, 400);
  }

  window.SoloVersion = { recarregar: carregarVersao };
})();
