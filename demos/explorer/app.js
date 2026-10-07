(() => {
  'use strict';

  const state = {
    endpoint: 'http://localhost:8765',
    token: '',
    response: null,
    resultView: 'cards',
    selectedDetail: null,
    selectedDocument: null,
    openapi: null
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const el = {
    endpointPill: $('#endpointPill'),
    endpointInput: $('#endpointInput'),
    tokenInput: $('#tokenInput'),
    rememberInput: $('#rememberInput'),
    connectionState: $('#connectionState'),
    searchForm: $('#searchForm'),
    queryInput: $('#queryInput'),
    topKInput: $('#topKInput'),
    debugInput: $('#debugInput'),
    filtersList: $('#filtersList'),
    resultsContainer: $('#resultsContainer'),
    resultsCaption: $('#resultsCaption'),
    debugPanel: $('#debugPanel'),
    debugJson: $('#debugJson'),
    statMode: $('#statMode'),
    statCount: $('#statCount'),
    statTook: $('#statTook'),
    statEndpoint: $('#statEndpoint'),
    settingsDrawer: $('#settingsDrawer'),
    drawerBackdrop: $('#drawerBackdrop'),
    modalBackdrop: $('#modalBackdrop'),
    detailModal: $('#detailModal'),
    modalTitle: $('#modalTitle'),
    modalEyebrow: $('#modalEyebrow'),
    modalBody: $('#modalBody'),
    toastRegion: $('#toastRegion'),
    documentsContainer: $('#documentsContainer'),
    healthContainer: $('#healthContainer'),
    descriptorJson: $('#descriptorJson'),
    openapiContainer: $('#openapiContainer'),
    openapiSummary: $('#openapiSummary')
  };

  function normalizeEndpoint(value) {
    let endpoint = String(value || '').trim().replace(/\/+$/, '');
    endpoint = endpoint.replace(/\/openapi\.json$/i, '');
    return endpoint || 'http://localhost:8765';
  }

  function headers() {
    const h = { 'Accept': 'application/json' };
    if (state.token) h.Authorization = state.token.toLowerCase().startsWith('bearer ') ? state.token : `Bearer ${state.token}`;
    return h;
  }

  async function request(path, options = {}) {
    const url = `${state.endpoint}${path}`;
    const init = { ...options, headers: { ...headers(), ...(options.headers || {}) } };
    if (options.body && typeof options.body !== 'string') {
      init.body = JSON.stringify(options.body);
      init.headers['Content-Type'] = 'application/json';
    }
    let response;
    try {
      response = await fetch(url, init);
    } catch (error) {
      throw new Error(`Não foi possível acessar ${url}. Verifique o endpoint, a rede e a configuração de CORS. ${error.message}`);
    }
    const raw = await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : null; } catch { data = raw; }
    if (!response.ok) {
      const detail = typeof data === 'object' && data ? (data.detail || JSON.stringify(data)) : raw;
      throw new Error(`HTTP ${response.status} em ${path}. ${detail || response.statusText}`);
    }
    return data;
  }

  function toast(title, message, type = 'info', timeout = 4400) {
    const node = document.createElement('div');
    node.className = `toast ${type}`;
    node.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>`;
    el.toastRegion.appendChild(node);
    setTimeout(() => node.remove(), timeout);
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function pretty(value) {
    return JSON.stringify(value, null, 2);
  }

  function formatNumber(value, digits = 4) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    const n = Number(value);
    return Math.abs(n) >= 100 ? n.toFixed(1) : n.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '');
  }

  function basename(value) {
    if (!value) return null;
    const parts = String(value).split(/[\\/]/);
    return parts[parts.length - 1] || value;
  }

  function setConnection(status, text) {
    const dot = $('.status-dot', el.connectionState);
    dot.className = `status-dot ${status}`;
    $('span:last-child', el.connectionState).textContent = text;
  }

  function setEndpoint(value) {
    state.endpoint = normalizeEndpoint(value);
    el.endpointInput.value = state.endpoint;
    el.endpointPill.textContent = state.endpoint.replace(/^https?:\/\//, '');
    el.statEndpoint.textContent = state.endpoint.replace(/^https?:\/\//, '');
  }

  function loadSettings() {
    try {
      const saved = JSON.parse(localStorage.getItem('wsragExplorer') || 'null');
      if (saved?.endpoint) setEndpoint(saved.endpoint);
      else setEndpoint(el.endpointInput.value);
      if (saved?.token) {
        state.token = saved.token;
        el.tokenInput.value = saved.token;
      }
    } catch {
      setEndpoint(el.endpointInput.value);
    }
  }

  function saveSettings() {
    setEndpoint(el.endpointInput.value);
    state.token = el.tokenInput.value.trim();
    if (el.rememberInput.checked) {
      localStorage.setItem('wsragExplorer', JSON.stringify({ endpoint: state.endpoint, token: state.token }));
    } else {
      localStorage.removeItem('wsragExplorer');
    }
    closeDrawer();
    toast('Configuração salva', state.endpoint, 'success');
  }

  function openDrawer() {
    el.settingsDrawer.classList.add('open');
    el.settingsDrawer.setAttribute('aria-hidden', 'false');
    el.drawerBackdrop.classList.remove('hidden');
  }

  function closeDrawer() {
    el.settingsDrawer.classList.remove('open');
    el.settingsDrawer.setAttribute('aria-hidden', 'true');
    el.drawerBackdrop.classList.add('hidden');
  }

  async function checkHealth(showToast = true) {
    setConnection('neutral', 'Verificando');
    try {
      const data = await request('/health');
      const ok = data?.status === 'ok';
      setConnection(ok ? 'success' : 'warning', ok ? 'Serviço disponível' : 'Serviço degradado');
      if (showToast) toast(ok ? 'Serviço disponível' : 'Serviço degradado', `${data.service || 'websensors-flow-rag'} respondeu com status ${data.status || 'desconhecido'}`, ok ? 'success' : 'info');
      return data;
    } catch (error) {
      setConnection('danger', 'Indisponível');
      if (showToast) toast('Falha de conexão', error.message, 'error', 6500);
      throw error;
    }
  }

  function addFilterRow(key = '', type = 'string', value = '') {
    const row = document.createElement('div');
    row.className = 'filter-row';
    row.innerHTML = `
      <input class="filter-key" placeholder="Campo" value="${escapeHtml(key)}">
      <select class="filter-type">
        <option value="string" ${type === 'string' ? 'selected' : ''}>texto</option>
        <option value="number" ${type === 'number' ? 'selected' : ''}>número</option>
        <option value="boolean" ${type === 'boolean' ? 'selected' : ''}>booleano</option>
        <option value="list" ${type === 'list' ? 'selected' : ''}>lista</option>
      </select>
      <input class="filter-value" placeholder="Valor" value="${escapeHtml(value)}">
      <button type="button" class="remove-filter" title="Remover">×</button>
    `;
    $('.remove-filter', row).addEventListener('click', () => row.remove());
    el.filtersList.appendChild(row);
  }

  function parseFilterValue(type, raw) {
    if (type === 'number') {
      const n = Number(raw);
      if (Number.isNaN(n)) throw new Error(`O valor ${raw} não é um número válido`);
      return n;
    }
    if (type === 'boolean') {
      const v = raw.trim().toLowerCase();
      if (['true', '1', 'sim', 'yes'].includes(v)) return true;
      if (['false', '0', 'não', 'nao', 'no'].includes(v)) return false;
      throw new Error(`O valor ${raw} não é um booleano válido`);
    }
    if (type === 'list') {
      return raw.split(',').map(v => v.trim()).filter(Boolean).map(v => {
        if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
        if (['true', 'false'].includes(v.toLowerCase())) return v.toLowerCase() === 'true';
        return v;
      });
    }
    return raw;
  }

  function collectFilters() {
    const filters = {};
    for (const row of $$('.filter-row', el.filtersList)) {
      const key = $('.filter-key', row).value.trim();
      const raw = $('.filter-value', row).value.trim();
      const type = $('.filter-type', row).value;
      if (!key || !raw) continue;
      filters[key] = parseFilterValue(type, raw);
    }
    return filters;
  }

  function selectedMode() {
    return $('input[name="mode"]:checked').value;
  }

  function buildSearchBody(query, topK = null) {
    const body = {
      query,
      top_k: topK || Number(el.topKInput.value || 10),
      filters: collectFilters(),
      debug: el.debugInput.checked
    };
    if (!Object.keys(body.filters).length) delete body.filters;
    return body;
  }

  async function executeSearch(mode = selectedMode(), query = el.queryInput.value.trim()) {
    if (!query) {
      toast('Consulta necessária', 'Informe um texto antes de executar a busca', 'error');
      return null;
    }
    const route = `/search/${mode}`;
    const submit = $('button[type="submit"]', el.searchForm);
    const original = submit.innerHTML;
    submit.innerHTML = '<span class="spinner"></span>Buscando';
    submit.disabled = true;
    el.resultsContainer.classList.add('loading');
    try {
      const data = await request(route, { method: 'POST', body: buildSearchBody(query) });
      state.response = data;
      renderSearchResponse();
      setConnection('success', 'Serviço disponível');
      return data;
    } catch (error) {
      toast('Falha na busca', error.message, 'error', 7600);
      el.resultsContainer.classList.remove('loading');
      return null;
    } finally {
      submit.innerHTML = original;
      submit.disabled = false;
    }
  }

  function resultTitle(hit) {
    return hit.title || hit.filename || `Documento ${hit.document_id}`;
  }

  function resultPath(hit) {
    const parts = [];
    if (hit.section) parts.push(hit.section);
    if (Array.isArray(hit.heading_path)) parts.push(...hit.heading_path.filter(Boolean));
    return [...new Set(parts)].join('  ›  ') || hit.chunk_id;
  }

  function renderSearchResponse() {
    const data = state.response;
    if (!data) return;
    el.resultsContainer.classList.remove('empty-state', 'loading');
    el.statMode.textContent = modeLabel(data.mode);
    el.statCount.textContent = data.count ?? data.results?.length ?? 0;
    el.statTook.textContent = `${formatNumber(data.took_ms, 2)} ms`;
    el.resultsCaption.textContent = `${data.count ?? data.results?.length ?? 0} resultados para “${data.query}”`;
    if (data.debug) {
      el.debugPanel.classList.remove('hidden');
      el.debugJson.textContent = pretty(data.debug);
    } else {
      el.debugPanel.classList.add('hidden');
    }
    renderResultsByView();
  }

  function modeLabel(mode) {
    return ({ hybrid: 'Híbrida', semantic: 'Semântica', bm25: 'BM25' })[mode] || mode || '—';
  }

  function renderResultsByView() {
    if (!state.response) return;
    if (state.resultView === 'cards') renderCards();
    if (state.resultView === 'table') renderTable();
    if (state.resultView === 'json') renderRawJson();
  }

  function renderCards() {
    const results = state.response?.results || [];
    if (!results.length) {
      el.resultsContainer.className = 'results-container empty-state';
      el.resultsContainer.innerHTML = '<h3>Nenhum resultado</h3><p>A consulta não retornou chunks para os filtros informados</p>';
      return;
    }
    el.resultsContainer.className = 'results-container';
    el.resultsContainer.innerHTML = results.map((hit, index) => {
      const page = hit.page_start ? (hit.page_end && hit.page_end !== hit.page_start ? `páginas ${hit.page_start} a ${hit.page_end}` : `página ${hit.page_start}`) : null;
      const chips = [basename(hit.filename), page, hit.document_id].filter(Boolean).map(v => `<span class="meta-chip">${escapeHtml(v)}</span>`).join('');
      return `
        <article class="result-card" data-result-index="${index}">
          <div class="result-header">
            <div class="result-title-wrap">
              <div class="rank-badge">${escapeHtml(hit.rank ?? index + 1)}</div>
              <div style="min-width:0">
                <h3 class="result-title">${escapeHtml(resultTitle(hit))}</h3>
                <div class="result-path">${escapeHtml(resultPath(hit))}</div>
              </div>
            </div>
            <span class="score-badge">score ${escapeHtml(formatNumber(hit.score, 6))}</span>
          </div>
          <p class="result-content">${escapeHtml(hit.content || '')}</p>
          <div class="result-footer">${chips}</div>
        </article>`;
    }).join('');
    $$('.result-card', el.resultsContainer).forEach(card => card.addEventListener('click', () => openResultDetail(Number(card.dataset.resultIndex))));
  }

  function renderTable() {
    const results = state.response?.results || [];
    el.resultsContainer.className = 'results-container';
    el.resultsContainer.innerHTML = `
      <div class="results-table-wrap">
        <table>
          <thead><tr><th>Rank</th><th>Score</th><th>Documento</th><th>Seção</th><th>Página</th><th>Conteúdo</th></tr></thead>
          <tbody>${results.map((hit, index) => `
            <tr class="data-row" data-result-index="${index}">
              <td>${escapeHtml(hit.rank ?? index + 1)}</td>
              <td>${escapeHtml(formatNumber(hit.score, 6))}</td>
              <td>${escapeHtml(basename(hit.filename) || hit.document_id)}</td>
              <td>${escapeHtml(hit.section || '—')}</td>
              <td>${escapeHtml(hit.page_start || '—')}</td>
              <td class="table-content">${escapeHtml(hit.content || '')}</td>
            </tr>`).join('')}</tbody>
        </table>
      </div>`;
    $$('.data-row', el.resultsContainer).forEach(row => row.addEventListener('click', () => openResultDetail(Number(row.dataset.resultIndex))));
  }

  function renderRawJson() {
    el.resultsContainer.className = 'results-container';
    el.resultsContainer.innerHTML = `<pre class="json-block" style="border-radius:12px;max-height:720px">${escapeHtml(pretty(state.response))}</pre>`;
  }

  function openResultDetail(index) {
    const hit = state.response?.results?.[index];
    if (!hit) return;
    state.selectedDetail = hit;
    state.selectedDocument = null;
    el.modalEyebrow.textContent = `Rank ${hit.rank ?? index + 1}  •  ${modeLabel(state.response.mode)}`;
    el.modalTitle.textContent = resultTitle(hit);
    activateModalTab('content');
    openModal();
  }

  function openDocumentDetail(doc) {
    state.selectedDocument = doc;
    state.selectedDetail = null;
    el.modalEyebrow.textContent = 'Documento indexado';
    el.modalTitle.textContent = doc.filename || doc.title || doc.document_id || 'Documento';
    activateModalTab('json');
    openModal();
  }

  function openModal() {
    el.detailModal.classList.add('open');
    el.detailModal.setAttribute('aria-hidden', 'false');
    el.modalBackdrop.classList.remove('hidden');
  }

  function closeModal() {
    el.detailModal.classList.remove('open');
    el.detailModal.setAttribute('aria-hidden', 'true');
    el.modalBackdrop.classList.add('hidden');
  }

  function activateModalTab(tab) {
    $$('.modal-tab').forEach(b => b.classList.toggle('active', b.dataset.modalTab === tab));
    renderModalContent(tab);
  }

  function keyValueGrid(obj) {
    if (!obj || typeof obj !== 'object' || !Object.keys(obj).length) return '<p class="help">Nenhuma informação disponível</p>';
    return `<dl class="detail-grid">${Object.entries(obj).map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(typeof v === 'object' ? pretty(v) : v)}</dd>`).join('')}</dl>`;
  }

  function renderModalContent(tab) {
    const hit = state.selectedDetail;
    const doc = state.selectedDocument;
    if (doc) {
      if (tab === 'json') el.modalBody.innerHTML = `<pre class="json-block" style="border-radius:10px;max-height:none">${escapeHtml(pretty(doc))}</pre>`;
      else if (tab === 'metadata') el.modalBody.innerHTML = keyValueGrid(doc.metadata || doc);
      else if (tab === 'source') el.modalBody.innerHTML = keyValueGrid(doc.source || {});
      else el.modalBody.innerHTML = `<div class="modal-content-text">${escapeHtml(doc.content || doc.markdown || 'O endpoint de documentos não retornou conteúdo textual neste registro.')}</div>`;
      return;
    }
    if (!hit) return;
    if (tab === 'content') {
      el.modalBody.innerHTML = `
        <div class="modal-content-text">${escapeHtml(hit.content)}</div>
        <div style="margin-top:18px">${keyValueGrid({
          rank: hit.rank,
          score: hit.score,
          document_id: hit.document_id,
          chunk_id: hit.chunk_id,
          revision_id: hit.revision_id,
          page_start: hit.page_start,
          page_end: hit.page_end
        })}</div>`;
    } else if (tab === 'metadata') {
      el.modalBody.innerHTML = keyValueGrid(hit.metadata || {});
    } else if (tab === 'source') {
      el.modalBody.innerHTML = keyValueGrid(hit.source || {});
    } else {
      el.modalBody.innerHTML = `<pre class="json-block" style="border-radius:10px;max-height:none">${escapeHtml(pretty(hit))}</pre>`;
    }
  }

  async function compareModes() {
    const query = el.queryInput.value.trim();
    if (!query) return toast('Consulta necessária', 'Informe o texto antes de comparar os modos', 'error');
    const button = $('#compareModes');
    const original = button.textContent;
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span>Comparando';
    try {
      const body = buildSearchBody(query);
      const start = performance.now();
      const [bm25, semantic, hybrid] = await Promise.all([
        request('/search/bm25', { method: 'POST', body }),
        request('/search/semantic', { method: 'POST', body }),
        request('/search/hybrid', { method: 'POST', body })
      ]);
      const elapsed = performance.now() - start;
      showComparisonModal({ bm25, semantic, hybrid, elapsed });
    } catch (error) {
      toast('Falha na comparação', error.message, 'error', 7000);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function showComparisonModal(data) {
    state.selectedDetail = null;
    state.selectedDocument = null;
    el.modalEyebrow.textContent = 'Comparação';
    el.modalTitle.textContent = 'BM25, semântica e híbrida';
    $$('.modal-tab').forEach(b => b.classList.remove('active'));
    el.modalBody.innerHTML = `
      <div class="openapi-summary" style="padding:0 0 16px;border:0;grid-template-columns:repeat(4,1fr)">
        <div class="openapi-stat"><span>BM25</span><strong>${formatNumber(data.bm25.took_ms,2)} ms</strong></div>
        <div class="openapi-stat"><span>Semântica</span><strong>${formatNumber(data.semantic.took_ms,2)} ms</strong></div>
        <div class="openapi-stat"><span>Híbrida</span><strong>${formatNumber(data.hybrid.took_ms,2)} ms</strong></div>
        <div class="openapi-stat"><span>Execução paralela</span><strong>${formatNumber(data.elapsed,2)} ms</strong></div>
      </div>
      <div class="results-table-wrap"><table>
        <thead><tr><th>Rank</th><th>BM25</th><th>Semântica</th><th>Híbrida</th></tr></thead>
        <tbody>${Array.from({ length: Math.max(data.bm25.results?.length || 0, data.semantic.results?.length || 0, data.hybrid.results?.length || 0) }, (_, i) => `
          <tr><td>${i+1}</td><td>${escapeHtml(shortHit(data.bm25.results?.[i]))}</td><td>${escapeHtml(shortHit(data.semantic.results?.[i]))}</td><td>${escapeHtml(shortHit(data.hybrid.results?.[i]))}</td></tr>`).join('')}</tbody>
      </table></div>`;
    openModal();
  }

  function shortHit(hit) {
    if (!hit) return '—';
    return `${basename(hit.filename) || hit.document_id} · ${String(hit.content || '').slice(0, 85).replace(/\s+/g, ' ')}${String(hit.content || '').length > 85 ? '…' : ''}`;
  }

  async function loadDocuments() {
    const limit = Number($('#documentsLimit').value || 50);
    const button = $('#loadDocuments');
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span>Carregando';
    try {
      const data = await request(`/documents?limit=${limit}`);
      renderDocuments(data);
    } catch (error) {
      toast('Falha ao listar documentos', error.message, 'error', 7000);
    } finally {
      button.disabled = false;
      button.innerHTML = original;
    }
  }

  function normalizeDocuments(data) {
    if (Array.isArray(data)) return data;
    for (const key of ['documents', 'results', 'items', 'hits']) if (Array.isArray(data?.[key])) return data[key];
    return data && typeof data === 'object' ? Object.entries(data).map(([document_id, v]) => typeof v === 'object' ? { document_id, ...v } : { document_id, value: v }) : [];
  }

  function renderDocuments(data) {
    const docs = normalizeDocuments(data);
    if (!docs.length) {
      el.documentsContainer.className = 'empty-state compact-empty';
      el.documentsContainer.innerHTML = '<h3>Nenhum documento retornado</h3><p>O índice de documentos está vazio ou a resposta não contém uma lista reconhecível</p>';
      return;
    }
    el.documentsContainer.className = 'documents-grid';
    el.documentsContainer.innerHTML = docs.map((doc, i) => `
      <article class="document-card" data-doc-index="${i}">
        <h3>${escapeHtml(doc.filename || doc.title || doc.document_id || `Documento ${i+1}`)}</h3>
        <p>${escapeHtml(doc.document_id || doc.id || '')}</p>
        <div class="document-meta">
          ${doc.status ? `<span class="meta-chip">${escapeHtml(doc.status)}</span>` : ''}
          ${doc.active_revision ? `<span class="meta-chip">rev ${escapeHtml(String(doc.active_revision).slice(0,10))}</span>` : ''}
          ${doc.mime_type ? `<span class="meta-chip">${escapeHtml(doc.mime_type)}</span>` : ''}
        </div>
      </article>`).join('');
    $$('.document-card', el.documentsContainer).forEach(card => card.addEventListener('click', async () => {
      const base = docs[Number(card.dataset.docIndex)];
      const id = base.document_id || base.id;
      if (!id) return openDocumentDetail(base);
      try {
        const full = await request(`/documents/${encodeURIComponent(id)}`);
        openDocumentDetail(full);
      } catch (error) {
        toast('Falha ao obter documento', error.message, 'error');
      }
    }));
  }

  async function renderHealth() {
    el.healthContainer.className = 'compact-empty';
    el.healthContainer.innerHTML = '<div style="padding:30px;text-align:center;color:var(--muted)"><span class="spinner"></span>Consultando dependências</div>';
    try {
      const data = await checkHealth(false);
      const deps = data.dependencies || {};
      el.healthContainer.innerHTML = `
        <div class="health-summary">
          <span class="health-badge ${data.status}">${escapeHtml(data.status)}</span>
          <div><strong>${escapeHtml(data.service || 'websensors-flow-rag')}</strong><div class="help">${Object.keys(deps).length} dependências reportadas</div></div>
        </div>
        <div class="health-list">
          ${Object.entries(deps).map(([name, status]) => `<div class="health-item"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(status)}</span></div>`).join('') || '<p class="help">Nenhuma dependência informada</p>'}
        </div>`;
    } catch (error) {
      el.healthContainer.className = 'empty-state compact-empty';
      el.healthContainer.innerHTML = `<h3>Serviço indisponível</h3><p>${escapeHtml(error.message)}</p>`;
    }
  }

  async function loadDescriptor() {
    const button = $('#loadDescriptor');
    button.disabled = true;
    try {
      const data = await request('/rag');
      el.descriptorJson.textContent = pretty(data);
    } catch (error) {
      el.descriptorJson.textContent = error.message;
      toast('Falha ao consultar descritor', error.message, 'error');
    } finally { button.disabled = false; }
  }

  async function loadOpenapi() {
    const button = $('#loadOpenapi');
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span>Carregando';
    try {
      const data = await request('/openapi.json');
      state.openapi = data;
      renderOpenapi(data);
    } catch (error) {
      toast('Falha ao carregar OpenAPI', error.message, 'error', 7000);
    } finally {
      button.disabled = false;
      button.textContent = 'Carregar OpenAPI';
    }
  }

  function renderOpenapi(spec) {
    const operations = [];
    Object.entries(spec.paths || {}).forEach(([path, methods]) => {
      Object.entries(methods || {}).forEach(([method, op]) => {
        if (!['get','post','put','patch','delete'].includes(method.toLowerCase())) return;
        operations.push({ path, method: method.toUpperCase(), ...op });
      });
    });
    const schemas = Object.keys(spec.components?.schemas || {});
    el.openapiSummary.classList.remove('hidden');
    el.openapiSummary.innerHTML = `
      <div class="openapi-stat"><span>Título</span><strong>${escapeHtml(spec.info?.title || 'API')}</strong></div>
      <div class="openapi-stat"><span>Versão</span><strong>${escapeHtml(spec.info?.version || '—')}</strong></div>
      <div class="openapi-stat"><span>Operações</span><strong>${operations.length}</strong></div>
      <div class="openapi-stat"><span>Schemas</span><strong>${schemas.length}</strong></div>`;
    el.openapiContainer.className = 'openapi-list';
    el.openapiContainer.innerHTML = operations.map((op, i) => `
      <article class="openapi-operation" data-op-index="${i}">
        <div class="operation-head">
          <span class="method-badge method-${op.method.toLowerCase()}">${op.method}</span>
          <span class="operation-path">${escapeHtml(op.path)}</span>
          <span class="operation-summary">${escapeHtml(op.summary || '')}</span>
          <span class="operation-id">${escapeHtml(op.operationId || '')}</span>
        </div>
        <div class="operation-details"><pre class="json-block" style="border-radius:9px;max-height:440px">${escapeHtml(pretty(op))}</pre></div>
      </article>`).join('');
    $$('.openapi-operation', el.openapiContainer).forEach(node => $('.operation-head', node).addEventListener('click', () => node.classList.toggle('open')));
  }

  function switchView(name) {
    $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === name));
    $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
    const titles = {
      search: ['Busca', 'Explore BM25, busca semântica e busca híbrida'],
      documents: ['Documentos', 'Inspecione os documentos atualmente indexados'],
      service: ['Serviço', 'Verifique saúde, dependências e capacidades da API'],
      openapi: ['OpenAPI', 'Explore o contrato publicado pelo serviço']
    };
    $('#pageTitle').textContent = titles[name][0];
    $('#pageSubtitle').textContent = titles[name][1];
  }

  function bindEvents() {
    $$('.nav-item').forEach(button => button.addEventListener('click', () => switchView(button.dataset.view)));
    $('#openSettings').addEventListener('click', openDrawer);
    $('#closeSettings').addEventListener('click', closeDrawer);
    el.drawerBackdrop.addEventListener('click', closeDrawer);
    $('#saveSettings').addEventListener('click', saveSettings);
    $('#testConnection').addEventListener('click', async () => {
      setEndpoint(el.endpointInput.value);
      state.token = el.tokenInput.value.trim();
      try { await checkHealth(true); } catch { /* toast feito acima */ }
    });
    $('#checkHealth').addEventListener('click', async () => { try { await checkHealth(true); } catch {} });
    $('#refreshHealth').addEventListener('click', renderHealth);
    $('#loadDescriptor').addEventListener('click', loadDescriptor);
    $('#loadOpenapi').addEventListener('click', loadOpenapi);
    $('#loadDocuments').addEventListener('click', loadDocuments);
    $('#addFilter').addEventListener('click', () => addFilterRow());
    $('#compareModes').addEventListener('click', compareModes);
    $('#copyDebug').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(el.debugJson.textContent); toast('Copiado', 'JSON de debug copiado para a área de transferência', 'success'); }
      catch { toast('Não foi possível copiar', 'Selecione o conteúdo manualmente', 'error'); }
    });
    el.searchForm.addEventListener('submit', event => { event.preventDefault(); executeSearch(); });
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && $('#view-search').classList.contains('active')) executeSearch();
      if (event.key === 'Escape') { closeModal(); closeDrawer(); }
    });
    $$('input[name="mode"]').forEach(input => input.addEventListener('change', () => {
      $$('.mode-card').forEach(card => card.classList.toggle('selected', $('input', card).checked));
    }));
    $$('.toggle-button').forEach(button => button.addEventListener('click', () => {
      state.resultView = button.dataset.resultView;
      $$('.toggle-button').forEach(b => b.classList.toggle('active', b === button));
      renderResultsByView();
    }));
    $('#closeModal').addEventListener('click', closeModal);
    el.modalBackdrop.addEventListener('click', closeModal);
    $$('.modal-tab').forEach(button => button.addEventListener('click', () => activateModalTab(button.dataset.modalTab)));
  }

  function init() {
    loadSettings();
    bindEvents();
    addFilterRow();
    el.queryInput.value = 'mudanças climáticas e impactos nos oceanos';
    setTimeout(() => checkHealth(false).catch(() => {}), 250);
  }

  init();
})();
