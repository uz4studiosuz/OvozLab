/* OvozLab — UI */
'use strict';

const GITHUB_URL = 'https://github.com/uz4studiosuz/OvozLab';
const MAX_CHARS = 5000;
const TAGS = [
  ['[laughter]', 'Kulgi'], ['[sigh]', "Xo'rsinish"], ['[surprise-ah]', 'Hayrat — ah'], ['[surprise-oh]', 'Hayrat — oh'],
  ['[question-ah]', 'Savol ohangi'], ['[dissatisfaction-hnn]', 'Norozilik'], ['[confirmation-en]', 'Tasdiqlash'],
];

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = (id, cls = 'icon sm') => `<svg class="${cls}"><use href="#${id}"/></svg>`;
const isDesktop = () => !!(window.pywebview && window.pywebview.api);

const MOOD_LABEL = { neutral: 'Oddiy', happy: 'Quvnoq', sad: "G'amgin", serious: 'Jiddiy', story: 'Hikoyachi' };
const MOOD_SUFFIX = { neutral: '', happy: 'quvnoq', sad: "g'amgin", serious: 'jiddiy', story: 'hikoya' };
const state = {
  mood: 'neutral',
  voices: [], voiceId: '', format: 'wav', quality: 32, history: [], health: null,
  playingId: null,
};

/* ---------------- utils ---------------- */
function fmtBytes(b) {
  if (b == null) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(b >= 10 || i < 2 ? 0 : 1)} ${u[i]}`;
}
function fmtTime(s) { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
function ago(ts) {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return 'hozirgina';
  if (d < 3600) return `${Math.floor(d / 60)} daqiqa oldin`;
  if (d < 86400) return `${Math.floor(d / 3600)} soat oldin`;
  return new Date(ts * 1000).toLocaleDateString('uz-UZ', { day: 'numeric', month: 'short' });
}
function hue(str) { let h = 0; for (const c of String(str)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function avatarStyle(name) {
  if (!name) return '';
  const h = hue(name);
  return `background: linear-gradient(135deg, hsl(${h} 70% 62%), hsl(${(h + 50) % 360} 72% 48%))`;
}
function toast(msg, err = false) {
  const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg;
  $('#toasts').append(t); setTimeout(() => t.remove(), err ? 6000 : 3200);
}
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : (j.detail?.[0]?.msg || msg); } catch {}
    throw new Error(msg);
  }
  return r;
}
const json = (path, opts) => api(path, opts).then(r => r.json());
const post = (path, body) => json(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
function openLink(url) { if (isDesktop()) window.pywebview.api.open_url(url); else window.open(url, '_blank'); }
function closeMenus(except) { $$('.menu').forEach(m => { if (m !== except) m.hidden = true; }); }
document.addEventListener('click', (e) => { if (!e.target.closest('.dropdown')) closeMenus(); });

/* ---------------- navigation ---------------- */
const TITLES = { tts: 'Matndan nutq', stt: 'Nutqdan matn', voices: 'Ovozlar', settings: 'Sozlamalar' };
function go(view) {
  $$('.nav-item[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach(v => v.classList.toggle('active', v.dataset.view === view));
  $('#viewTitle').textContent = TITLES[view];
  if (view === 'voices') renderVoiceGrid();
  if (view === 'settings') renderSettings();
  if (view === 'stt') checkSttModel();
}
$$('.nav-item[data-view]').forEach(b => b.onclick = () => go(b.dataset.view));
document.addEventListener('click', (e) => {
  const a = e.target.closest('[data-action="clone"]'); if (a) openClone({});
  const l = e.target.closest('[data-link]');
  if (l) openLink(l.dataset.link === 'github' ? GITHUB_URL : location.origin + '/docs');
});

/* ---------------- status ---------------- */
async function pollHealth() {
  let next = 4000;
  try {
    const h = state.health = await json('/health');
    const dot = $('#statusDot'), t1 = $('#statusT1'), t2 = $('#statusT2');
    dot.className = 'dot ' + (h.status === 'ready' ? 'ready' : h.status === 'error' ? 'error' : h.status === 'loading' ? 'loading' : '');
    const L = h.loading;
    if (!h.setup_complete) { t1.textContent = 'Sozlanmagan'; t2.textContent = 'O\'rnatish ustasi'; }
    else if (h.status === 'ready') { t1.textContent = 'Tayyor'; t2.textContent = h.device_name || h.device; }
    else if (h.status === 'loading') { t1.textContent = `Yuklanmoqda · ${L ? Math.round(L.percent) : 0}%`; t2.textContent = L?.stage || 'Bir daqiqa…'; next = 700; }
    else if (h.status === 'error') { t1.textContent = 'Xato'; t2.textContent = h.error || ''; }
    else { t1.textContent = 'Kutilmoqda'; t2.textContent = '\u00a0'; next = 1000; }
    $('#statusCard').title = h.error || '';
    renderReady(h);
  } catch { $('#statusT1').textContent = 'Aloqa yo\'q'; next = 2000; }
  setTimeout(pollHealth, next);
}
const isReady = () => state.health?.status === 'ready';
function renderReady(h) {
  const ban = $('#loadBanner'), ready = h.status === 'ready';
  ban.hidden = ready || !h.setup_complete;
  ban.classList.toggle('err', h.status === 'error');
  if (h.status === 'loading' || h.status === 'not_loaded') {
    const L = h.loading || { percent: 0, stage: 'Model yuklanmoqda', eta_s: null };
    $('#lbStage').textContent = (L.stage || 'Model yuklanmoqda') + '…';
    $('#lbEta').textContent = L.eta_s ? `~${Math.max(1, Math.round(L.eta_s))} soniya qoldi` : '';
    $('#lbBar').style.width = (L.percent || 2) + '%';
  } else if (h.status === 'error') {
    $('#lbStage').textContent = 'Model yuklanmadi'; $('#lbEta').textContent = 'Sozlamalar → Qayta sozlash';
    $('#lbBar').style.width = '0';
  }
  // model tayyor bo'lmaguncha asosiy tugmalar "kutish" holatida
  for (const id of ['genBtn', 'cSave', 'cAsr']) {
    const el = document.getElementById(id); if (!el) continue;
    el.classList.toggle('waiting', !ready); el.title = ready ? '' : 'Model yuklanmoqda — biroz kuting';
  }
  const gl = $('#genLabel'); if (gl && !$('#genBtn').disabled) gl.textContent = ready ? 'Ovoz yaratish' : 'Model yuklanmoqda…';
}

/* ---------------- editor ---------------- */
const ta = $('#text'), backdrop = $('#hlBackdrop');
function syncEditor() {
  const v = ta.value;
  backdrop.innerHTML = esc(v).replace(/\[[a-z-]+\]/g, m => `<mark>${m}</mark>`) + '\n';
  ta.style.height = 'auto'; ta.style.height = Math.max(360, ta.scrollHeight) + 'px';
  const n = v.length;
  $('#count').textContent = `${n.toLocaleString('uz-UZ').replace(/,/g, ' ')} / 5 000 belgi`;
  $('#count').style.color = n > MAX_CHARS ? 'var(--danger)' : '';
  try { localStorage.setItem('ovozlab.text', v); } catch {}
}
ta.addEventListener('input', syncEditor);
try { const saved = localStorage.getItem('ovozlab.text'); if (saved) ta.value = saved; } catch {}

$('#tagMenu').innerHTML = `<div class="menu-title" style="display:flex;justify-content:space-between;align-items:center">His-tuyg'u teglari <span class="badge">Tajribaviy</span></div>` +
  TAGS.map(([t, n]) => `<button class="menu-item" data-tag="${t}">${n}<span class="sub"><span class="tag-code">${t}</span></span></button>`).join('') +
  `<div class="menu-sep"></div><div class="hint" style="padding:4px 10px 8px;white-space:normal;max-width:310px">Model teglarni asosan ingliz va xitoy tilida o'rgangan, o'zbekcha matnda ko'pincha sezilmaydi. Eng ishonchli yo'l — kayfiyatli ovoz profili.</div>
  <button class="menu-item" data-mood-clone="happy">${icon('i-mic')}Kayfiyatli ovoz yozish<span class="sub">tavsiya</span></button>`;
$('#tagBtn').onclick = (e) => { e.stopPropagation(); const m = $('#tagMenu'); closeMenus(m); m.hidden = !m.hidden; };
$('#tagMenu').onclick = (e) => {
  const mc = e.target.closest('[data-mood-clone]'); if (mc) { closeMenus(); return openClone({ mode: 'record', mood: mc.dataset.moodClone }); }
  const b = e.target.closest('[data-tag]'); if (!b) return;
  const s = ta.selectionStart ?? ta.value.length, en = ta.selectionEnd ?? s;
  const before = ta.value.slice(0, s), ins = (before && !/\s$/.test(before) ? ' ' : '') + b.dataset.tag + ' ';
  ta.value = before + ins + ta.value.slice(en);
  ta.focus(); ta.selectionStart = ta.selectionEnd = s + ins.length; syncEditor(); closeMenus();
};

