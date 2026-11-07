# Coaster Lab

A 3D roller coaster design game built with Godot 4. You build a track, ride it in first person, see how riders react and how it scores, then tweak it.

**Phase 1** is the full design → ride → score → tweak loop. **Phase 2** adds challenge contracts, five coaster types, terrain sculpting, tunnels, near misses, scenery and lake splashdowns.

## Run it

1. Install **Godot 4.3 or newer** (standard build, not .NET) from godotengine.org.
2. Open Godot, choose **Import**, and select `coaster/project.godot`.
3. Press **F5** (Play). You start with nothing but the station. Build from its end and bring the track back to the start of the station (within 15 m) to close the circuit; until then it is "unfinished" and cannot be ridden. File → New: starter coaster loads a complete example.

Run the tests without opening the editor:

```sh
godot --headless --path coaster --import            # first time only: builds the class cache
godot --headless --path coaster -s res://tests/run_tests.gd   # 44 unit tests
godot --headless --path coaster -s res://tests/smoke_ui.gd    # end-to-end: editing, ride, results, types, sculpting, scenery, contracts, save/load
```

CI runs both on every push that touches `coaster/` (`.github/workflows/coaster.yml`).

## Controls

| Action | Mouse / keyboard | Touch |
|---|---|---|
| Orbit camera | Left-drag empty space | One-finger drag |
| Pan | Right/middle-drag, WASD/arrows | Two-finger drag |
| Zoom | Wheel | Pinch |
| Select point | Click a handle | Tap a handle |
| Move point across ground | Drag a handle | Drag a handle |
| Move point up/down | Shift + drag, PgUp/PgDn | **Height mode** toggle, then drag; or **Up/Down 1 m** buttons |
| Add point after selected | N / Insert | **+ Point** (the **Spacing** slider sets how far from the end it goes) |
| Select several points | Ctrl/Cmd + click | **Multi** toggle, then tap points (tap again to remove); **All** selects everything |
| Move a group | Drag any selected point | Drag any selected point |
| Shape the curve | Drag the cyan handles of the selected point (Alt + drag moves one handle only) | Drag the cyan handles |
| Handle style | Point panel → Curve: Auto / Smooth / Corner | same |
| Delete point | Delete / Backspace | **Delete** |
| Undo / redo | Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) | **Undo** / **Redo** |
| Test ride | Space / Enter | **Test ride** |
| Ride camera POV ↔ chase | C | **Camera** button |
| Ride speed 1×/2×/4× | Tab | **Speed** button |
| Look around (POV) | Drag | Drag |
| Stop ride | Esc / Space | **Stop** |

**Curve handles** work like Bezier handles in a drawing app or a video editor's curves. Every segment between two points is a cubic Bezier. **Auto** points get smooth handles automatically, the same shape as before. Drag a handle and the point becomes **Smooth**: the opposite handle mirrors its direction so the track stays smooth. **Corner** lets each handle move freely. Turns and helixes are now built as a few points with handles (one per quarter turn), so you can reshape a turn by dragging its handles.

Big handles are control points you place. Small dots are the inner points of generated elements; you can drag them too. Handle colour shows the segment type: white is normal, blue is chain lift, pink is launch, orange is brakes, green is station.

## What to test

1. **Ride the starter coaster.** Press Test ride. Watch the chain lift, the drop, airtime on the hill, the banked turn and the loop. Switch to the chase cam and watch riders raise their hands on the airtime hill. Check the results screen. It should rate Thrill about 7.6, Intensity 3.2 and Nausea 2.4, and show two yellow airtime spots. Tap **Show** on one to jump there.
2. **Make it stall.** Tap the small dot at the top of the first airtime hill (about 24 m). Turn on Height mode and drag it up to about 38 m, taller than the 35 m lift. The stats panel should change to **STALLS at … m**. Ride it and the train rolls back from the hill and rocks to a stop. Undo to fix it.
3. **Hurt the riders.** Raise the lift's top points (blue/white handles around 32–35 m) to about 50 m. The extra speed pushes the valleys and loop past 7 g. Those parts turn red, the graph spikes, and red markers appear over the track. Also try dragging a point at the bottom of a drop to make a tight kink.
4. **Banking.** Select a point in the big turn and switch off Auto-bank. The bank slider takes over. Set it to 0° and watch lateral G turn red, then switch Auto-bank back on.
5. **Elements.** Select a point on the return straight and use Add element → Airtime hill (or Loop, Helix…). Each element is sized from the train's speed at that point. Undo if it collides with other track.
6. **Overlays.** Switch the top dropdown between Comfort zones, Speed, Vertical G and Lateral G.
7. **Save/load.** Use File → Save…, then File → New: blank oval, then File → Load…
8. **On a phone or tablet:** export (see below) and try everything with touch, especially pinch and the Height mode toggle.

