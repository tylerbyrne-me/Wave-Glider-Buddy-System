/**
 * Slocum Vehicle Parameters – mission file management UI.
 * Uses /api/slocum/mission-files/* for deployments, files, summary, changes, snapshots.
 */
import { apiRequest, fetchWithAuth, showToast } from '/static/js/api.js';

const API_BASE = '/api/slocum/mission-files';

function getDeploymentId() {
  const el = document.body.dataset.deploymentId;
  return el ? parseInt(el, 10) : null;
}

function showError(msg) {
  const el = document.getElementById('slocumVehicleParamsError');
  if (el) {
    el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
  }
}

function hideError() {
  showError('');
}

async function loadDeployments() {
  const data = await apiRequest(`${API_BASE}/deployments`, 'GET');
  return Array.isArray(data) ? data : [];
}

function renderDeploymentSelect(deployments, selectedId) {
  const sel = document.getElementById('deploymentSelect');
  if (!sel) return;
  sel.innerHTML = '<option value="">— Select deployment —</option>';
  for (const d of deployments) {
    const opt = document.createElement('option');
    opt.value = d.id;
    opt.textContent = d.name || `Deployment ${d.id}`;
    if (selectedId && d.id === selectedId) opt.selected = true;
    sel.appendChild(opt);
  }
}

async function loadSummary(deploymentId) {
  return apiRequest(`${API_BASE}/deployments/${deploymentId}/summary`, 'GET');
}

function renderSummary(summary) {
  const el = document.getElementById('missionSummary');
  if (!el) return;
  if (!summary || !summary.interpretation) {
    el.textContent = 'No mission files yet, or summary unavailable.';
    return;
  }
  el.textContent = summary.interpretation;
  if (summary.summary) {
    const s = summary.summary;
    const parts = [];
    if (s.dive_depth != null) parts.push(`Dive depth: ${s.dive_depth}`);
    if (s.climb_depth != null) parts.push(`Climb depth: ${s.climb_depth}`);
    if (s.dive_angle != null) parts.push(`Dive angle: ${s.dive_angle}`);
    if (s.active_sample_files?.length) parts.push(`Sample files: ${s.active_sample_files.join(', ')}`);
    if (parts.length) el.innerHTML = `${summary.interpretation}<br><span class="text-muted">${parts.join(' · ')}</span>`;
  }
}

async function loadFiles(deploymentId) {
  const data = await apiRequest(`${API_BASE}/deployments/${deploymentId}/files`, 'GET');
  return Array.isArray(data?.files) ? data.files : (Array.isArray(data) ? data : []);
}

function renderFileList(files, deploymentId) {
  const list = document.getElementById('fileList');
  if (!list) return;
  list.innerHTML = '';
  for (const f of files) {
    const item = document.createElement('div');
    item.className = 'list-group-item d-flex justify-content-between align-items-center flex-wrap gap-1';
    const left = document.createElement('div');
    left.className = 'd-flex align-items-center gap-2';
    const nameLink = document.createElement('a');
    nameLink.href = '#';
    nameLink.className = 'text-primary';
    nameLink.textContent = f.file_name || `File ${f.id}`;
    nameLink.addEventListener('click', (e) => {
      e.preventDefault();
      window.open(`${API_BASE}/files/${f.id}/download`, '_blank');
    });
    const badge = document.createElement('span');
    badge.className = 'badge bg-secondary';
    badge.textContent = f.file_type || 'file';
    left.appendChild(nameLink);
    left.appendChild(badge);
    const actions = document.createElement('div');
    actions.className = 'd-flex gap-1';
    const reqBtn = document.createElement('button');
    reqBtn.type = 'button';
    reqBtn.className = 'btn btn-sm btn-outline-primary';
    reqBtn.textContent = 'Request changes';
    reqBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openRequestChangeModal(deploymentId, f.file_name);
    });
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn-sm btn-outline-danger';
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteFile(f.id, deploymentId);
    });
    actions.appendChild(reqBtn);
    actions.appendChild(delBtn);
    item.appendChild(left);
    item.appendChild(actions);
    list.appendChild(item);
  }
}

function getDeploymentIdFromSelect() {
  const v = document.getElementById('deploymentSelect')?.value;
  return v ? parseInt(v, 10) : null;
}

async function deleteFile(fileId, deploymentId) {
  if (!window.confirm('Remove this file from the deployment? It will no longer appear in the list.')) return;
  hideError();
  try {
    await apiRequest(`${API_BASE}/files/${fileId}`, 'DELETE');
    showToast('File removed');
    const deployments = await loadDeployments();
    await loadDeploymentContent(deploymentId, deployments);
  } catch (e) {
    showError(e.message || 'Delete failed');
  }
}