/* ---------------- side panel controls ---------------- */
function seg(id, cb) {
  const el = $('#' + id);
  el.onclick = (e) => {
    const b = e.target.closest('button'); if (!b) return;
    $$('button', el).forEach(x => x.classList.toggle('on', x === b)); cb && cb(b.dataset.v);
  };
  return () => $('button.on', el)?.dataset.v ?? '';
}
const QUALITY_HINT = { 16: 'Tezroq, sifat biroz past', 32: 'Muvozanatli', 48: 'Eng yaxshi sifat, sekinroq' };
seg('quality', v => { state.quality = +v; $('#qualityHint').textContent = QUALITY_HINT[v]; });
seg('format', v => state.format = v);
const getGender = seg('stGender');
const speed = $('#speed');
const syncSpeed = () => { const p = (speed.value - speed.min) / (speed.max - speed.min) * 100; speed.style.setProperty('--p', p + '%'); $('#speedVal').textContent = (+speed.value).toFixed(2) + '×'; };
speed.oninput = syncSpeed; syncSpeed();
$('#seedOn').onchange = () => $('#seed').hidden = !$('#seedOn').checked;

$$('.tabs button').forEach(b => b.onclick = () => {
  $$('.tabs button').forEach(x => x.classList.toggle('on', x === b));
  $$('[data-pane]').forEach(p => p.hidden = p.dataset.pane !== b.dataset.tab);
  if (b.dataset.tab === 'history') loadHistory();
});

/* ---------------- voices ---------------- */
async function loadVoices() {
  state.voices = await json('/voices');
  if (state.voiceId && !state.voices.some(v => v.id === state.voiceId)) state.voiceId = '';
  renderVoicePick(); renderVoiceMenu();
  if ($('.view.active')?.dataset.view === 'voices') renderVoiceGrid();
}
function voiceById(id) { return state.voices.find(v => v.id === id); }
function voiceBase(name) { return String(name || '').replace(/\s+[—–-]\s+[^—–-]+$/, ''); }
function moodSibling(voiceId, mood) {
  const v = voiceById(voiceId); if (!v) return null;
  if ((v.mood || 'neutral') === mood) return v;
  return state.voices.find(o => o.id !== v.id && o.group === v.group && (o.mood || 'neutral') === mood) || null;
}
function renderMoodNote() {
  $$('#moodPick .mood').forEach(b => b.classList.toggle('on', b.dataset.mood === state.mood));
  const note = $('#moodNote'), v = voiceById(state.voiceId), m = state.mood;
  if (m === 'neutral') { note.innerHTML = v && v.mood && v.mood !== 'neutral' ? `Yozuvdagi kayfiyat: <b>${esc(MOOD_LABEL[v.mood])}</b>` : ''; return; }
  const sib = v && moodSibling(v.id, m);
  if (sib) { note.innerHTML = `✓ Haqiqiy kayfiyat: <b>${esc(sib.name)}</b> yozuvidan olinadi`; return; }
  note.innerHTML = v
    ? `Taxminiy: tezlik va ohang o'zgartiriladi. Haqiqiy kayfiyat uchun <button data-rec-mood>${esc(voiceBase(v.name))} — ${MOOD_SUFFIX[m]}</button> yozuvini qo'shing.`
    : `Taxminiy: tezlik va ohang o'zgartiriladi. Eng yaxshi natija — kayfiyatli <button data-rec-mood>ovoz yozuvi</button>.`;
}
$('#moodPick').onclick = (e) => { const b = e.target.closest('[data-mood]'); if (!b) return; state.mood = b.dataset.mood; renderMoodNote(); };
$('#moodNote').onclick = (e) => {
  if (!e.target.closest('[data-rec-mood]')) return;
  const v = voiceById(state.voiceId);
  openClone({ mode: 'record', mood: state.mood, name: v ? voiceBase(v.name) : '' });
};
function renderVoicePick() {
  setTimeout(renderMoodNote);
  const v = voiceById(state.voiceId), name = v ? v.name : 'Avtomatik ovoz';
  for (const [a, n] of [['#chipAvatar', '#chipName'], ['#selAvatar', '#selName']]) {
    $(n).textContent = name;
    $(a).setAttribute('style', avatarStyle(v?.name));
    $(a).innerHTML = v ? '' : icon('i-sparkle', 'icon xs');
  }
  const auto = !v;
  $('#styleBox').classList.toggle('disabled', !auto);
  $('#styleBadge').textContent = auto ? 'Faol' : 'Klon ovozda o\'chiq';
  $('#styleBadge').className = 'badge' + (auto ? ' accent' : '');
}
function renderVoiceMenu() {
  const item = (id, name, sub) => `<button class="menu-item ${state.voiceId === id ? 'on' : ''}" data-voice="${esc(id)}">
    <span class="avatar" style="${avatarStyle(id ? name : '')}">${id ? '' : icon('i-sparkle', 'icon xs')}</span>
    <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(name)}</span><span class="sub">${esc(sub)}</span></button>`;
  $('#voiceMenu').innerHTML = item('', 'Avtomatik ovoz', 'model tanlaydi') +
    (state.voices.length ? '<div class="menu-sep"></div><div class="menu-title">Mening ovozlarim</div>' : '') +
    state.voices.map(v => item(v.id, v.name, `${v.duration_s}s`)).join('') +
    `<div class="menu-sep"></div><button class="menu-item" data-action="clone">${icon('i-plus')}Yangi ovoz klonlash</button>`;
}
function toggleVoiceMenu(e) { e.stopPropagation(); const m = $('#voiceMenu'); closeMenus(m); m.hidden = !m.hidden; }
$('#voiceSelect').onclick = toggleVoiceMenu;
$('#voiceChip').onclick = (e) => { toggleVoiceMenu(e); $('#voiceMenu').scrollIntoView({ block: 'nearest' }); };
$('#voiceMenu').onclick = (e) => {
  const b = e.target.closest('[data-voice]'); if (!b) return;
  state.voiceId = b.dataset.voice; renderVoicePick(); renderVoiceMenu(); closeMenus();
};
function useVoice(id) { state.voiceId = id; renderVoicePick(); renderVoiceMenu(); go('tts'); }

function renderVoiceGrid() {
  const g = $('#voiceGrid');
  if (!state.voices.length) {
    g.style.display = 'block';
    g.innerHTML = `<div class="card"><div class="empty"><div class="art">${icon('i-mic', 'icon')}</div><h3>Hali ovoz yo'q</h3>
      <p style="margin:0 0 16px">3–10 soniyalik yozuvdan istalgan ovozni klonlang.</p>
      <button class="btn primary" data-action="clone">${icon('i-plus')}Birinchi ovozni qo'shish</button></div></div>`;
    return;
  }
  g.style.display = '';
  g.innerHTML = state.voices.map(v => `<div class="voice-card">
    <div class="head"><span class="avatar lg" style="${avatarStyle(v.name)}"></span>
      <div style="min-width:0"><div class="name" data-rename="${esc(v.id)}" title="Nomini o'zgartirish" style="cursor:text">${esc(v.name)}</div><div class="sub">${v.duration_s}s namuna · ${ago(v.created_at)}</div></div>${v.mood && v.mood !== 'neutral' ? `<span class="badge mood" style="margin-left:auto">${esc(MOOD_LABEL[v.mood] || v.mood)}</span>` : ''}</div>
    <div class="ref">${esc(v.ref_text)}</div>
    <div class="foot">
      <button class="btn sm" data-use="${esc(v.id)}">Ishlatish</button>
      <button class="icon-btn" data-preview="${esc(v.id)}" title="Namunani tinglash">${icon('i-play')}</button>
      <button class="icon-btn" data-rename="${esc(v.id)}" title="Nomini o'zgartirish">${icon('i-pencil')}</button>
      <button class="icon-btn danger" data-del="${esc(v.id)}" title="O'chirish">${icon('i-trash')}</button>
    </div></div>`).join('');
}
$('#voiceGrid').onclick = async (e) => {
  const u = e.target.closest('[data-use]'), p = e.target.closest('[data-preview]'), d = e.target.closest('[data-del]'), rn = e.target.closest('[data-rename]');
  if (u) useVoice(u.dataset.use);
  if (rn) renameVoice(rn.dataset.rename);
  if (p) playUrl(`/voices/${p.dataset.preview}/reference`, voiceById(p.dataset.preview)?.name, 'Namuna', null, voiceById(p.dataset.preview)?.ref_text);
  if (d) {
    const v = voiceById(d.dataset.del);
    if (!confirm(`"${v?.name}" ovozini o'chirasizmi? Buni qaytarib bo'lmaydi.`)) return;
    await api(`/voices/${d.dataset.del}`, { method: 'DELETE' }); toast('Ovoz o\'chirildi'); loadVoices();
  }
};

