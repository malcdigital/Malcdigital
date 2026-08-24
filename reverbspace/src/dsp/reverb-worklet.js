// Thin AudioWorklet wrapper. All the actual work is in ReverbEngine, which
// knows nothing about Web Audio -- this file is the only part of the DSP layer
// that would be thrown away when porting to a native plugin.

import { ReverbEngine } from './reverb-engine.js';

const METER_INTERVAL = 6;   // blocks between meter posts

class ReverbSpaceProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.engine = new ReverbEngine(sampleRate);
    this.blocks = 0;
    this.silent = 0;
    this.port.onmessage = (e) => {
      const m = e.data;
      if (m.type === 'design') this.engine.setDesign(m.design);
      else if (m.type === 'controls') this.engine.setControls(m.controls);
    };
    this.port.postMessage({ type: 'ready', sampleRate });
  }

  process(inputs, outputs) {
    const input = inputs[0];
    const output = outputs[0];
    if (!output || output.length === 0) return true;

    const n = output[0].length;
    const outL = output[0];
    const outR = output.length > 1 ? output[1] : output[0];

    // A disconnected or mono input still has to drive the room.
    let inL = input && input[0] ? input[0] : null;
    let inR = input && input[1] ? input[1] : inL;
    if (!inL) {
      if (!this.zeros || this.zeros.length !== n) this.zeros = new Float32Array(n);
      inL = this.zeros;
      inR = this.zeros;
    }

    this.engine.process(inL, inR, outL, outR, n);

    if (++this.blocks >= METER_INTERVAL) {
      this.blocks = 0;
      let inPeak = 0;
      for (let i = 0; i < n; i++) {
        const v = Math.abs(inL[i]);
        if (v > inPeak) inPeak = v;
      }
      this.port.postMessage({ type: 'meter', out: this.engine.peak, in: inPeak });
    }
    return true;
  }
}

registerProcessor('reverbspace', ReverbSpaceProcessor);