let requestChangeDeploymentId = null;
let requestChangeLastParsed = null;

function openRequestChangeModal(deploymentId, fileName) {
  requestChangeDeploymentId = deploymentId;
  requestChangeLastParsed = null;
  document.getElementById('requestChangeFileName').textContent = fileName || '—';
  document.getElementById('requestChangeInput').value = '';
  document.getElementById('requestChangePreview').innerHTML = '';
  document.getElementById('requestChangeError').style.display = 'none';
  document.getElementById('requestChangeApplyBtn').style.display = 'none';
  const modal = new bootstrap.Modal(document.getElementById('requestChangeModal'));
  modal.show();
}

function initRequestChangeModal() {
  const previewBtn = document.getElementById('requestChangePreviewBtn');
  const applyBtn = document.getElementById('requestChangeApplyBtn');
  const input = document.getElementById('requestChangeInput');
  const previewEl = document.getElementById('requestChangePreview');
  const errEl = document.getElementById('requestChangeError');
  if (!previewBtn || !applyBtn || !input) return;

  previewBtn.addEventListener('click', async () => {
    const deploymentId = requestChangeDeploymentId || getDeploymentIdFromSelect();
    const fileName = document.getElementById('requestChangeFileName').textContent.trim();
    const part = (input.value || '').trim();
    if (!deploymentId || !part) return;
    const requestText = fileName && fileName !== '—' ? `In ${fileName}, ${part}` : part;
    errEl.style.display = 'none';
    previewEl.innerHTML = '';
    applyBtn.style.display = 'none';
    try {
      const nlRes = await apiRequest(`${API_BASE}/deployments/${deploymentId}/changes/natural-language`, 'POST', { request: requestText });
      const parsed = nlRes.parsed_changes || [];
      if (parsed.length === 0) {
        errEl.textContent = 'No parameter changes understood. Try e.g. "set param_name to value".';
        errEl.style.display = 'block';
        return;
      }
      const previewRes = await apiRequest(`${API_BASE}/deployments/${deploymentId}/changes/preview`, 'POST', { changes: parsed });
      requestChangeLastParsed = parsed;
      const fileDiffs = previewRes.file_diffs || {};
      for (const [fn, lines] of Object.entries(fileDiffs)) {
        const pre = document.createElement('pre');
        pre.className = 'small bg-light p-2 rounded mb-2';
        const parts = (lines || []).map((l) => (l.kind === 'remove' ? '-' : l.kind === 'add' ? '+' : ' ') + (l.content || ''));
        pre.textContent = fn + '\n' + parts.join('\n');
        previewEl.appendChild(pre);
      }
      applyBtn.style.display = 'inline-block';
    } catch (e) {
      errEl.textContent = e.message || 'Preview failed';
      errEl.style.display = 'block';
    }
  });

  applyBtn.addEventListener('click', async () => {
    if (!requestChangeLastParsed || requestChangeLastParsed.length === 0) return;
    const deploymentId = requestChangeDeploymentId || getDeploymentIdFromSelect();
    if (!deploymentId) return;
    errEl.style.display = 'none';
    try {
      await apiRequest(`${API_BASE}/deployments/${deploymentId}/changes/apply`, 'POST', { changes: requestChangeLastParsed });
      showToast('Changes applied');
      bootstrap.Modal.getInstance(document.getElementById('requestChangeModal'))?.hide();
      const deployments = await loadDeployments();
      await loadDeploymentContent(deploymentId, deployments);
    } catch (e) {
      errEl.textContent = e.message || 'Apply failed';
      errEl.style.display = 'block';
    }
  });
}

function setDownloadZipHref(deploymentId) {
  const a = document.getElementById('btnDownloadZip');
  if (a) a.href = `${API_BASE}/deployments/${deploymentId}/download`;
}

async function loadSnapshots(deploymentId) {
  const data = await apiRequest(`${API_BASE}/deployments/${deploymentId}/snapshots`, 'GET');
  return Array.isArray(data) ? data : [];
}

function renderSnapshotList(snapshots, deploymentId) {
  const list = document.getElementById('snapshotList');
  if (!list) return;
  list.innerHTML = '';
  for (const s of snapshots) {
    const a = document.createElement('a');
    a.href = `${API_BASE}/deployments/${deploymentId}/snapshots/${s.id}/download`;
    a.target = '_blank';
    a.rel = 'noopener';
    a.className = 'list-group-item list-group-item-action';
    a.textContent = s.created_at_utc || `Snapshot ${s.id}`;
    list.appendChild(a);
  }
}