/* ---------------- player ---------------- */
const audio = new Audio();
let peaks = [];
async function computePeaks(url, n = 140) {
  try {
    const buf = await (await fetch(url)).arrayBuffer();
    const ctx = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(1, 1, 24000);
    const data = (await ctx.decodeAudioData(buf)).getChannelData(0);
    const step = Math.floor(data.length / n) || 1, out = [];
    for (let i = 0; i < n; i++) { let m = 0; for (let j = i * step; j < (i + 1) * step && j < data.length; j++) m = Math.max(m, Math.abs(data[j])); out.push(m); }
    const mx = Math.max(...out, 0.01); return out.map(v => v / mx);
  } catch { return Array.from({ length: n }, () => .3 + Math.random() * .5); }
}
function drawWave() {
  const p = audio.duration ? audio.currentTime / audio.duration : 0;
  const w = $('#wave');
  if (w.children.length !== peaks.length) w.innerHTML = peaks.map(v => `<i style="height:${Math.max(8, v * 100)}%"></i>`).join('');
  [...w.children].forEach((el, i) => el.classList.toggle('on', i / peaks.length < p));
  $('#plTime').textContent = `${fmtTime(audio.currentTime)} / ${fmtTime(audio.duration)}`;
}
async function playUrl(url, t1, t2, historyId = null, text = '') {
  state.playText = text;
  $('#player').hidden = false;
  $('#plT1').textContent = t1 || 'Audio'; $('#plT2').textContent = t2 || '';
  $('#plDownload').hidden = !historyId; $('#plDownload').dataset.id = historyId || '';
  state.playingId = historyId; markPlaying();
  peaks = await computePeaks(url); $('#wave').innerHTML = '';
  audio.src = url; audio.play(); drawWave();
}
audio.ontimeupdate = drawWave;
audio.onplay = audio.onpause = audio.onended = () => { $('#playBtn use').setAttribute('href', audio.paused ? '#i-play' : '#i-pause'); drawWave(); };
$('#playBtn').onclick = () => { if (stage.ctx) stage.ctx.resume(); audio.paused ? audio.play() : audio.pause(); };
$('#wave').onclick = (e) => { const r = e.currentTarget.getBoundingClientRect(); if (audio.duration) audio.currentTime = (e.clientX - r.left) / r.width * audio.duration; };
$('#plDownload').onclick = () => saveHistory($('#plDownload').dataset.id);
async function saveHistory(id) {
  if (!id) return;
  if (isDesktop()) {
    try { const p = await window.pywebview.api.save_history(id, state.format); if (p) toast('Saqlandi: ' + p); }
    catch (e) { toast(String(e), true); }
  } else {
    const a = document.createElement('a'); a.href = `/history/${id}/audio?format=${state.format}`; a.download = `ovozlab-${id}.${state.format}`; a.click();
  }
}

