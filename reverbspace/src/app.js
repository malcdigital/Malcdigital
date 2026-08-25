// Wiring. State lives here; every change re-runs the room model, re-designs the
// reverb, ships it to the worklet and redraws.

import {
  makeState, analyze, setScale, setMicDistance, micDistance, clampOccupants, aimMic,
  resetPlacement,
} from './core/acoustics.js';
import { PRESETS, PRESETS_BY_ID } from './core/presets.js';
import { TREATMENTS } from './core/materials.js';
import { STAGES, MAX_STAGE } from './core/treatment.js';
import { NOTE_NAMES, roomNote, roomModes, scaleForNote } from './core/modes.js';
import { mouthHeight } from './core/fittings.js';
import { MICS, MICS_BY_ID } from './core/mics.js';
import { designReverb } from './dsp/designer.js';
import { AudioEngine, TEST_SOURCES } from './audio/engine.js';
import { RoomScene } from './ui/scene3d.js';
import { drawEchogram, drawDecay } from './ui/ir-view.js';

const $ = (id) => document.getElementById(id);
const clampStage = (v) => Math.max(0, Math.min(MAX_STAGE, Math.round(v ?? 0)));
/** Just the note name, for the second and third modes in the readout. */
const noteLabelOf = (f) => `${NOTE_NAMES[((Math.round(69 + 12 * Math.log2(f / 440)) % 12) + 12) % 12]}`;
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

const audio = new AudioEngine();
let state = makeState('studio');
let response = analyze(state);
let scene;
let currentSource = 'clap';
let dirty = true;

// ------------------------------------------------------------------ startup

function boot() {
  scene = new RoomScene($('room'), $('room-hud'));
  scene.onChange = (what) => {
    if (what === 'dims') {
      // A dragged wall breaks the link to the preset's base size.
      const p = PRESETS_BY_ID[state.presetId];
      state.scale = state.dims.w / p.dims.w;
    }
    clampOccupants(state);
    syncInputs();
    dirty = true;
  };
  scene.onModeChange = (mode) => {
    $('view-first').classList.toggle('on', mode === 'first');
    $('view-orbit').classList.toggle('on', mode === 'orbit');
  };

  buildPresets();
  buildSources();
  buildSelects();
  bindControls();
  applyPreset('studio', true);

  bindSheet();
  // The keyboard hints are no use on a phone.
  if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
    $('overlay').innerHTML =
      '<p><strong>Tap to start audio.</strong></p>' +
      '<p>You are standing in the room. <em>Drag</em> to look around, drag the <em>mic</em> ' +
      'to move it, and drag either marker on the plan to walk about. ' +
      'Pull up <em>Controls</em> to change the space.</p>';
  }

  window.addEventListener('resize', () => { resize(); dirty = true; });
  // Rotating a phone, or opening the sheet, changes the stage without ever
  // firing a window resize.
  if (window.ResizeObserver) {
    new ResizeObserver(() => { resize(); dirty = true; }).observe($('room').parentElement);
  }
  resize();

  let last = performance.now();
  let complained = 0;
  const frame = (now) => {
    const dt = Math.min(60, now - last);
    last = now;
    // Anything that throws in here used to take the whole application with it:
    // the rescheduling call sits at the end, so one bad frame meant no more
    // frames, ever, and an interface that had quietly stopped being live
    // without saying so. Keep going, and say what happened the first few times.
    try {
      if (dirty) { recompute(); dirty = false; }
      scene.render(dt);
      updateMeters();
    } catch (err) {
      if (complained++ < 3) console.error('frame failed:', err);
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);

  // A handle for the browser smoke test, and for poking at the model from a
  // console: everything the app knows, live.
  window.reverbspace = {
    get state() { return state; },
    get response() { return response; },
    scene,
    audio,
    /** Where the performer or the mic currently sits on screen. */
    screenOf(which) {
      const p = which === 'mic' ? scene.micPoint : scene.sourcePoint;
      return scene.screenOf(p);
    },
  };

  // Audio can only start inside a gesture.
  const kick = async () => {
    try {
      await audio.start();
      $('overlay').classList.add('gone');
      audio.sendDesign(designReverb(response, audio.ctx.sampleRate));
      pushControls();
    } catch (err) {
      // Opened straight off the disk, the page has an opaque origin and the
      // browser refuses to load the worklet. Everything visual still works.
      const local = location.protocol === 'file:';
      $('overlay').classList.remove('gone');
      $('overlay').innerHTML = local
        ? `<p><strong>The room works, but audio cannot start from a file:// page.</strong></p>
           <p>Browsers refuse to load audio worklets off the local disk. Serve the folder
              instead &mdash; <code>python3 -m http.server 8123</code> &mdash; and open it
              over http.</p>`
        : `<p><strong>Audio failed to start.</strong></p><p>${err.message}</p>`;
    }
  };
  document.body.addEventListener('pointerdown', kick, { once: true });
}