async function loadDeploymentContent(deploymentId, deployments) {
  const name = (deployments.find(d => d.id === deploymentId) || {}).name || `Deployment ${deploymentId}`;
  document.getElementById('deploymentHeaderName').textContent = name;
  document.getElementById('deployment-content').style.display = 'block';
  setDownloadZipHref(deploymentId);
  try {
    const [summary, files, snapshots] = await Promise.all([
      loadSummary(deploymentId),
      loadFiles(deploymentId),
      loadSnapshots(deploymentId),
    ]);
    renderSummary(summary);
    renderFileList(files, deploymentId);
    renderSnapshotList(snapshots, deploymentId);
  } catch (e) {
    showError(e.message || 'Failed to load deployment');
  }
}

function initDeploymentSelect(deployments, initialId) {
  renderDeploymentSelect(deployments, initialId);
  const sel = document.getElementById('deploymentSelect');
  if (!sel) return;
  sel.addEventListener('change', async () => {
    const id = sel.value ? parseInt(sel.value, 10) : null;
    if (!id) {
      document.getElementById('deployment-content').style.display = 'none';
      return;
    }
    hideError();
    await loadDeploymentContent(id, deployments);
  });
}

async function loadActiveDatasets() {
  const res = await apiRequest(`${API_BASE}/deployments/active-datasets`, 'GET');
  return res.dataset_ids || [];
}

function initNewDeployment() {
  const btn = document.getElementById('btnNewDeployment');
  const modalEl = document.getElementById('newDeploymentModal');
  const confirmBtn = document.getElementById('btnNewDeploymentConfirm');
  const nameInput = document.getElementById('newDeploymentName');
  const gliderInput = document.getElementById('newDeploymentGlider');
  const datasetSelect = document.getElementById('newDeploymentDataset');
  if (!btn || !modalEl || !confirmBtn) return;

  btn.addEventListener('click', async () => {
    nameInput.value = '';
    gliderInput.value = '';
    datasetSelect.innerHTML = '<option value="">— Testing (no dataset) —</option>';
    try {
      const datasetIds = await loadActiveDatasets();
      for (const id of datasetIds) {
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = id;
        datasetSelect.appendChild(opt);
      }
    } catch (e) {
      console.warn('Could not load active datasets', e);
    }
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
  });

  confirmBtn.addEventListener('click', async () => {
    const name = (nameInput.value || '').trim();
    const glider_name = (gliderInput.value || '').trim();
    if (!name || !glider_name) {
      showError('Name and glider name are required.');
      return;
    }
    hideError();
    const erddap_dataset_id = (datasetSelect.value || '').trim() || null;
    try {
      const created = await apiRequest(`${API_BASE}/deployments`, 'POST', {
        name,
        glider_name,
        erddap_dataset_id,
      });
      bootstrap.Modal.getInstance(modalEl)?.hide();
      const deployments = await loadDeployments();
      renderDeploymentSelect(deployments, created.id);
      document.getElementById('deploymentSelect').value = String(created.id);
      await loadDeploymentContent(created.id, deployments);
      showToast('Deployment created');
    } catch (e) {
      showError(e.message || 'Failed to create deployment');
    }
  });
}

function initUpload() {
  const btn = document.getElementById('btnUploadFile');
  const input = document.getElementById('uploadFileInput');
  if (!btn || !input) return;
  btn.addEventListener('click', () => input.click());
  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file) return;
    const deploymentId = document.getElementById('deploymentSelect')?.value;
    if (!deploymentId) return;
    hideError();
    const form = new FormData();
    form.append('files', file);
    try {
      const res = await fetchWithAuth(`${API_BASE}/deployments/${deploymentId}/files/upload`, {
        method: 'POST',
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      showToast('File uploaded');
      const deployments = await loadDeployments();
      await loadDeploymentContent(parseInt(deploymentId, 10), deployments);
    } catch (e) {
      showError(e.message || 'Upload failed');
    }
    input.value = '';
  });
}

function initCreateFile() {
  const btn = document.getElementById('btnCreateFile');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const deploymentId = document.getElementById('deploymentSelect')?.value;
    if (!deploymentId) return;
    const subtype = window.prompt('Subtype (sample, surfacing, yo, goto)', 'sample');
    if (!subtype) return;
    const template = await apiRequest(`${API_BASE}/deployments/${deploymentId}/files/create/template/${subtype}`, 'GET').catch(() => ({}));
    const suggestedName = template.suggested_file_name || `${subtype}11.ma`;
    const fileName = window.prompt('File name (e.g. sample11.ma)', suggestedName);
    if (!fileName) return;
    hideError();
    try {
      const paramList = template.parameters || [];
      const parameters = {};
      for (const p of paramList) {
        parameters[p.name] = p.default_value != null ? String(p.default_value) : '';
      }
      const preview = await apiRequest(`${API_BASE}/deployments/${deploymentId}/files/create`, 'POST', {
        file_name: fileName,
        subtype: subtype.trim().toLowerCase(),
        parameters,
      });
      if (!preview.content || !preview.file_name) {
        showError('Server did not return file content.');
        return;
      }
      await apiRequest(`${API_BASE}/deployments/${deploymentId}/files/create/confirm`, 'POST', {
        content: preview.content,
        file_name: preview.file_name,
      });
      showToast('File created');
      const deployments = await loadDeployments();
      await loadDeploymentContent(parseInt(deploymentId, 10), deployments);
    } catch (e) {
      showError(e.message || 'Create file failed');
    }
  });
}