/* ---------------- generate ---------------- */
async function generate() {
  const text = ta.value.trim();
  if (!text) { toast('Avval matn yozing', true); return; }
  if (text.length > MAX_CHARS) { toast('Matn 5 000 belgidan oshmasligi kerak', true); return; }
  if (!isReady()) { toast(state.health?.status === 'error' ? 'Model yuklanmadi — Sozlamalarni tekshiring' : 'Model hali yuklanmoqda — tayyor bo\'lishi bilan tugma faollashadi', true); return; }
  const btn = $('#genBtn'); btn.disabled = true; $('#genLabel').innerHTML = '<span class="spinner" style="border-top-color:var(--primary-text);border-color:color-mix(in srgb,var(--primary-text) 30%,transparent);border-top-color:var(--primary-text)"></span> Yaratilmoqda…';
  const body = { text, voice_id: state.voiceId || null, language: 'uz', format: 'wav', num_step: state.quality, mood: state.mood };
  if (+speed.value !== 1) body.speed = +speed.value;
  if ($('#seedOn').checked) body.seed = parseInt($('#seed').value, 10) || 0;
  if (!state.voiceId) {
    const st = [getGender(), $('#stAge').value, $('#stPitch').value, $('#stWhisper').checked ? 'whisper' : ''].filter(Boolean);
    if (st.length) body.instruct = st.join(', ');
  }
  const t0 = performance.now();
  try {
    const r = await api('/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const id = r.headers.get('X-History-Id');
    const url = URL.createObjectURL(await r.blob());
    const dur = r.headers.get('X-Audio-Duration');
    const v = voiceById(state.voiceId);
    const used = voiceById(r.headers.get('X-Voice-Used')) || v;
    const ms = r.headers.get('X-Mood-Source'), ml = MOOD_LABEL[state.mood];
    const moodTxt = ms === 'profile' ? ` · ${ml} (yozuvdan)` : ms === 'approx' ? ` · ${ml} (taxminiy)` : '';
    await playUrl(url, used ? used.name : 'Avtomatik ovoz', `${(+dur).toFixed(1)}s · ${((performance.now() - t0) / 1000).toFixed(1)}s da yaratildi${moodTxt}`, id, text);
    if (!$('[data-pane="history"]').hidden) loadHistory();
  } catch (e) { toast(e.message, true); }
  btn.disabled = false; $('#genLabel').textContent = 'Ovoz yaratish';
}
$('#genBtn').onclick = generate;
document.addEventListener('keydown', (e) => { if (e.ctrlKey && e.key === 'Enter' && $('.view.active')?.dataset.view === 'tts') { e.preventDefault(); generate(); } });

/* ---------------- history ---------------- */
async function loadHistory() {
  state.history = await json('/history');
  const list = $('#historyList');
  $('#histCount').textContent = state.history.length ? `${state.history.length} ta yozuv` : '';
  $('#histClear').hidden = !state.history.length;
  if (!state.history.length) {
    list.innerHTML = `<div class="empty"><div class="art">${icon('i-wave', 'icon')}</div><h3>Tarix bo'sh</h3>Yaratilgan audiolar shu yerda saqlanadi.</div>`;
    return;
  }
  list.innerHTML = state.history.map(h => `<div class="history-item" data-id="${h.id}">
    <span class="avatar" style="${avatarStyle(h.voice_id ? h.voice_name : '')};margin-top:2px">${h.voice_id ? '' : icon('i-sparkle', 'icon xs')}</span>
    <div class="body"><div class="txt">${esc(h.text)}</div><div class="sub">${esc(h.voice_name)} · ${h.duration_s}s · ${ago(h.created_at)}</div></div>
    <div class="acts"><button class="icon-btn" data-save="${h.id}" title="Saqlash">${icon('i-download')}</button>
    <button class="icon-btn danger" data-hdel="${h.id}" title="O'chirish">${icon('i-trash')}</button></div></div>`).join('');
  markPlaying();
}
function markPlaying() { $$('.history-item').forEach(el => el.classList.toggle('playing', el.dataset.id === state.playingId)); }
$('#historyList').onclick = async (e) => {
  const s = e.target.closest('[data-save]'), d = e.target.closest('[data-hdel]'), it = e.target.closest('.history-item');
  if (s) { e.stopPropagation(); return saveHistory(s.dataset.save); }
  if (d) { e.stopPropagation(); await api(`/history/${d.dataset.hdel}`, { method: 'DELETE' }); return loadHistory(); }
  if (it) {
    const h = state.history.find(x => x.id === it.dataset.id);
    playUrl(`/history/${h.id}/audio`, h.voice_name, `${h.duration_s}s · ${ago(h.created_at)}`, h.id, h.text);
  }
};
$('#histClear').onclick = async () => {
  if (!confirm('Butun tarixni o\'chirasizmi? Audio fayllar ham o\'chadi.')) return;
  await api('/history', { method: 'DELETE' }); loadHistory();
};

/* ---------------- clone modal ---------------- */
// Yozib olishda o'qish uchun matnlar — kayfiyat bo'yicha. Har biri ~10–14 soniyada o'qiladi.
const MOODS = {
  neutral: { label: 'Oddiy', suffix: '', how: 'Tabiiy, xotirjam ohangda o\'qing', scripts: [
    "Assalomu alaykum. Bugun ob-havo ancha iliq, shuning uchun ishdan keyin bog'da biroz sayr qilmoqchiman. Siz ham men bilan borasizmi?",
    "Toshkentdan Samarqandgacha poyezdda ikki soatcha yo'l bor. Yo'lda choy ichib, kitob o'qib, derazadan go'zal manzaralarni tomosha qilish mumkin.",
    "Har kuni ertalab yarim soat kitob o'qish odati fikrlashni kengaytiradi, so'z boyligini oshiradi va kunni yaxshi kayfiyat bilan boshlashga yordam beradi.",
  ] },
  happy: { label: 'Quvnoq', suffix: 'quvnoq', how: 'Tabassum bilan, quvnoq ohangda o\'qing', scripts: [
    "Voy, qanday ajoyib yangilik! Nihoyat imtihondan a'lo baho oldim! Bugun kechqurun hammamiz birga bayram qilamiz, albatta kelinglar!",
    "Bugun shunday yaxshi kayfiyatdaman! Quyosh charaqlab turibdi, do'stlarim bilan uchrashamiz, yana sevimli oshimni ham pishiramiz!",
  ] },
  serious: { label: 'Jiddiy', suffix: 'jiddiy', how: 'Aniq, ishonchli va rasmiy ohangda o\'qing', scripts: [
    "Hurmatli hamkasblar, bugungi yig'ilishda kompaniyamizning yillik natijalari va kelgusi rejalarimizni muhokama qilamiz. Iltimos, diqqat bilan tinglang.",
    "Xavfsizlik qoidalariga rioya qilish har birimizning burchimiz. Binoni tark etishda chiroqlarni o'chiring va eshiklarni qulflashni unutmang.",
  ] },
  sad: { label: "G'amgin", suffix: "g'amgin", how: 'Sekin, past va mungli ohangda o\'qing', scripts: [
    "Bilasizmi, ba'zan eski suratlarni ko'rib, o'tgan kunlarni sog'inib ketaman. Bolalikdagi o'sha beg'ubor kunlar endi hech qachon qaytmaydi.",
    "U ketganidan beri uy juda jimjit bo'lib qoldi. Har oqshom derazadan ko'chaga qarab, uning qaytishini kutaman.",
  ] },
  story: { label: 'Hikoyachi', suffix: 'hikoya', how: 'Ertak aytayotgandek, ifodali o\'qing', scripts: [
    "Qadim zamonlarda, tog'lar orasidagi kichik bir qishloqda, juda dono va mehribon bir chol yashagan ekan. Uning bog'ida sehrli olma daraxti o'sar ekan.",
    "Va shu payt eshik sekin ochildi... Xonaga kim kirganini ko'rib, hammamiz hayratdan qotib qoldik. Bu haqiqatan ham u edi!",
  ] },
};
const REC_MAX_S = 20, REC_GOOD_MIN = 5, REC_GOOD_MAX = 15;

let cloneAudio = null, cloneName = '', cloneScript = '';
function openClone(opts = {}) {
  closeMenus(); cloneAudio = null; cloneScript = '';
  let mode = opts.mode || 'record', mood = opts.mood || 'neutral', scriptIdx = 0;
  const bg = document.createElement('div'); bg.className = 'modal-bg'; bg.id = 'cloneModal';
  bg.innerHTML = `<div class="modal" role="dialog" aria-label="Ovoz klonlash" style="width:min(600px,100%)">
    <div class="modal-head"><h3>Ovoz klonlash</h3><button class="icon-btn" data-close>${icon('i-x')}</button></div>
    <div class="modal-body">
      <div class="mode-tabs"><button data-mode="record">${icon('i-mic')}Yozib olish</button><button data-mode="upload">${icon('i-upload')}Fayl yuklash</button></div>

      <div id="cRecord">
        <div class="moods" id="cMoods">${Object.entries(MOODS).map(([k, m]) => `<button class="mood" data-mood="${k}">${m.label}</button>`).join('')}</div>
        <div class="script" id="cScript">
          <div class="how"><span id="cHow"></span><button class="btn sm ghost" id="cShuffle" style="margin:-6px -8px -6px 0">${icon('i-shuffle', 'icon xs')}Boshqa matn</button></div>
          <div class="txt" id="cScriptTxt"></div>
        </div>
        <div class="rec-big"><button class="btn rec-btn" id="recBtn"><span class="rec-dot"></span><span id="recLbl">Yozishni boshlash</span></button>
          <div class="meter"><i id="meter"></i></div><span class="hint mono" id="recTime" style="width:38px;text-align:right">0:00</span></div>
        <div class="len-hint" id="lenHint">Matnni ovoz chiqarib o'qing. 5–15 soniya eng yaxshi natija beradi.</div>
      </div>

      <div id="cUpload" hidden>
        <label class="drop" id="drop"><input type="file" accept="audio/*" hidden id="cFile">
          ${icon('i-upload', 'icon')}<div class="t1">Audio faylni tanlang yoki shu yerga tashlang</div>
          <div class="t2">WAV, MP3, M4A, OGG · 5–15 soniya · bitta odam ovozi, shovqinsiz</div></label>
      </div>

      <div id="srcPicked" hidden style="margin-top:14px">
        <div class="file-pill"><span class="avatar">${icon('i-file', 'icon xs')}</span><span class="n" id="cFileName"></span>
          <button class="icon-btn" id="cPlay" title="Tinglash">${icon('i-play')}</button><button class="icon-btn" id="cReset" title="Qaytadan">${icon('i-x')}</button></div>
      </div>

      <div style="margin-top:18px" id="cTextWrap">
        <div class="label-row"><span class="label">Audioda aytilgan matn</span><span class="hint" id="cTextHint">ixtiyoriy</span></div>
        <textarea class="textarea" id="cText" rows="3" placeholder="Bo'sh qoldirsangiz, avtomatik aniqlanadi"></textarea>
        <div class="row-between" style="margin-top:8px"><span class="hint">Matn audio bilan so'zma-so'z mos bo'lsa, klon aniqroq chiqadi</span>
          <button class="btn sm" id="cAsr">${icon('i-sparkle', 'icon xs')}Avtomatik aniqlash</button></div>
      </div>
      <div style="margin-top:16px"><span class="label">Ovoz nomi</span><input class="input" id="cName" maxlength="80" placeholder="Masalan: Dilshod"></div>
    </div>
    <div class="modal-foot"><button class="btn" data-close>Bekor qilish</button><button class="btn primary" id="cSave">Ovozni saqlash</button></div>
  </div>`;
  document.body.append(bg);
  const close = () => { stopRec(true); bg.remove(); };
  bg.addEventListener('click', (e) => { if (e.target === bg || e.target.closest('[data-close]')) close(); });

  const render = () => {
    $$('.mode-tabs button', bg).forEach(b => b.classList.toggle('on', b.dataset.mode === mode));
    $$('.mood', bg).forEach(b => b.classList.toggle('on', b.dataset.mood === mood));
    const m = MOODS[mood];
    $('#cHow').textContent = m.how;
    $('#cScriptTxt').textContent = m.scripts[scriptIdx % m.scripts.length];
    const picked = !!cloneAudio;
    $('#cRecord').hidden = mode !== 'record';
    $('#cTextWrap').hidden = mode === 'record' && !picked;
    $('#cUpload').hidden = mode !== 'upload' || picked;
    $('#srcPicked').hidden = !picked;
    if (mode === 'record') { $('.rec-big', bg).hidden = picked; $('#cScript').hidden = false; $('#cMoods').hidden = picked; $('#lenHint').hidden = picked; }
  };
  const suggestName = () => {
    const n = $('#cName'); const base = n.value.replace(/\s+—\s+\S+$/, '').trim();
    const sfx = MOODS[mood].suffix;
    if (!n.dataset.touched) n.value = base ? base + (sfx ? ` — ${sfx}` : '') : '';
    n.placeholder = 'Masalan: Dilshod' + (sfx ? ` — ${sfx}` : '');
  };
  $('#cName').oninput = () => { $('#cName').dataset.touched = $('#cName').value ? '1' : ''; };
  $$('.mode-tabs button', bg).forEach(b => b.onclick = () => { if (recorder) return; mode = b.dataset.mode; reset(); });
  $('#cMoods').onclick = (e) => { const b = e.target.closest('[data-mood]'); if (!b || recorder) return; mood = b.dataset.mood; scriptIdx = 0; suggestName(); render(); };
  $('#cShuffle').onclick = () => { if (recorder) return; scriptIdx++; render(); };

  const setAudio = (blob, name, script = '') => {
    cloneAudio = blob; cloneName = name; cloneScript = script;
    $('#cFileName').textContent = name;
    if (script) { $('#cText').value = script; $('#cTextHint').textContent = 'o\'qilgan matn — xato o\'qigan bo\'lsangiz tuzating'; }
    render();
  };
  const reset = () => {
    cloneAudio = null; cloneScript = ''; $('#cFile').value = '';
    if (mode === 'upload') { $('#cText').value = ''; }
    $('#cTextHint').textContent = 'ixtiyoriy'; render();
  };
  $('#cFile').onchange = () => { const f = $('#cFile').files[0]; if (f) setAudio(f, f.name); };
  const drop = $('#drop');
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); const f = e.dataTransfer.files[0]; if (f) setAudio(f, f.name); };
  $('#cReset').onclick = reset;
  $('#cPlay').onclick = () => new Audio(URL.createObjectURL(cloneAudio)).play();
  $('#recBtn').onclick = () => {
    if (recorder) return stopRec();
    const script = $('#cScriptTxt').textContent;
    $('#cScript').classList.add('recording');
    startRec({
      btn: $('#recBtn'), label: $('#recLbl'), meter: () => $('#meter'), time: $('#recTime'), maxS: REC_MAX_S,
      onTick: (s) => {
        const h = $('#lenHint');
        h.className = 'len-hint' + (s >= REC_GOOD_MIN ? ' good' : '');
        h.textContent = s < REC_GOOD_MIN ? 'Davom eting…' : s <= REC_GOOD_MAX ? 'Yaxshi uzunlik — matnni tugatgach to\'xtating' : `Maksimum ${REC_MAX_S} soniya`;
      },
      onDone: (blob, secs) => {
        $('#cScript').classList.remove('recording');
        if (secs < 3) { toast('Yozuv juda qisqa — kamida 5 soniya o\'qing', true); return; }
        setAudio(blob, `Mikrofon yozuvi · ${secs.toFixed(0)}s · ${MOODS[mood].label}`, script);
      },
    });
  };
  $('#cAsr').onclick = async () => {
    if (!cloneAudio) return toast('Avval audio tanlang yoki yozib oling', true);
    const b = $('#cAsr'); b.disabled = true; b.innerHTML = '<span class="spinner"></span>Aniqlanmoqda…';
    try {
      const fd = new FormData(); fd.append('audio', cloneAudio, 'audio.webm');
      const r = await json('/transcribe', { method: 'POST', body: fd });
      $('#cText').value = r.text; toast('Matn aniqlandi — tekshirib chiqing');
    } catch (e) { toast(e.message, true); }
    b.disabled = false; b.innerHTML = icon('i-sparkle', 'icon xs') + 'Avtomatik aniqlash';
  };
  $('#cSave').onclick = async () => {
    if (!cloneAudio) return toast(mode === 'record' ? 'Avval matnni o\'qib, yozib oling' : 'Avval audio fayl tanlang', true);
    if (!isReady()) return toast('Model hali yuklanmoqda — biroz kuting', true);
    const b = $('#cSave'); b.disabled = true;
    b.innerHTML = '<span class="spinner" style="border-color:color-mix(in srgb,var(--primary-text) 30%,transparent);border-top-color:var(--primary-text)"></span>' + ($('#cText').value.trim() ? 'Saqlanmoqda…' : 'Matn aniqlanmoqda…');
    try {
      const fd = new FormData();
      fd.append('audio', cloneAudio, 'reference.webm'); fd.append('ref_text', $('#cText').value.trim());
      const sfx = mode === 'record' ? MOODS[mood].suffix : '';
      fd.append('name', $('#cName').value.trim() || ('Mening ovozim' + (sfx ? ` — ${sfx}` : ''))); fd.append('language', 'uz');
      if (mode === 'record') fd.append('mood', mood);
      const v = await json('/clone', { method: 'POST', body: fd });
      await loadVoices(); close(); useVoice(v.id);
      toast(`"${v.name}" saqlandi` + (v.ref_text_auto ? ' (matn avtomatik aniqlandi)' : ''));
    } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = 'Ovozni saqlash'; }
  };
  if (opts.name) { $('#cName').value = opts.name; }
  suggestName(); render();
}