## Phase 2: what's new and how to test it

**Contracts.** Tap **Contracts** in the top bar. There are eight briefs, and each sets a site, a coaster type, a budget and goals. Meeting every required goal earns 1 star, and each bonus goal adds another (up to 3). The stats panel shows each goal live as YES/NO while you build. Tap the panel to fold it to two lines on a phone. Finishing a contract opens the next one, and some contracts unlock coaster types:

| Contract | Coaster | Site | The twist |
|---|---|---|---|
| First Steps | Steel | Flat | Thrill ≥ 4, nausea ≤ 5 |
| Family Woodie | Wooden | Hills | ≤ 30 m, gentle; **unlocks Launched** |
| Lakeside Splash | Steel | Lake | At least one splashdown |
| Zero to Ninety | Launched | Flat | No chain lift; at least 90 km/h |
| Into the Hill | Steel | Hills | 60 m of tunnel, near misses, keep the path clear; **unlocks Wing** |
| Height Restriction | Steel | Flat | 25 m cap, thrill ≥ 6 |
| Wings Over Water | Wing | Lake | 2 inversions, 4 near misses; **unlocks Flying** |
| Canyon Flyer | Flying | Canyon | Thrill ≥ 6.5 with lower G limits |

**Coaster types** (top bar dropdown in the sandbox):
- **Steel** is the all-rounder.
- **Wooden** has more friction and a rattle that adds intensity and nausea, cheaper track, lattice supports, and can't go upside down.
- **Launched** has linear-motor launches. Set the speed in the point panel on a Launch segment.
- **Wing** puts the seats 1.6 m out on each side. Rolls swing those riders around (the game calculates the extra force at each seat), near misses feel closer, and loops are built wider so legs clear the track.
- **Flying** riders lie face-down under the rails. Their G limits are 18% lower, and the supports are C-shaped columns.

**Terrain** (bottom bar → Terrain): Raise, Lower, Flatten and Smooth brushes with a size slider. Drag on the ground to sculpt. On touch, two fingers move the camera; on desktop, Alt + drag orbits. Track that passes through the ground automatically becomes a cutting (a dug trench) or, when there is enough earth overhead, a tunnel with its own walls. Earthworks and tunnels cost money. File → Terrain switches the sandbox site.

**Scenery** (bottom bar → Scenery): tap to place a tree, rock or tower, and tap it again to remove it. Riders' heads passing within 2.5 m of scenery, other track, supports or terrain at speed count as a **near miss**, which adds thrill. Closer than 0.3 m is a **collision** and shows as a red problem spot. Diving into a tunnel also counts as a near miss.

**Water**: on the Lakeside site, use Add element → **Splashdown**. It dips the train so only the bottom of the car enters the water. Water drag slows the train, spray flies, and riders scream. Going deeper than about 2 m is a red "train under water" problem.

