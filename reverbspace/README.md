# ReverbSpace

A reverb you tune by moving around a room instead of turning knobs.

Pick a space — studio, concert hall, cathedral, theatre — then resize it, hang
soundproofing on the walls, stand somewhere, and put a mic somewhere else. Every
one of those changes runs through a real room-acoustics model and comes back out
as the reverb you hear. The rays on screen are the reflection paths the DSP is
actually rendering, not decoration.

```
npm install          # playwright, for the browser smoke test only
npm start            # serves on http://localhost:8123
npm test             # the acoustics and DSP suites
```

No build step and no runtime dependencies. Open `index.html` from any static
server and it runs.

## What you can move

| Control | What it does to the sound |
|---|---|
| **Space** | Swaps the surface materials — plasterboard, wood, stone, marble, seating |
| **Size** | Scales the room, or drag a wall in the 3D view to stretch one dimension |
| **Soundproofing** | Covers walls and ceiling in foam, rockwool, drapes or diffusers |
| **Where you stand** | Drag the performer; changes which reflections arrive and when |
| **Mic distance** | Drag the mic; the direct sound falls off, the room doesn't |
| **Mic type** | Polar pattern, on-axis tone, off-axis dulling, proximity effect |

The two panels along the bottom are live: what reaches the mic over time (direct
spike, every early reflection at its true arrival, then the tail), and the
reverberation time in each octave band.

## The model

Six octave bands, 125 Hz to 4 kHz, carried all the way through.

**Decay.** Eyring, with the air-absorption term, over the effective absorption
of each surface once seating and treatment are blended in:

```
T60 = 0.161 V / (-S ln(1 - a) + 4mV)
```

**Early reflections.** Image-source method over the shoebox to third order —
every image's exact distance, arrival time, and per-band gain from the specific
walls it bounced off, plus air absorption over the path. Those same paths are
what get drawn.

**The diffuse tail.** Its level comes from the room constant `R = Sa/(1-a)` and
the mic's directivity factor `Q`, so the direct-to-reverberant ratio falls with
distance exactly as `d * sqrt(16pi / (R Q))` says it should — which is why
backing away from the mic buries you in the room, and why a shotgun keeps you
out of it.

**The mic** contributes its polar pattern (as a proper 3D angle, so a reflection
off the ceiling is off-axis too), an on-axis tone curve, high-frequency dulling
that grows off-axis, and a first-order gradient proximity lift that only
directional capsules get.

## The DSP

A 16-line feedback delay network with a Hadamard mixing matrix, line lengths
derived from the room's mean free path, and per-line low and high shelves whose
ratios come straight from the per-band reverberation times. Ahead of it: four
allpass diffusers, a multi-tap early-reflection bank (one tap per image source,
panned per capsule), and the direct tap. Modulated lines, 4-point Lagrange
interpolation on the direct and early taps, and a soft clip on the output.

## Is it actually right?

`npm test` holds the DSP to the numbers the room model produces, measured by
running the engine offline:

- rendered T60 within 15% of the model's, every preset
- the tail sits within 2 dB of the diffuse-field prediction, in one-octave bands
  at 500 / 1k / 2k, across presets and a 3.4x size range
- the direct sound within 1 dB of inverse-square, from 0.5 m to 8 m
- backing away always drops the direct-to-reverberant ratio; tighter patterns
  always raise it; treatment always shortens the tail
- no clicks, non-finite samples or overs while the room is yanked around
  underneath the audio

`node tests/browser-smoke.mjs` (with `npm start` running) covers the half that
only exists in a browser: the page loads clean, the AudioWorklet builds, the
room paints, and dragging the mic across the hall really does move the
direct-to-room ratio.

One number is empirical rather than derived: `FDN_ENERGY` in
`src/dsp/designer.js`, which sets the tail's absolute level. The diffuse-field
argument predicts 0.5 and the network measures 0.416, the gap being
high-frequency loss in the damping filters. It is measured, documented, and
re-checked by the test suite, so it cannot drift silently.

## Porting to a native plugin

The layers are split so the expensive thinking survives a rewrite:

| Directory | Ports? |
|---|---|
| `src/core/` | **1:1.** Pure arithmetic, no browser API. Reads across to C++ nearly line for line. |
| `src/dsp/` | **Design ports whole**, code is a mechanical rewrite. `reverb-engine.js` is plain loops over typed arrays and deliberately uses no Web Audio node — the only file here that gets thrown away is `reverb-worklet.js`, which is 50 lines of glue. |
| `src/ui/`, `src/audio/` | **No.** A JUCE editor is its own build — but this is the tuned, working spec to build it against. |

`tests/` ports too, and is worth porting first: it is what tells you the C++
still matches the model.

## Known limits

- Shoebox rooms only. No balconies, no transepts, no angled walls.
- Third-order image sources; past that the tail takes over, which is the usual
  trade but does mean small, hard rooms are less exact than large ones.
- Diffusers are modelled as scattering that moves energy out of the discrete
  reflections and into the tail, not as a real scattering coefficient per band.
- The performer radiates omnidirectionally. Real instruments and voices do not.
- Absorption coefficients are typical published values, not measurements of any
  particular room.