/* ---------------- microphone recorder (clone + stt) ---------------- */
let recorder = null, recTimer = null, meterRaf = null;
async function startRec({ btn, label, meter, time, maxS, onTick, onDone }) {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const chunks = []; recorder = new MediaRecorder(stream);
    const ctx = new AudioContext(), an = ctx.createAnalyser(); an.fftSize = 512; ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    const tick = () => { an.getByteTimeDomainData(buf); let m = 0; for (const v of buf) m = Math.max(m, Math.abs(v - 128)); const el = meter(); if (el) el.style.width = Math.min(100, m / 1.1) + '%'; meterRaf = requestAnimationFrame(tick); };
    tick();
    const t0 = Date.now(), oldLabel = label.textContent;
    recorder.ondataavailable = (e) => chunks.push(e.data);
    recorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop()); ctx.close(); cancelAnimationFrame(meterRaf); clearInterval(recTimer);
      btn.classList.remove('on'); label.textContent = oldLabel; const el = meter(); if (el) el.style.width = '0';
      const discard = recorder._discard; recorder = null;
      if (!discard) onDone(new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' }), (Date.now() - t0) / 1000);
    };
    recorder.start(250);
    btn.classList.add('on'); label.textContent = 'To\'xtatish';
    recTimer = setInterval(() => { const s = (Date.now() - t0) / 1000; time.textContent = fmtTime(s); onTick && onTick(s); if (maxS && s >= maxS) stopRec(); }, 200);
  } catch (e) { toast('Mikrofonga ruxsat berilmadi: ' + e.message, true); }
}
function stopRec(discard = false) { if (recorder) { recorder._discard = discard; recorder.stop(); } }

/* ---------------- rename voice ---------------- */
function renameVoice(id) {
  const v = voiceById(id); if (!v) return;
  const bg = document.createElement('div'); bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal" style="width:min(420px,100%)"><div class="modal-head"><h3>Nomini o'zgartirish</h3><button class="icon-btn" data-close>${icon('i-x')}</button></div>
    <div class="modal-body"><input class="input" id="rnName" maxlength="80" value="${esc(v.name)}"></div>
    <div class="modal-foot"><button class="btn" data-close>Bekor qilish</button><button class="btn primary" id="rnSave">Saqlash</button></div></div>`;
  document.body.append(bg);
  const inp = $('#rnName', bg); inp.focus(); inp.select();
  const close = () => bg.remove();
  bg.addEventListener('click', (e) => { if (e.target === bg || e.target.closest('[data-close]')) close(); });
  const save = async () => {
    const name = inp.value.trim(); if (!name) return toast('Nom bo\'sh bo\'lmasligi kerak', true);
    try {
      await json(`/voices/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
      close(); await loadVoices(); toast('Nom o\'zgartirildi');
    } catch (e) { toast(e.message, true); }
  };
  $('#rnSave', bg).onclick = save;
  inp.onkeydown = (e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') close(); };
}

/* ---------------- speech to text ---------------- */
const stt = { result: null, name: '', poll: null };
async function checkSttModel() {
  let s; try { s = await json('/api/system'); } catch { return; }
  const asr = s.models.find(m => m.id === 'asr');
  const need = !asr.present || !s.settings.asr_enabled;
  $('#sttNeedModel').hidden = !need; $('#sttMain').hidden = need;
  if (need) renderSttNeed(asr);
}
function renderSttNeed(asr, p) {
  const box = $('#sttNeedModel');
  const running = p && p.state === 'running';
  const step = p?.steps?.find(x => x.id === 'asr');
  box.innerHTML = `<div class="card"><div class="empty" style="padding:40px 24px">
    <div class="art">${icon('i-text', 'icon')}</div><h3>O'zbekcha Whisper modeli kerak</h3>
    <p style="margin:0 auto 16px;max-width:440px">Nutqni matnga o'girish uchun o'zbek tiliga moslashtirilgan Whisper modeli bir marta yuklab olinadi (${fmtBytes(asr.size)}). Keyin internetsiz ishlaydi.</p>
    ${running ? `<div style="max-width:360px;margin:0 auto"><div class="bar big"><i style="width:${step ? Math.min(100, step.bytes_done / step.bytes_total * 100) : 0}%"></i></div>
      <div class="hint" style="margin-top:8px">${fmtBytes(step?.bytes_done)} / ${fmtBytes(step?.bytes_total)} · ${esc(step?.where || '')}</div></div>`
      : p && p.state === 'error' ? `<p style="color:var(--danger)">${esc(p.error)}</p><button class="btn primary" id="sttGet">Qayta urinish</button>`
      : `<button class="btn primary" id="sttGet">${icon('i-download')}Yuklab olish</button>`}
  </div></div>`;
  const b = $('#sttGet');
  if (b) b.onclick = async () => {
    try { renderSttNeed(asr, await post('/api/setup/start', { only: ['asr'] })); } catch (e) { return toast(e.message, true); }
    clearInterval(stt.poll);
    stt.poll = setInterval(async () => {
      const pr = await json('/api/setup/progress');
      if (pr.state === 'running') renderSttNeed(asr, pr);
      else { clearInterval(stt.poll); if (pr.state === 'done') { toast('Model yuklandi'); checkSttModel(); } else renderSttNeed(asr, pr); }
    }, 1000);
  };
}
async function runStt(blob, name) {
  stt.name = name;
  $('#sttResult').hidden = false; $('#sttName').textContent = name; $('#sttMeta').textContent = '';
  $('#sttLoading').hidden = false; $('#sttText').value = ''; $('#sttSegs').innerHTML = '';
  $('#sttLoadingText').textContent = 'Matnga o\'girilmoqda… (birinchi marta Whisper modeli xotiraga yuklanadi)';
  try {
    const fd = new FormData(); fd.append('audio', blob, name);
    const r = stt.result = await json('/stt', { method: 'POST', body: fd });
    $('#sttText').value = r.text;
    $('#sttMeta').textContent = `${fmtTime(r.duration_s)} audio · ${r.elapsed_s}s da o'girildi · ${r.text.split(/\s+/).filter(Boolean).length} so'z`;
    $('#sttSegs').innerHTML = r.segments.map(s => `<div class="stt-seg"><span class="ts">${fmtTime(s.start)} – ${fmtTime(s.end)}</span><span>${esc(s.text)}</span></div>`).join('')
      || '<div class="empty">Nutq topilmadi</div>';
  } catch (e) { toast(e.message, true); $('#sttResult').hidden = true; }
  $('#sttLoading').hidden = true;
}
seg('sttMode', v => { $('#sttText').hidden = v !== 'text'; $('#sttSegs').hidden = v !== 'seg'; });
$('#sttFile').onchange = () => { const f = $('#sttFile').files[0]; if (f) runStt(f, f.name); $('#sttFile').value = ''; };
(() => {
  const d = $('#sttDrop');
  d.ondragover = (e) => { e.preventDefault(); d.classList.add('over'); };
  d.ondragleave = () => d.classList.remove('over');
  d.ondrop = (e) => { e.preventDefault(); d.classList.remove('over'); const f = e.dataTransfer.files[0]; if (f) runStt(f, f.name); };
})();
$('#sttRec').onclick = () => recorder ? stopRec() : startRec({
  btn: $('#sttRec'), label: $('#sttRecLbl'), meter: () => $('#sttMeter'), time: $('#sttRecTime'), maxS: 60 * 60,
  onDone: (blob, secs) => secs < 1.5 ? toast('Yozuv juda qisqa', true) : runStt(blob, `Mikrofon yozuvi · ${fmtTime(secs)}`),
});
const srtTime = (s) => { const ms = Math.round(s * 1000); const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, sec = Math.floor(ms / 1000) % 60; return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')},${String(ms % 1000).padStart(3, '0')}`; };
function downloadText(text, filename) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' })); a.download = filename; a.click();
}
const baseName = () => (stt.name || 'ovozlab').replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|·]+/g, '').trim() || 'ovozlab';
$('#sttCopy').onclick = async () => { try { await navigator.clipboard.writeText($('#sttText').value); toast('Nusxalandi'); } catch { $('#sttText').select(); document.execCommand('copy'); toast('Nusxalandi'); } };
$('#sttTxt').onclick = () => downloadText($('#sttText').value, baseName() + '.txt');
$('#sttSrt').onclick = () => {
  if (!stt.result) return;
  downloadText(stt.result.segments.map((s, i) => `${i + 1}\n${srtTime(s.start)} --> ${srtTime(s.end)}\n${s.text}\n`).join('\n'), baseName() + '.srt');
};
$('#sttToTts').onclick = () => { ta.value = $('#sttText').value.slice(0, MAX_CHARS); syncEditor(); go('tts'); };