function resize() {
  scene.resize();
  updateReserved();
  drawViews();
}

/**
 * How much of the room the controls sheet is hiding. The scene lifts its
 * vanishing point by half of it, so what you are looking at stays in the part
 * of the screen you can still see.
 */
function updateReserved() {
  const sheet = $('sheet');
  if (!sheet || getComputedStyle(sheet).position !== 'fixed') {
    scene.reserved = 0;
    return;
  }
  const stage = $('room').getBoundingClientRect();
  const box = sheet.getBoundingClientRect();
  // Use what the sheet actually covers: clamping it short leaves the mic
  // behind the sheet, which is the whole problem this is meant to solve.
  scene.reserved = Math.max(0, Math.min(stage.bottom - box.top, stage.height * 0.82));
}

function bindSheet() {
  const sheet = $('sheet');
  const handle = $('sheet-handle');
  if (!handle) return;
  const settle = () => { resize(); dirty = true; };
  // The slide is what decides how much of the room is covered, so wait for it
  // to finish. A frame-counted loop is not enough: on a slow device too few
  // frames land inside the transition and the view keeps the closed offset.
  sheet.addEventListener('transitionend', (e) => {
    if (e.propertyName === 'transform') settle();
  });
  handle.addEventListener('click', () => {
    const open = sheet.classList.toggle('open');
    handle.setAttribute('aria-expanded', String(open));
    $('sheet-label').textContent = open ? 'Hide controls' : 'Controls & analysis';
    settle();
    // Follow the slide so the view keeps pace, and settle once more after it
    // should have ended, in case the transition event never arrives.
    const t0 = performance.now();
    const step = () => {
      settle();
      if (performance.now() - t0 < 420) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    setTimeout(settle, 460);
  });
}

// -------------------------------------------------------------- the pipeline

function recompute() {
  clampOccupants(state);
  response = analyze(state);
  scene.setState(state, response);
  if (audio.ready) audio.sendDesign(designReverb(response, audio.ctx.sampleRate));
  drawViews();
  drawStats();
  drawRoomNote();
}

/**
 * What the room rings at. Small rooms have a note you can hear; big ones have
 * modes too low and too close together to be one, and say so.
 *
 * Belongs here and not in syncInputs: that runs before the room is reanalysed,
 * so it would be reading the previous room's decay to describe this one -- and
 * a cathedral measured against a studio's Schroeder frequency confidently
 * reported a B flat.
 */
function drawRoomNote() {
  const note = roomNote(state, response.decay);
  const modes = roomModes(state, response.decay, 3);
  $('mode-note').textContent = note
    ? `Rings at ${note.f.toFixed(1)} Hz — ${note.label}`
      + (modes.length > 1 ? `, then ${modes.slice(1).map((m) => noteLabelOf(m.f)).join(' and ')}` : '')
    : 'Too big to ring at a note — its modes are below hearing and packed too close to hear apart.';
  $('tune').disabled = !note;
}

function drawViews() {
  if (!response) return;
  const accent = PRESETS_BY_ID[state.presetId].palette;
  drawEchogram($('echogram'), response, accent);
  drawDecay($('decay'), response, accent);
}

function drawStats() {
  const d = response.decay;
  const rows = [
    ['reverb time (mid)', `${d.midRt.toFixed(2)} s`],
    ['volume', `${Math.round(d.volume).toLocaleString()} m³`],
    ['mic distance', `${micDistance(state).toFixed(2)} m`],
    ['critical distance', `${response.criticalDistance.toFixed(2)} m`],
    ['direct vs room', `${response.balance.drrDb >= 0 ? '+' : ''}${response.balance.drrDb.toFixed(1)} dB`],
    ['1st reflection', `${(response.firstReflectionGap * 1000).toFixed(1)} ms`],
    ['reflections traced', `${response.early.length}`],
    ['absorption (mid)', `${(d.alphaBar[3] * 100).toFixed(0)} %`],
  ];
  $('stats').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');

  // Past the critical distance you are hearing the room more than the performer.
  const past = micDistance(state) > response.criticalDistance;
  $('stats').insertAdjacentHTML('beforeend',
    `<dt style="grid-column:1/-1;color:${past ? '#e0a04f' : '#6d7488'};padding-top:6px">${
      past ? 'Past the critical distance — the room is louder than the performer.'
           : 'Inside the critical distance — the performer still dominates.'}</dt>`);
}

// ---------------------------------------------------------------- UI builders

function buildPresets() {
  $('presets').innerHTML = PRESETS.map(
    (p) => `<button class="btn preset" data-id="${p.id}">${p.name}</button>`).join('');
  for (const b of $('presets').querySelectorAll('.preset')) {
    b.addEventListener('click', () => applyPreset(b.dataset.id));
  }
}

function buildSources() {
  $('sources').innerHTML = TEST_SOURCES.map(
    (s) => `<button class="btn src" data-id="${s.id}" title="${s.blurb}">${s.name}</button>`).join('');
  for (const b of $('sources').querySelectorAll('.src')) {
    b.addEventListener('click', () => {
      currentSource = b.dataset.id;
      markSource();
      play();
    });
  }
  markSource();
}

function markSource() {
  for (const b of $('sources').querySelectorAll('.src')) {
    b.classList.toggle('on', b.dataset.id === currentSource);
  }
}

function buildSelects() {
  $('treat-type').innerHTML = Object.entries(TREATMENTS)
    .map(([id, t]) => `<option value="${id}">${t.name}</option>`).join('');
  $('mic-type').innerHTML = MICS.map((m) => `<option value="${m.id}">${m.name}</option>`).join('');
  $('key').innerHTML = NOTE_NAMES.map((n, i) => `<option value="${i}">${n}</option>`).join('');
  $('key').value = '9';        // A, for want of anywhere better to start
}

function applyPreset(id, quiet = false) {
  const keepMic = state ? state.mic.id : null;
  state = makeState(id);
  if (keepMic && !quiet) state.mic.id = keepMic;
  aimMic(state);
  scene.framed = false;
  const p = PRESETS_BY_ID[id];
  document.documentElement.style.setProperty('--accent', p.palette);
  $('preset-blurb').textContent = p.blurb;
  for (const b of $('presets').querySelectorAll('.preset')) {
    b.classList.toggle('on', b.dataset.id === id);
  }
  const [lo, hi] = p.sizeRange;
  $('scale').min = lo;
  $('scale').max = hi;
  syncInputs();
  dirty = true;
}

// ---------------------------------------------------------------- inputs

/** Push state into the widgets, after a drag or a preset change. */
function syncInputs() {
  const p = PRESETS_BY_ID[state.presetId];
  $('scale').value = clamp(state.scale, p.sizeRange[0], p.sizeRange[1]);
  $('scale-out').textContent = `${Math.round(state.scale * 100)}%`;
  $('height').max = Math.max(6, p.dims.h * p.sizeRange[1]);
  $('height').value = state.dims.h;
  $('height-out').textContent = `${state.dims.h.toFixed(1)} m`;

  // The step number goes in the value slot with every other row's number; the
  // name is a name and needs a line of its own, not a column sized for "35%".
  const step = clampStage(state.treatment.stage);
  $('treat').value = step;
  $('treat-out').textContent = `${step} / ${MAX_STAGE}`;
  $('treat-name').textContent = STAGES[step].name;
  $('treat-note').textContent = STAGES[step].blurb;
  $('treat-type').value = state.treatment.type;
  $('treat-blurb').textContent = TREATMENTS[state.treatment.type].blurb;

  $('src-h').max = Math.max(2, state.dims.h - 0.2);
  $('src-h').value = state.source.height;
  $('src-h-out').textContent = `${state.source.height.toFixed(2)} m`;
  // Say where the sound actually leaves from, since it is not the number on
  // the control and it is what every distance in here is measured from.
  $('mouth-note').textContent =
    `Their mouth is at ${mouthHeight(state.source.height).toFixed(2)} m. `
    + 'That is where the sound leaves from, and where the mic starts.';

  $('mic-type').value = state.mic.id;
  $('mic-blurb').textContent = MICS_BY_ID[state.mic.id].blurb;
  const dist = micDistance(state);
  $('mic-d').max = Math.max(2, Math.hypot(state.dims.w, state.dims.d));
  $('mic-d').value = dist;
  $('mic-d-out').textContent = `${dist.toFixed(2)} m`;
  $('mic-h').max = Math.max(2, state.dims.h - 0.2);
  $('mic-h').value = state.mic.height;
  $('mic-h-out').textContent = `${state.mic.height.toFixed(2)} m`;
  const deg = Math.round((state.mic.azimuth * 180) / Math.PI);
  $('mic-az').value = deg;
  $('mic-az-out').textContent = `${deg}°`;
  $('mic-aim').checked = state.mic.aimAtSource;
  $('mic-az').disabled = state.mic.aimAtSource;
}

function bindControls() {
  const on = (id, ev, fn) => $(id).addEventListener(ev, fn);

  on('scale', 'input', (e) => { setScale(state, +e.target.value); scene.framed = false; syncInputs(); dirty = true; });
  on('height', 'input', (e) => {
    state.dims.h = +e.target.value;
    clampOccupants(state);
    syncInputs();
    dirty = true;
  });

  on('treat', 'input', (e) => { state.treatment.stage = +e.target.value; syncInputs(); dirty = true; });
  // Tune the room to the key. Mode frequencies go as one over length and the
  // size control scales every dimension together, so this is just a size
  // change -- which is exactly why the size already moves the pitch.
  on('tune', 'click', () => {
    const p = PRESETS_BY_ID[state.presetId];
    const hit = scaleForNote(state, response.decay, +$('key').value, p.sizeRange);
    if (!hit) return;
    setScale(state, hit.scale);
    scene.framed = false;
    syncInputs();
    dirty = true;
  });

  on('reset-places', 'click', () => {
    resetPlacement(state);
    scene.lookAtMic();
    syncInputs();
    dirty = true;
  });
  on('treat-type', 'change', (e) => { state.treatment.type = e.target.value; syncInputs(); dirty = true; });

  on('src-h', 'input', (e) => { state.source.height = +e.target.value; clampOccupants(state); syncInputs(); dirty = true; });

  on('mic-type', 'change', (e) => { state.mic.id = e.target.value; syncInputs(); dirty = true; });
  on('mic-d', 'input', (e) => { setMicDistance(state, +e.target.value); syncInputs(); dirty = true; });
  on('mic-h', 'input', (e) => { state.mic.height = +e.target.value; clampOccupants(state); syncInputs(); dirty = true; });
  on('mic-az', 'input', (e) => { state.mic.azimuth = (+e.target.value * Math.PI) / 180; syncInputs(); dirty = true; });
  on('mic-aim', 'change', (e) => { state.mic.aimAtSource = e.target.checked; aimMic(state); syncInputs(); dirty = true; });

  on('mix', 'input', (e) => { $('mix-out').textContent = `${Math.round(e.target.value * 100)}%`; pushControls(); });
  on('output', 'input', (e) => {
    const v = +e.target.value;
    $('output-out').textContent = v <= 0.001 ? '-inf' : `${(20 * Math.log10(v)).toFixed(1)} dB`;
    pushControls();
  });
  on('room-only', 'change', pushControls);
  on('rays', 'change', (e) => { scene.showRays = e.target.checked; });
  on('view-first', 'click', () => scene.setMode('first'));
  on('view-orbit', 'click', () => scene.setMode('orbit'));

  on('bypass', 'click', () => {
    $('bypass').classList.toggle('on');
    pushControls();
  });

  on('play', 'click', play);
  // Stop means everything quiet, live input included. A stop button that
  // leaves sound coming through is a stop button that does not work.
  on('stop', 'click', () => {
    audio.stopAll();
    $('live').classList.remove('on');
    syncTransport();
  });
  on('loop', 'change', () => { if (audio.playing) play(); });
  on('live', 'click', async () => {
    await audio.start();
    if (audio.streamNode) { audio.stopLive(); $('live').classList.remove('on'); return; }
    try {
      await audio.startLive();
      $('live').classList.add('on');
      $('overlay').classList.add('gone');
    } catch (err) {
      $('live').classList.remove('on');
      alert(`Could not open the microphone: ${err.message}`);
    }
  });
  on('file', 'change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    await audio.start();
    try {
      await audio.loadFile(f);
      currentSource = 'file';
      markSource();
      $('overlay').classList.add('gone');
      play();
    } catch (err) {
      alert(`Could not decode ${f.name}: ${err.message}`);
    }
  });
}

function pushControls() {
  audio.sendControls({
    mix: +$('mix').value,
    output: +$('output').value,
    roomOnly: $('room-only').checked,
    bypass: $('bypass').classList.contains('on'),
  });
}

async function play() {
  await audio.start();
  $('overlay').classList.add('gone');
  audio.sendDesign(designReverb(response, audio.ctx.sampleRate));
  pushControls();
  const src = TEST_SOURCES.find((s) => s.id === currentSource);
  const loop = $('loop').checked || (src ? src.loops && $('loop').checked : false);
  if (audio.play(currentSource, { loop })) scene.ping();
}

/** Play and Stop reflect what is actually making a noise. */
function syncTransport() {
  const on = audio.playing;
  $('stop').disabled = !on;
  $('play').classList.toggle('on', on);
}

function updateMeters() {
  syncTransport();
  const m = audio.meters;
  $('meter-in').style.width = `${clamp(m.in * 100, 0, 100)}%`;
  $('meter-out').style.width = `${clamp(m.out * 100, 0, 100)}%`;
}

boot();