function initRefreshSummary() {
  const btn = document.getElementById('btnRefreshSummary');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const deploymentId = document.getElementById('deploymentSelect')?.value;
    if (!deploymentId) return;
    hideError();
    try {
      const summary = await loadSummary(parseInt(deploymentId, 10));
      renderSummary(summary);
      showToast('Summary refreshed');
    } catch (e) {
      showError(e.message || 'Refresh failed');
    }
  });
}

function initNaturalLanguageChange() {
  const previewBtn = document.getElementById('btnNlPreview');
  const applyBtn = document.getElementById('btnApplyChanges');
  const input = document.getElementById('nlChangeInput');
  const diffsEl = document.getElementById('previewDiffs');
  if (!previewBtn || !applyBtn || !input || !diffsEl) return;

  let lastParsedChanges = null;

  previewBtn.addEventListener('click', async () => {
    const deploymentId = document.getElementById('deploymentSelect')?.value;
    const text = (input.value || '').trim();
    if (!deploymentId || !text) return;
    hideError();
    try {
      const nlRes = await apiRequest(`${API_BASE}/deployments/${deploymentId}/changes/natural-language`, 'POST', { request: text });
      const parsed = nlRes.parsed_changes || [];
      if (parsed.length === 0) {
        diffsEl.textContent = 'No parameter changes understood from that request.';
        applyBtn.style.display = 'none';
        lastParsedChanges = null;
        return;
      }
      const previewRes = await apiRequest(`${API_BASE}/deployments/${deploymentId}/changes/preview`, 'POST', { changes: parsed });
      lastParsedChanges = parsed;
      diffsEl.innerHTML = '';
      const fileDiffs = previewRes.file_diffs || {};
      if (Object.keys(fileDiffs).length) {
        for (const [fileName, lines] of Object.entries(fileDiffs)) {
          const pre = document.createElement('pre');
          pre.className = 'small bg-light p-2 rounded mb-2';
          const parts = (lines || []).map((l) => (l.kind === 'remove' ? '-' : l.kind === 'add' ? '+' : ' ') + (l.content || ''));
          pre.textContent = fileName + '\n' + parts.join('\n');
          diffsEl.appendChild(pre);
        }
        applyBtn.style.display = 'inline-block';
      } else {
        diffsEl.textContent = 'No file diffs produced.';
        applyBtn.style.display = 'none';
      }
    } catch (e) {
      showError(e.message || 'Preview failed');
      applyBtn.style.display = 'none';
      lastParsedChanges = null;
    }
  });

  applyBtn.addEventListener('click', async () => {
    if (!lastParsedChanges || lastParsedChanges.length === 0) return;
    const deploymentId = document.getElementById('deploymentSelect')?.value;
    if (!deploymentId) return;
    hideError();
    try {
      await apiRequest(`${API_BASE}/deployments/${deploymentId}/changes/apply`, 'POST', {
        changes: lastParsedChanges,
      });
      showToast('Changes applied');
      input.value = '';
      diffsEl.innerHTML = '';
      applyBtn.style.display = 'none';
      lastParsedChanges = null;
      const deployments = await loadDeployments();
      await loadDeploymentContent(parseInt(deploymentId, 10), deployments);
    } catch (e) {
      showError(e.message || 'Apply failed');
    }
  });
}

async function init() {
  hideError();
  let deployments = [];
  try {
    deployments = await loadDeployments();
  } catch (e) {
    showError(e.message || 'Failed to load deployments');
    return;
  }
  const initialId = getDeploymentId();
  initDeploymentSelect(deployments, initialId);
  initNewDeployment();
  initUpload();
  initCreateFile();
  initRefreshSummary();
  initNaturalLanguageChange();
  initRequestChangeModal();
  if (initialId && deployments.some(d => d.id === initialId)) {
    document.getElementById('deploymentSelect').value = initialId;
    await loadDeploymentContent(initialId, deployments);
  }
}

document.addEventListener('DOMContentLoaded', init);