/* ---------------- settings ---------------- */
async function renderSettings() {
  const body = $('#settingsBody');
  let s;
  try { s = await json('/api/system'); } catch (e) { body.innerHTML = `<div class="card"><div class="empty">${esc(e.message)}</div></div>`; return; }
  const BK = { xpu: 'Intel Arc (XPU)', cuda: 'NVIDIA (CUDA)', cpu: 'Protsessor (CPU)' };
  const openBtn = (t) => `<button class="btn sm" data-open="${t}">${icon('i-folder', 'icon xs')}Ochish</button>`;
  body.innerHTML = `
    <div class="card"><div class="card-head"><h3>Qurilma va model</h3><p>Nutq sintezi qayerda bajarilishi.</p></div>
      <div class="set-row"><div class="k"><div class="t1">Hisoblash qurilmasi</div><div class="t2">${esc(s.device_name || BK[s.backend] || '—')}</div></div><span class="badge">${esc(BK[s.installed_backend] || 'O\'rnatilmagan')}</span></div>
      <div class="set-row"><div class="k"><div class="t1">Modellar</div><div class="t2">${s.models.map(m => `${esc(m.label.split(' — ')[0])}: ${m.present ? 'yuklangan' : 'yo\'q'}`).join(' · ')}</div></div>
        <button class="btn sm" id="reSetup">${icon('i-refresh', 'icon xs')}Qayta sozlash</button></div>
    </div>
    <div class="card"><div class="card-head"><h3>Saqlash joylari</h3><p>Fayllaringiz kompyuterdan tashqariga chiqmaydi.</p></div>
      <div class="set-row"><div class="k"><div class="t1">Modellar papkasi <span class="hint" id="szModels"></span></div><div class="t2 mono">${esc(s.models_dir)}</div></div>${openBtn('models')}</div>
      <div class="set-row"><div class="k"><div class="t1">Ovozlar va tarix <span class="hint" id="szData"></span></div><div class="t2 mono">${esc(s.data_dir)}</div></div>${openBtn('data')}</div>
      <div class="set-row"><div class="k"><div class="t1">Ilova papkasi</div><div class="t2 mono">${esc(s.app_dir)}</div></div>${openBtn('app')}</div>
      <div class="set-row"><div class="k"><div class="t1">Bo'sh joy</div><div class="t2">${fmtBytes(s.free_bytes)} — modellar diskida</div></div></div>
    </div>
    <div class="card"><div class="card-head"><h3>Imkoniyatlar</h3></div>
      <label class="set-row" style="cursor:pointer"><div class="k"><div class="t1">Matnni avtomatik aniqlash</div><div class="t2">Klonlashda audiodagi gapni o'zbekcha Whisper yozib beradi (~3 GB model)</div></div>
        <span class="switch"><input type="checkbox" id="setAsr" ${s.settings.asr_enabled ? 'checked' : ''}><span></span></span></label>
      <div class="set-row"><div class="k"><div class="t1">Mavzu</div><div class="t2">Ilova ko'rinishi</div></div>
        <div class="seg" id="theme" style="width:240px"><button data-v="">Tizim</button><button data-v="light">Yorug'</button><button data-v="dark">Qorong'i</button></div></div>
    </div>
    <div class="card"><div class="card-head"><h3>Dasturchilar uchun</h3></div>
      <div class="set-row"><div class="k"><div class="t1">Lokal API</div><div class="t2 mono">${esc(location.origin)}</div></div><button class="btn sm" data-link="api">${icon('i-external', 'icon xs')}Hujjatlar</button></div>
    </div>
    <div class="card"><div class="card-head"><h3>OvozLab haqida</h3></div>
      <div class="set-row"><div class="k"><div class="t1">Versiya ${esc(s.version)}</div><div class="t2">Ochiq kod, Apache-2.0 litsenziyasi · Python ${esc(s.python)}</div></div><button class="btn sm" data-link="github">${icon('i-github', 'icon xs')}GitHub</button></div>
      <div class="set-row"><div class="k"><div class="t2" style="word-break:normal">Nutq modeli: OmniVoice (k2-fsa, Xiaomi) · O'zbekcha Whisper: navai-uz · Shrift: Inter (OFL). Mualliflarga rahmat.</div></div></div>
    </div>`;
  $$('[data-open]', body).forEach(b => b.onclick = () => post(`/api/system/open/${b.dataset.open}`).catch(e => toast(e.message, true)));
  $('#reSetup').onclick = () => openSetup(true);
  $('#setAsr').onchange = (e) => post('/api/settings', { asr_enabled: e.target.checked }).then(() => toast('Saqlandi'));
  const th = (() => { try { return localStorage.getItem('ovozlab.theme') || ''; } catch { return ''; } })();
  $$('#theme button').forEach(b => b.classList.toggle('on', b.dataset.v === th));
  seg('theme', v => { applyTheme(v); try { localStorage.setItem('ovozlab.theme', v); } catch {} });
  json('/api/system/sizes').then(z => { $('#szModels').textContent = '· ' + fmtBytes(z.models_bytes); $('#szData').textContent = '· ' + fmtBytes(z.data_bytes); }).catch(() => {});
}
function applyTheme(v) { if (v) document.documentElement.dataset.theme = v; else delete document.documentElement.dataset.theme; }
try { applyTheme(localStorage.getItem('ovozlab.theme') || ''); } catch {}

/* ================= SETUP WIZARD ================= */
const W = { step: 0, st: null, backend: null, modelsDir: '', asr: true, poll: null, rerun: false };

async function openSetup(rerun = false) {
  W.rerun = rerun; W.step = 0;
  $('#setup').hidden = false;
  W.st = await json('/api/setup/status');
  W.backend = W.st.selected_backend || W.st.installed_backend || W.st.recommended;
  W.modelsDir = W.st.models_dir; W.asr = W.st.asr_enabled;
  renderSetup();
}
function closeSetup() { $('#setup').hidden = true; clearInterval(W.poll); }

function wizardSteps() {
  $$('#steps li').forEach(li => { const s = +li.dataset.s; li.className = s === W.step ? 'on' : s < W.step ? 'done' : ''; li.querySelector('.n').innerHTML = s < W.step ? icon('i-check', 'icon xs') : s + 1; });
}
function foot(left, right) { $('#setupFoot').innerHTML = `<div>${left || ''}</div><div style="display:flex;gap:8px">${right || ''}</div>`; }
function totalPlan() {
  const items = [];
  const b = W.st.backends.find(x => x.id === W.backend);
  if (b) items.push({ label: 'PyTorch — ' + b.label, size: b.disk, where: W.st.app_dir, have: b.installed });
  for (const m of W.st.models) if (m.required || W.asr) items.push({ label: m.label, size: m.size, where: W.modelsDir, have: m.present && W.modelsDir === W.st.models_dir });
  return items;
}

