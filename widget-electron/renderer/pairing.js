'use strict';
// The Phones window: pair a phone with a QR, accept/reject its request
// (comparing the fingerprint the phone shows), revoke a paired friend.
// Everything goes through main.js → lib/pairing.js → vortexia §10.

const $ = (id) => document.getElementById(id);
const els = {
  pendingList: $('pendingList'), pairIdle: $('pairIdle'), pairActive: $('pairActive'),
  pairLabel: $('pairLabel'), pairStart: $('pairStart'), pairCancel: $('pairCancel'), pairCopy: $('pairCopy'),
  qr: $('qr'), countdown: $('pairCountdown'), status: $('pairStatus'), friends: $('friendList'),
};
let state = { connected: false, friends: [], pending: [], session: null };
let session = null;          // {sessionId, uri, expiresAt, svg?}
let countdownTimer = null;

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}

function setStatus(text, error = false) {
  els.status.textContent = text || '';
  els.status.classList.toggle('error', !!error);
}

function ago(ms) {
  if (!ms) return '';
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 90) return 'just now';
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function renderFriends() {
  els.friends.replaceChildren();
  if (!state.friends.length) {
    els.friends.append(el('div', { className: 'empty', textContent: 'Nothing paired yet.' }));
    return;
  }
  for (const f of state.friends) {
    const revoke = el('button', { type: 'button', className: 'danger', textContent: 'Revoke', title: `Stop trusting ${f.envName}` });
    // Two clicks: the first arms, the second revokes (no modal dialogs).
    let armed = null;
    revoke.addEventListener('click', async () => {
      if (!armed) {
        revoke.classList.add('armed');
        revoke.textContent = 'Sure?';
        armed = setTimeout(() => { armed = null; revoke.classList.remove('armed'); revoke.textContent = 'Revoke'; }, 4000);
        return;
      }
      clearTimeout(armed);
      revoke.disabled = true;
      const res = await window.pairing.revoke(f.envName);
      if (!res.ok) { revoke.disabled = false; setStatus(`Could not revoke ${f.label}: ${res.error}`, true); }
      else setStatus(`${f.label} revoked.`);
    });
    const kind = f.role === 'device' ? 'Phone' : 'Mac';
    const seen = f.lastSeen ? ` · seen ${ago(f.lastSeen)}` : '';
    els.friends.append(el('div', { className: 'row' },
      el('div', { className: 'grow' },
        el('div', { className: 'name', textContent: f.label }),
        el('div', { className: 'sub', textContent: `${kind} · ${f.envName}${seen}` })),
      revoke));
  }
}

function renderPending() {
  const pending = state.pending || [];
  els.pendingList.replaceChildren();
  els.pendingList.classList.toggle('hidden', !pending.length);
  for (const p of pending) {
    const accept = el('button', { type: 'button', className: 'ok', textContent: 'Accept' });
    const reject = el('button', { type: 'button', textContent: 'Reject' });
    const decide = async (yes) => {
      accept.disabled = reject.disabled = true;
      const res = await window.pairing.decide(p.sessionId, yes);
      if (!res.ok) { accept.disabled = reject.disabled = false; setStatus(`Could not answer: ${res.error}`, true); }
    };
    accept.addEventListener('click', () => decide(true));
    reject.addEventListener('click', () => decide(false));
    els.pendingList.append(el('div', { className: 'center' },
      el('div', { className: 'name', textContent: `Accept ${p.label || p.envName}?` }),
      el('div', { className: 'sub', textContent: `${p.role === 'env' ? 'Mac' : 'Phone'} · ${p.envName}` }),
      el('div', { className: 'fp', textContent: p.fingerprint || '' }),
      el('div', { className: 'sub', textContent: 'Accept only if the phone shows this same code.' }),
      el('div', { className: 'row', style: 'justify-content:center' }, accept, reject)));
  }
  renderPair();
}

function renderPair() {
  const pendingUp = (state.pending || []).length > 0;
  els.pairIdle.classList.toggle('hidden', pendingUp || !!session);
  els.pairActive.classList.toggle('hidden', pendingUp || !session);
  els.pairStart.disabled = !state.connected;
  if (!state.connected) setStatus('Not connected to vortexia — retrying…', true);
}

function stopCountdown() {
  clearInterval(countdownTimer);
  countdownTimer = null;
}

function showSession(s) {
  session = s;
  stopCountdown();
  if (!s) { els.qr.replaceChildren(); renderPair(); return; }
  // The SVG comes from the qrcode library in main, never from the network.
  if (s.svg) els.qr.innerHTML = s.svg;
  const tick = () => {
    const left = Math.max(0, Math.round((s.expiresAt - Date.now()) / 1000));
    els.countdown.textContent = `Valid for ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
    if (!left) { showSession(null); setStatus('The QR expired. Show a new one to try again.'); }
  };
  tick();
  countdownTimer = setInterval(tick, 1000);
  renderPair();
}

els.pairStart.addEventListener('click', async () => {
  els.pairStart.disabled = true;
  setStatus('Asking vortexia for a pairing code…');
  const res = await window.pairing.start(els.pairLabel.value);
  els.pairStart.disabled = false;
  if (!res.ok) return setStatus(`Could not start pairing: ${res.error}`, true);
  setStatus('');
  showSession(res);
});

els.pairCopy.addEventListener('click', async () => {
  const res = await window.pairing.copy();
  setStatus(res.ok ? 'Link copied — paste it in the LAS app on the phone.' : `Could not copy: ${res.error}`, !res.ok);
});

els.pairCancel.addEventListener('click', async () => {
  showSession(null);
  await window.pairing.cancel();
  setStatus('Cancelled.');
});

window.pairing.onState((s) => {
  state = { ...state, ...s };
  if (state.connected && els.status.classList.contains('error') && /vortexia/.test(els.status.textContent)) setStatus('');
  renderFriends();
  renderPending();
});

window.pairing.onEvent((event) => {
  const who = event.envName || 'the phone';
  const text = { paired: `Paired with ${who}.`, rejected: `Rejected ${who}.`, expired: 'The request expired.', cancelled: 'Cancelled.' }[event.type];
  if (session && event.sessionId === session.sessionId) showSession(null);
  if (text) setStatus(text, event.type === 'expired');
});

window.pairing.state().then((s) => {
  state = { ...state, ...s };
  renderFriends();
  renderPending();
  // A QR shown before the window was reopened keeps its session, but its
  // picture is not kept: start over rather than show a blank square.
  if (s.session) window.pairing.cancel();
});