**New elements**: Splashdown and **Heartline roll** (a 360° roll around the riders' chests; great on a wing coaster).

Things to try:
1. Play **First Steps**. The starter loop isn't thrilling enough, so add a lift hill, a drop and an airtime hill until Thrill reaches 4, then ride it to collect your stars.
2. In the sandbox, switch the starter coaster to **Wooden** and watch the loop turn into a red "can't go upside down" spot.
3. Raise a hill over the return straight with the Terrain tool and watch the tunnel and its cost appear.
4. Plant trees 3–4 m from the track and watch Near misses (and Thrill) go up. Plant one on the track to see a collision.
5. Switch to Lakeside terrain and add a Splashdown at the bottom of a drop that crosses the lake.

## Project layout

```
coaster/
  main.gd / main.tscn      top-level controller: edit / ride / results modes,
                           background analysis on a worker thread
  core/                    pure logic, no rendering (all unit-tested)
    track_point.gd         one control point (position, bank, segment type)
    track_data.gd          the whole coaster + train/ride-system settings (saved as JSON)
    spline/track_spline.gd arc-length baked Catmull-Rom, frames, banking, G-force lookup
    physics/train_sim.gd   the train simulation (fixed step, no per-frame allocation)
    physics/ride_record.gd time series captured during a ride
    scoring/               G-force comfort zones, Thrill/Intensity/Nausea, problem spots
    profile_builder.gd     designs hills/drops/loops from target G-forces
    elements.gd            element generators (hill, drop, loop, helix, turns, rolls, splashdown, lift, launch, brakes)
    coaster_types.gd       steel / wooden / launched / wing / flying: physics, limits, cost, look
    terrain_data.gd        heightfield, presets, sculpt brushes, lake, compact saving
    site_analysis.gd       tunnels/cuttings, water depth, supports, near misses, collisions, zones
    props.gd               scenery kinds and their collision shapes
    cost_model.gd          what the coaster costs
    contracts.gd           the eight contracts and their goals
    contract_evaluator.gd  checks goals and awards stars
    analysis_job.gd        the after-edit pipeline, runnable in time slices
    track_analyzer.gd      bake → simulate → auto-bank → simulate → score
    history.gd             undo/redo snapshots
    track_tools.gd         smoothing, insert/remove points
    default_tracks.gd      starter coaster and blank oval
  render/                  track mesh (2 LODs, chunked), supports, station, train,
                           riders, terrain shader, sky
  editor/                  orbit camera (mouse + touch) and control-point editing
  ride/                    ride camera (POV/chase) and procedurally generated sounds
  ui/                      HUD, speed/G graph, results, save/load dialogs
  io/                      save/load to user://coasters/*.json, contract progress
  tests/                   headless test runner, unit tests, smoke test,
                           screenshot + tuning scripts (debug_*.gd)
```

## How the physics works (short version)

All the maths is commented in the code. The key ideas:

- **Track.** Control points are joined with centripetal Catmull-Rom curves and resampled every 0.5 m. Each sample stores position, tangent T, curvature K (which points at the centre of the turn, with |K| = 1/radius), an up/right frame and the roll. The frame is carried along the track, so loops really do go upside down, and it gently returns to level on flat track.
- **Train.** The train is a rigid chain of cars with one speed `v` along the rails. Each step:
  `dv/dt = −g·T.y (averaged over cars) + launch − brakes − μ·|N| − k·v²`,
  where `|N| = |v²K + gY|` with the along-track part removed is the force pressing the wheels on the rails. With no friction this conserves ½v² + gy exactly; a test checks that. The step runs at a fixed 120 Hz with semi-implicit Euler. Chain lifts hold a minimum speed with anti-rollback, and stations and brake runs have drive tyres. If the train runs out of energy it rolls back. If it makes no progress for 12 s it counts as stalled.
- **G-forces.** The specific force is `f = v²K + a_t·T + gY`. Vertical G is `f·up/g` and lateral G is `f·right/g`.
- **Auto-bank.** Each turn is rolled to the angle that makes lateral G zero, `tanθ = f_right/f_up`, using the speed from a first simulation pass. Banking doesn't change speed, so that pass is exact.
- **Elements are designed from forces.** Loops, hills and drops are shaped by integrating `κ = g·(n − cosθ)/v²` for a target felt G `n`. That's why loops come out as teardrops (about 3.3 g at the bottom, 0.9 g at the top), and why turns and helixes use clothoid transitions so there are no sideways jolts.

## Performance notes (target: 60 fps on mid-range phones)

- One train sim step takes about 8 µs on desktop and allocates nothing. Arrays are pre-sized, lookups read packed arrays, and Vector3 is a value type.
- After an edit, analysis runs on a `WorkerThreadPool` thread. That includes two simulated laps and building the mesh arrays, about 0.2 s on desktop. The main thread only uploads the meshes (about 5 ms). On a phone, expect the colours to update a few times a second while you drag.
- The track is split into 40 m chunks with two levels of detail. The detailed rails and ties switch to a 3-sided, sparse-tie version beyond 110 m. Supports are a single MultiMesh, and riders share meshes and materials.
- The project uses the Mobile renderer. If very old Android devices struggle, switch to Compatibility in Project Settings → Rendering.

## Exporting

In the Godot editor: **Editor → Manage Export Templates → Download**, then **Project → Export… → Add…**

- **Web:** the repo includes a `Web` preset (single-threaded, so it needs no special server headers). Run `godot --headless --path coaster --export-release Web build/web/index.html` and serve `build/web/` over HTTP. The web build uses the Compatibility renderer, and background analysis runs on the main thread, so edits can stutter briefly.
- **Windows / macOS:** add the preset and export. macOS builds need signing and notarisation for distribution.
- **Android:** set the Android SDK path in Editor Settings and create a debug keystore. Then use the Android preset with "Use Gradle Build" off and press **Remote Debug** to run on a USB-connected phone.
- **iOS:** export the Xcode project from a Mac, open it in Xcode, set your team, and run.

The screen is locked to landscape (sensor-landscape) on phones. The UI is laid out at 1280×720 and scales up.

## Known limitations

- Tracks are always closed circuits. Point 0 should be the station, because the train starts there.
- Elements are inserted at the selected point, and you may need to reshape the track after them so it still joins up.
- Supports only go under upright track, so loops have no supports. A support that would pass through other track is left out.
- Riders' heads are checked for collisions; car bodies are approximated as a 1 m envelope around the heartline.
- Sounds are synthesised placeholders.
- Scoring formulas are hand-tuned game numbers, not real ride-engineering standards. The constants live at the top of `core/scoring/ride_scorer.gd` and `core/scoring/g_limits.gd`.