function renderSetup() {
  wizardSteps();
  const c = $('#setupContent');
  if (W.step === 0) {
    const plan = totalPlan(), need = plan.filter(p => !p.have).reduce((a, p) => a + p.size, 0);
    c.innerHTML = `<h2>${W.rerun ? 'OvozLab sozlamalari' : 'OvozLab\'ga xush kelibsiz'}</h2>
      <p class="lead">O'zbek tilida matnni tabiiy nutqqa aylantiradigan va ovozlarni klonlaydigan ochiq kodli dastur. Hammasi kompyuteringizda ishlaydi.</p>
      <div class="feature-list">
        <div class="feature"><div class="ic">${icon('i-lock', 'icon')}</div><div><div class="t1">Internetsiz va maxfiy</div><div class="t2">Matn va ovozlaringiz hech qayerga yuborilmaydi. O'rnatilgach internet kerak emas.</div></div></div>
        <div class="feature"><div class="ic">${icon('i-mic', 'icon')}</div><div><div class="t1">3 soniyada ovoz klonlash</div><div class="t2">Qisqa yozuvdan istalgan ovozni nusxalab, u bilan gapirtiring.</div></div></div>
        <div class="feature"><div class="ic">${icon('i-heart', 'icon')}</div><div><div class="t1">To'liq ochiq kod</div><div class="t2">Bepul, Apache-2.0 litsenziyasi. Kodni ko'rish, o'zgartirish va ulashish mumkin.</div></div></div>
      </div>
      <div class="callout">${icon('i-info')}<div>Keyingi qadamlarda AI modellar va ular uchun dvigatel yuklab olinadi — taxminan <b>${fmtBytes(need || plan.reduce((a, p) => a + p.size, 0))}</b>. Bu bir marta bajariladi; nima va qayerga yuklanishini oldindan ko'rasiz.</div></div>`;
    foot(W.rerun ? `<button class="btn ghost" id="wCancel">Bekor qilish</button>` : '', `<button class="btn primary lg" id="wNext">Boshlash</button>`);
  }
  if (W.step === 1) {
    const g = W.st.gpus.length ? W.st.gpus.join(', ') : 'Videokarta aniqlanmadi';
    c.innerHTML = `<h2>Qurilmani tanlang</h2>
      <p class="lead">Nutq sintezi videokartada bir necha baravar tez ishlaydi. Kompyuteringizga mos variantni tanladik.</p>
      <div class="detected">${icon('i-cpu')}<div><span class="hint">Topilgan videokarta:</span> <b>${esc(g)}</b></div></div>
      <div class="opt-list">${W.st.backends.map(b => `<button class="opt ${W.backend === b.id ? 'on' : ''}" data-b="${b.id}">
        <span class="radio"></span><span class="body"><span class="t1">${esc(b.label)}
          ${b.id === W.st.recommended ? '<span class="badge accent">Tavsiya etiladi</span>' : ''}${b.installed ? '<span class="badge ok">O\'rnatilgan</span>' : ''}</span>
          <span class="t2">${esc(b.detail)}</span></span><span class="size">${b.installed ? '—' : fmtBytes(b.disk)}</span></button>`).join('')}</div>`;
    $$('.opt[data-b]', c).forEach(o => o.onclick = () => { W.backend = o.dataset.b; renderSetup(); });
    foot(`<button class="btn ghost" id="wBack">Orqaga</button>`, `<button class="btn primary lg" id="wNext">Davom etish</button>`);
  }
  if (W.step === 2) {
    const asrM = W.st.models.find(m => m.id === 'asr'), ttsM = W.st.models.find(m => m.id === 'tts');
    const need = totalPlan().filter(p => !p.have && p.where === W.modelsDir).reduce((a, p) => a + p.size, 0);
    const bad = W.st.free_bytes != null && W.st.free_bytes < need * 1.05;
    c.innerHTML = `<h2>Modellar qayerga saqlansin?</h2>
      <p class="lead">AI modellar katta hajmli. Bo'sh joyi ko'p diskni tanlang — masalan, <span class="mono">D:\\</span>.</p>
      ${W.st.existing_models_dir && W.st.existing_models_dir !== W.modelsDir ? `<div class="callout" style="margin-bottom:18px">${icon('i-info')}<div style="flex:1">Avval yuklangan modellar topildi:<br><span class="mono">${esc(W.st.existing_models_dir)}</span><br>
        <button class="btn sm" id="wUseExisting" style="margin-top:8px">Shundan foydalanish — qayta yuklamaslik</button></div></div>` : ''}
      <span class="label">Modellar papkasi</span>
      <div class="path-row"><input class="input" id="wDir" value="${esc(W.modelsDir)}" spellcheck="false"><button class="btn" id="wPick">${icon('i-folder')}O'zgartirish</button></div>
      <div class="space ${bad ? 'bad' : ''}"><span>Kerak: <b>${fmtBytes(need)}</b></span><span>Bo'sh joy: <b>${fmtBytes(W.st.free_bytes)}</b></span></div>
      <div class="section-title">Komponentlar</div>
      <div class="opt-list">
        <div class="opt on locked"><span class="check">${icon('i-check', 'icon xs')}</span><span class="body"><span class="t1">${esc(ttsM.label)} <span class="badge">Majburiy</span>${ttsM.present ? '<span class="badge ok">Yuklangan</span>' : ''}</span><span class="t2">${esc(ttsM.detail)}</span></span><span class="size">${fmtBytes(ttsM.size)}</span></div>
        <button class="opt ${W.asr ? 'on' : ''}" id="wAsr"><span class="check">${W.asr ? icon('i-check', 'icon xs') : ''}</span><span class="body"><span class="t1">${esc(asrM.label)} <span class="badge">Ixtiyoriy</span>${asrM.present ? '<span class="badge ok">Yuklangan</span>' : ''}</span><span class="t2">${esc(asrM.detail)}. Keyinroq Sozlamalardan yoqish mumkin.</span></span><span class="size">${fmtBytes(asrM.size)}</span></button>
      </div>`;
    const applyDir = async (dir) => {
      try { W.st = await post('/api/setup/config', { models_dir: dir }); W.modelsDir = W.st.models_dir; renderSetup(); }
      catch (e) { toast(e.message, true); }
    };
    $('#wDir').onchange = () => applyDir($('#wDir').value.trim());
    $('#wPick').onclick = async () => {
      if (isDesktop()) { const p = await window.pywebview.api.pick_folder(W.modelsDir); if (p) applyDir(p); }
      else { $('#wDir').focus(); $('#wDir').select(); toast('Yo\'lni qo\'lda kiriting va Enter bosing'); }
    };
    const ue = $('#wUseExisting'); if (ue) ue.onclick = () => applyDir(W.st.existing_models_dir);
    $('#wAsr').onclick = () => { W.asr = !W.asr; renderSetup(); };
    foot(`<button class="btn ghost" id="wBack">Orqaga</button>`, `<button class="btn primary lg" id="wNext" ${bad ? 'disabled' : ''}>Davom etish</button>`);
  }
  if (W.step === 3) renderInstall(null);
  if (W.step === 4) {
    const restart = W.st?.restart_required || W.progress?.restart_required;
    c.innerHTML = `<div class="done-art">${icon('i-check', 'icon')}</div><h2>OvozLab tayyor</h2>
      <p class="lead">${restart ? 'Yangi modellar papkasi kuchga kirishi uchun ilovani bir marta qayta ishga tushiring.' : 'Model fonda yuklanmoqda — bu bir necha soniya oladi. Holatni chap pastki burchakda ko\'rasiz.'}</p>
      <div class="feature-list">
        <div class="feature"><div class="ic">${icon('i-wave', 'icon')}</div><div><div class="t1">Matn yozing va "Ovoz yaratish" ni bosing</div><div class="t2">Yoki Ctrl + Enter. Natijalar "Tarix" bo'limida saqlanadi.</div></div></div>
        <div class="feature"><div class="ic">${icon('i-mic', 'icon')}</div><div><div class="t1">O'z ovozingizni klonlang</div><div class="t2">"Ovoz klonlash" — 3–10 soniyalik toza yozuv yetarli.</div></div></div>
      </div>`;
    foot('', restart && isDesktop() ? `<button class="btn primary lg" id="wRestart">Qayta ishga tushirish</button>` : `<button class="btn primary lg" id="wFinish">OvozLab'ni ochish</button>`);
  }
  bindFoot();
}

function bindFoot() {
  const n = $('#wNext'), b = $('#wBack'), cn = $('#wCancel'), f = $('#wFinish'), r = $('#wRestart');
  if (n) n.onclick = async () => {
    try {
      if (W.step === 1) W.st = await post('/api/setup/config', { backend: W.backend });
      if (W.step === 2) W.st = await post('/api/setup/config', { asr_enabled: W.asr, models_dir: $('#wDir').value.trim() });
    } catch (e) { return toast(e.message, true); }
    W.step++; renderSetup();
  };
  if (b) b.onclick = () => { W.step--; renderSetup(); };
  if (cn) cn.onclick = closeSetup;
  if (f) f.onclick = () => { closeSetup(); loadVoices(); };
  if (r) r.onclick = () => window.pywebview.api.restart();
}

