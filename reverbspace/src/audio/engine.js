// The Web Audio side: build the graph, feed the worklet, run the transport.
// Everything here is glue; the reverb itself lives in src/dsp.

import { buildTestSources, TEST_SOURCES } from './sources.js';

// An AudioWorklet can only be loaded from a URL. Normally that is the file
// next door; the single-file build hands us a blob URL instead, since there is
// no file to point at.
const WORKLET_URL = globalThis.__REVERBSPACE_WORKLET_URL__
  || new URL('../dsp/reverb-worklet.js', import.meta.url);

export class AudioEngine {
  constructor() {
    this.ctx = null;
    this.node = null;
    this.analyser = null;
    this.testBuffers = null;
    this.current = null;        // the playing AudioBufferSourceNode
    this.userBuffer = null;     // a file the user dropped in
    this.userName = '';
    this.stream = null;         // live input
    this.streamNode = null;
    this.onMeter = () => {};
    this.onState = () => {};
    this.meters = { in: 0, out: 0 };
    this.pendingDesign = null;
    this.pendingControls = null;
    this.status = 'idle';
  }

  get ready() { return !!this.node; }

  /** Must be called from a user gesture, or the context will not start. */
  async start() {
    if (this.node) {
      if (this.ctx.state === 'suspended') await this.ctx.resume();
      return;
    }
    this.status = 'starting';
    this.onState(this);
    this.ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
    await this.ctx.audioWorklet.addModule(WORKLET_URL);

    this.node = new AudioWorkletNode(this.ctx, 'reverbspace', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [2],
    });
    this.node.port.onmessage = (e) => {
      const m = e.data;
      if (m.type === 'meter') {
        this.meters = { in: m.in, out: m.out };
        this.onMeter(this.meters);
      }
    };
    this.node.onprocessorerror = () => {
      this.status = 'error';
      this.onState(this);
    };

    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0.75;

    this.input = this.ctx.createGain();
    this.input.connect(this.node);
    this.node.connect(this.analyser);
    this.analyser.connect(this.ctx.destination);

    this.testBuffers = buildTestSources(this.ctx);
    if (this.pendingDesign) this.sendDesign(this.pendingDesign);
    if (this.pendingControls) this.sendControls(this.pendingControls);

    this.status = 'running';
    this.onState(this);
  }

  sendDesign(design) {
    if (!this.node) { this.pendingDesign = design; return; }
    this.node.port.postMessage({ type: 'design', design });
  }

  sendControls(controls) {
    if (!this.node) { this.pendingControls = { ...this.pendingControls, ...controls }; return; }
    this.node.port.postMessage({ type: 'controls', controls });
  }

  stopSource() {
    if (this.current) {
      try { this.current.stop(); } catch { /* already ended */ }
      this.current.disconnect();
      this.current = null;
    }
  }

  /** Play a test signal, or the user's own file when id is 'file'. */
  play(id, { loop = false } = {}) {
    if (!this.ctx) return false;
    const buffer = id === 'file' ? this.userBuffer : this.testBuffers.get(id);
    if (!buffer) return false;
    this.stopSource();
    this.stopLive();
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.loop = loop;
    src.connect(this.input);
    src.onended = () => { if (this.current === src) { this.current = null; this.onState(this); } };
    src.start();
    this.current = src;
    this.onState(this);
    return true;
  }

  get playing() { return !!this.current || !!this.streamNode; }

  async loadFile(file) {
    if (!this.ctx) await this.start();
    const bytes = await file.arrayBuffer();
    this.userBuffer = await this.ctx.decodeAudioData(bytes);
    this.userName = file.name;
    this.onState(this);
    return this.userBuffer;
  }

  async startLive() {
    if (!this.ctx) await this.start();
    this.stopSource();
    if (this.streamNode) return true;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    this.streamNode = this.ctx.createMediaStreamSource(this.stream);
    this.streamNode.connect(this.input);
    this.onState(this);
    return true;
  }

  stopLive() {
    if (this.streamNode) { this.streamNode.disconnect(); this.streamNode = null; }
    if (this.stream) { for (const t of this.stream.getTracks()) t.stop(); this.stream = null; }
    this.onState(this);
  }

  stopAll() {
    this.stopSource();
    this.stopLive();
  }

  /** Magnitude spectrum for the display, in dB. */
  spectrum(into) {
    if (!this.analyser) return null;
    const n = this.analyser.frequencyBinCount;
    if (!into || into.length !== n) into = new Uint8Array(n);
    this.analyser.getByteFrequencyData(into);
    return into;
  }
}

export { TEST_SOURCES };