function renderInstall(p) {
  const c = $('#setupContent');
  const running = p && p.state === 'running';
  const steps = p ? p.steps : totalPlan().map(x => ({ label: x.label, where: x.where, bytes_total: x.size, bytes_done: x.have ? x.size : 0, status: x.have ? 'skipped' : 'pending', detail: '' }));
  const total = steps.reduce((a, s) => a + (s.status === 'skipped' ? 0 : s.bytes_total), 0);
  const ST = {
    pending: '<span class="st wait">Kutilmoqda</span>', running: '<span class="st run"><span class="spinner"></span>Yuklanmoqda</span>',
    done: `<span class="st done">${icon('i-check', 'icon xs')}Tayyor</span>`, skipped: `<span class="st done">${icon('i-check', 'icon xs')}Mavjud</span>`,
    error: '<span class="st err">Xato</span>',
  };
  const title = !p ? 'O\'rnatishga tayyor' : p.state === 'running' ? 'O\'rnatilmoqda…' : p.state === 'error' ? 'Xatolik yuz berdi' : p.state === 'cancelled' ? 'To\'xtatildi' : 'O\'rnatildi';
  const lead = !p ? (total ? 'Quyidagilar yuklab olinadi. Internet tezligiga qarab 10–40 daqiqa davom etadi. Bu vaqtda kompyuterdan foydalanishingiz mumkin.'
      : 'Kerakli hamma narsa allaqachon kompyuteringizda bor — hech narsa yuklanmaydi.')
    : p.state === 'error' ? esc(p.error) : p.state === 'running' ? 'Oynani yopmang. Jarayon tugagach, OvozLab avtomatik davom etadi.' : '';
  c.innerHTML = `<h2>${title}</h2><p class="lead">${lead}</p>
    ${p ? `<div class="overall"><div class="row-between"><b>${p.percent.toFixed(0)}%</b><span class="hint">${fmtTime(p.elapsed_s)} o'tdi</span></div><div class="bar big"><i style="width:${p.percent}%"></i></div></div>` : ''}
    <div class="summary">${steps.map(s => `<div class="summary-row">
        <div class="t1">${esc(s.label)}</div><div>${p ? ST[s.status] : `<span class="size">${s.status === 'skipped' ? 'mavjud' : fmtBytes(s.bytes_total)}</span>`}</div>
        <div class="where">${icon('i-drive', 'icon xs')}<span class="mono" title="${esc(s.where)}">${esc(s.where)}</span></div>
        ${p && s.status === 'running' ? `<div class="bar"><i style="width:${Math.min(100, s.bytes_done / s.bytes_total * 100)}%"></i></div><div class="where"><span>${esc(s.detail || '')}</span></div>` : ''}
      </div>`).join('')}
      ${!p ? `<div class="summary-total"><span>Jami yuklanadi</span><span>${fmtBytes(total)}</span></div>` : ''}</div>
    ${p && p.log.length ? `<details class="log"><summary>Batafsil jurnal</summary><pre id="wLog">${esc(p.log.join('\n'))}</pre></details>` : ''}`;
  const logEl = $('#wLog'); if (logEl) logEl.scrollTop = logEl.scrollHeight;
  if (!p) foot(`<button class="btn ghost" id="wBack">Orqaga</button>`, `<button class="btn primary lg" id="wStart">${total ? 'O\'rnatishni boshlash' : 'Davom etish'}</button>`);
  else if (running) foot('', `<button class="btn" id="wStop">Bekor qilish</button>`);
  else if (p.state === 'error' || p.state === 'cancelled') foot(`<button class="btn ghost" id="wBack">Orqaga</button>`, `<button class="btn primary lg" id="wStart">Qayta urinish</button>`);
  bindFoot();
  const s = $('#wStart'), x = $('#wStop');
  if (s) s.onclick = startInstall;
  if (x) x.onclick = () => post('/api/setup/cancel');
}
async function startInstall() {
  try { const p = await post('/api/setup/start'); renderInstall(p); } catch (e) { return toast(e.message, true); }
  clearInterval(W.poll);
  W.poll = setInterval(async () => {
    try {
      const p = W.progress = await json('/api/setup/progress');
      const open = $('.log')?.open;
      renderInstall(p); if (open) $('.log').open = true;
      if (p.state !== 'running') {
        clearInterval(W.poll);
        if (p.state === 'done') { W.st = await json('/api/setup/status'); W.step = 4; renderSetup(); }
      }
    } catch {}
  }, 1000);
}

/* ---------------- boot ---------------- */
async function boot() {
  syncEditor(); renderVoicePick();
  pollHealth();
  try {
    const st = await json('/api/setup/status');
    if (!st.setup_complete) await openSetup(false);
  } catch (e) { toast(e.message, true); }
  loadVoices().catch(() => {});
}
boot();

/* ================= STAGE: ovozga jonli javob beradigan shar ================= */
const stage = { open: false, ctx: null, an: null, data: null, level: 0, raf: 0, words: [], weights: [], idleT: 0, t0: performance.now() };
function ensureAnalyser() {
  if (stage.an) { stage.ctx.resume(); return; }
  try {
    const C = new (window.AudioContext || window.webkitAudioContext)();
    const src = C.createMediaElementSource(audio);
    const an = C.createAnalyser(); an.fftSize = 1024; an.smoothingTimeConstant = 0.6;
    src.connect(an); an.connect(C.destination);
    stage.ctx = C; stage.an = an; stage.data = new Uint8Array(an.fftSize);
  } catch (e) { console.warn('Analyser', e); }
}
function setStageText(text) {
  const clean = String(text || '').replace(/\[[a-z-]+\]/g, ' ').replace(/\s+/g, ' ').trim();
  stage.words = clean ? clean.split(' ') : [];
  const lens = stage.words.map(w => w.length + 1), tot = lens.reduce((a, b) => a + b, 0) || 1;
  let acc = 0; stage.weights = lens.map(l => (acc += l) / tot);
  $('#stageText').innerHTML = stage.words.map(w => `<span>${esc(w)}</span> `).join('');
}
function openStage() {
  if (!audio.src) return toast('Avval ovoz yarating yoki tarixdan tanlang', true);
  stage.open = true; $('#stage').hidden = false;
  $('#stageVoice').textContent = $('#plT1').textContent;
  setStageText(state.playText);
  ensureAnalyser();
  try { document.documentElement.requestFullscreen?.(); } catch {}
  poke(); cancelAnimationFrame(stage.raf); stage.raf = requestAnimationFrame(stageLoop);
}
function closeStage() {
  stage.open = false; $('#stage').hidden = true; cancelAnimationFrame(stage.raf);
  if (document.fullscreenElement) document.exitFullscreen?.();
}
function poke() {
  $('#stage').classList.remove('idle'); clearTimeout(stage.idleT);
  stage.idleT = setTimeout(() => { if (!audio.paused) $('#stage').classList.add('idle'); }, 2200);
}
function stageLoop(now) {
  let lv = 0;
  if (stage.an && !audio.paused) {
    stage.an.getByteTimeDomainData(stage.data);
    let sum = 0; for (let i = 0; i < stage.data.length; i++) { const v = (stage.data[i] - 128) / 128; sum += v * v; }
    lv = Math.min(1, Math.sqrt(sum / stage.data.length) * 4.2);
  }
  stage.level += (lv - stage.level) * (lv > stage.level ? 0.35 : 0.08); // tez ko'tarilib, sekin tushadi
  const L = stage.level, t = (now - stage.t0) / 1000;
  const breathe = 0.012 * Math.sin(t * 1.4);
  const orb = $('#orb');
  orb.style.setProperty('--s', (1 + breathe + L * 0.14).toFixed(4));
  orb.style.setProperty('--glow', (0.15 + L * 0.85).toFixed(3));
  const sp = 0.35 + L * 2.2;
  stage.phase = (stage.phase || 0) + sp * 0.016;
  const ph = stage.phase, amp = 6 + L * 16;
  const blobs = orb.querySelectorAll('i');
  const cfg = [[1, 0], [0.8, 1.7], [0.6, 3.1], [1.3, 4.4], [0.9, 5.6]];
  blobs.forEach((b, i) => {
    const [f, o] = cfg[i];
    const x = Math.cos(ph * f + o) * amp, y = Math.sin(ph * f * 1.3 + o) * amp * 0.8;
    const sc = 1 + Math.sin(ph * f * 0.7 + o) * 0.08 + L * 0.18 * (i % 2 ? 1 : -0.6);
    b.style.transform = `translate(${x.toFixed(1)}%, ${y.toFixed(1)}%) scale(${sc.toFixed(3)}) rotate(${(ph * 20 * f).toFixed(1)}deg)`;
  });
  // so'zma-so'z yoritish (vaqt bo'yicha taxminiy)
  const p = audio.duration ? audio.currentTime / audio.duration : 0;
  const spans = $('#stageText').children;
  for (let i = 0; i < spans.length; i++) spans[i].classList.toggle('on', audio.ended || stage.weights[i] <= p + 0.02);
  $('#stageTime').textContent = `${fmtTime(audio.currentTime)} / ${fmtTime(audio.duration)}`;
  $('#stagePlay use').setAttribute('href', audio.paused ? '#i-play' : '#i-pause');
  if (stage.open) stage.raf = requestAnimationFrame(stageLoop);
}
$('#plStage').onclick = openStage;
$('#stageClose').onclick = closeStage;
$('#stagePlay').onclick = () => { ensureAnalyser(); if (audio.ended) audio.currentTime = 0; audio.paused ? audio.play() : audio.pause(); };
$('#stage').addEventListener('mousemove', poke);
document.addEventListener('keydown', (e) => {
  if (!stage.open) return;
  if (e.key === 'Escape') closeStage();
  if (e.code === 'Space') { e.preventDefault(); $('#stagePlay').click(); poke(); }
});
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && stage.open) { /* foydalanuvchi F11/Esc bilan chiqdi */ } });
