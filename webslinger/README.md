# WebSlinger

A first-person web-swinging traversal prototype for Unreal Engine 5. You fire a
line at a building, the line goes taut, and you swing on it — as a real rope
constraint, not a spring or a scripted animation.

It is all C++ and text config. There are no `.uasset` files, so the whole thing
lives in git and builds from a clone. The test city is generated at runtime, so
there is somewhere to swing the moment you press Play.

> **On the obvious question.** This is not a Spider-Man game and cannot become
> one you distribute. Game *mechanics* are not protectable — web-swinging,
> wall-crawling, and web-zips are yours to build. The *character* is Marvel's:
> the name, the costume, the logo, the villains, the web pattern as trade dress.
> Build the traversal, ship it as your own character. If you want to make an
> actual Spider-Man game you need a licence from Marvel Games, which is why
> Insomniac has one.

---

## Quick start

You need Unreal Engine 5.6 and a C++ toolchain: Xcode on macOS, or Visual
Studio 2022 with the "Game development with C++" workload on Windows.

**macOS**

```
1. Open WebSlinger.uproject. It reports the module is missing
   and offers to rebuild - say yes. First build takes a few minutes.
2. File -> New Level -> Empty Level
3. Drag a CityBlockGenerator from the Place Actors panel into the level
   (search "City Block"). It brings its own sun, sky and fog, so the
   level lights itself.
4. Drag in a Player Start and set its Z to about 4000
5. Press Play
```

An Empty Level in Unreal has no lighting whatsoever and renders black, which
is why the generator carries a sun, a real-time sky light, a Sky Atmosphere and
height fog of its own. Dropping it into a level that is already lit means two
suns fighting - untick **bGenerateLighting** on the actor in that case.

If the rebuild prompt does not appear, generate an Xcode project first:
right-click `WebSlinger.uproject` -> Services -> Generate Xcode Project, then
build the `WebSlingerEditor` scheme.

**Windows** is the same, except step 1 is right-click `WebSlinger.uproject` ->
Generate Visual Studio project files, then build the `WebSlingerEditor` target.

The game mode is already wired in `Config/DefaultEngine.ini`, so any empty level
spawns the slinger pawn and its HUD with no Blueprint needed.

**Save the level and set it as the editor/game default map** so you are not
rebuilding it each session.

## Controls

| Input | Action |
|---|---|
| `W` `A` `S` `D` | Move — camera-relative in the air, flat on the ground |
| Mouse | Look |
| **Hold** Left Mouse | Fire and hold the web. Release to let go |
| Right Mouse | Web-zip — a fast pull to the target |
| `Space` | Jump; cuts the line mid-swing; wall-jumps off a crawl |
| `Q` / `E`, mouse wheel | Pay out / reel in the line |
| Hold `Left Shift` | Wall-crawl the surface you are looking at |

Gamepad is mapped too: right trigger webs, left trigger zips, left shoulder
crawls.

The reticle is the thing to watch. Dim cross means nothing in range; **red
diamond** means a shot connects right now; **blue** means you are attached, and
it tracks the anchor across the screen so you can see the pivot you are turning
around.

---

## How the swing works

The interesting code is `UWebSlingerMovementComponent::PhysSwinging`, a custom
movement mode (`MOVE_Custom` / `CMOVE_Swinging`) on the character movement
component.

**The line is a distance constraint, not a spring.** Each frame:

1. Gravity accelerates you. This is the only thing that powers a swing at rest.
2. Steering thrust is applied, projected onto the plane perpendicular to the
   line — pushing "toward the anchor" cannot fight the constraint and jitter.
3. The line length updates (manual reel, or auto-pump — see below).
4. **Tension.** Only when the line is taut, and only on the component of
   velocity leaving the sphere, that component is removed. A rope pulls; it
   never pushes. This single step is what makes it read as a rope rather than a
   bungee cord.
5. Drag and a speed clamp.
6. Move, sweeping for collision.
7. **Positional correction.** Integrating in discrete steps overshoots the
   constraint sphere every frame. Left uncorrected the line stretches and the
   arc goes soft, so the capsule is pulled back onto the sphere *without
   touching velocity* — momentum survives the correction.

Steps 4 and 7 are the two that people usually miss. Doing only 4 lets the rope
creep longer; doing only 7 (position-based, deriving velocity from
displacement) bleeds energy and kills your ability to accelerate.

### Auto-pump

`bAutoPump` shortens the line near the bottom of the arc and pays it out near
the top — exactly how a child pumps a playground swing, and for the same
physical reason: tension is highest at the bottom, so shortening there does the
most work. It means a player who just holds the mouse button gains speed
instead of decaying to a stop. Turn it off for a stricter simulation.

## What makes it work in *first person*

Most of the feel is camera work, not physics. Two things matter more than any
tuning value in the movement component:

- **The FOV widens with speed** and the **view rolls into the anchor** so the
  horizon banks through the arc. Without those, the exact same motion reads as
  sliding rather than swinging. Both are in
  `AWebSlingerCharacter::UpdateCameraFeel`. Roll is capped at 16° — past about
  20° it starts making people ill.
- **Aim assist is generous.** A bare centre-ray trace misses constantly at
  speed, because you look where you want to *go*, not at the one pixel of
  cornice that would hold. `UWebShooterComponent::FindAnchor` fans a sphere
  sweep over a 14° cone in scored rings and takes the best candidate, preferring
  near-centre and nearby. Anchors below you are rejected outright — they drag
  you into the street.

Tune both from the details panel: every value is an `EditDefaultsOnly`
`UPROPERTY` grouped under Swing, Wall Crawl, Camera, Aim Assist and Zip.

---

## Layout

```
WebSlinger.uproject         CableComponent plugin enabled for the web visual
Config/
  DefaultEngine.ini         game mode, physics, forced legacy input classes
  DefaultInput.ini          all key bindings (see "Migrating to Enhanced Input")
Source/WebSlinger/
  WebSlingerMovementComponent   the rope constraint, wall crawl, wall jump
  WebShooterComponent           anchor search, aim assist, cable visual, zip
  WebSlingerCharacter           camera feel, input, crawl surface search
  WebSlingerHUD                 canvas reticle and speed bar, no UMG assets
  CityBlockGenerator            seeded greybox city from engine cubes, plus
                                the sun/sky/fog an Empty Level lacks
  WebSlingerGameMode            wires the pawn and HUD to any empty level
```

## Honest limits

- **Not network-predicted.** Custom movement modes need `FSavedMove_Character`
  work to replicate. This is single-player. Adding rollback for a rope
  constraint is a real project, not an afternoon.
- **Wall-crawling keeps the capsule upright.** Proper gravity reorientation is a
  large job, and in first person with no visible body the difference is nearly
  invisible — so the capsule stays vertical and only the movement plane rotates.
  If you add a body mesh you will need the real thing; UE 5.4+ has
  `SetGravityDirection` on the movement component for exactly this.
- **One line at a time.** Dual-web constraints are much harder than two of these
  bolted together: two hard distance constraints on one body need an iterative
  solver, or they fight and buzz.
- **The city is a greybox.** Boxes on a grid, no interiors, no detail, no
  ledges to catch, and one untextured material on everything. It is a physics
  test space, not a level.
- **No mesh, no animation, no sound.** In first person you never see the body,
  which is what makes the prototype honest — but it also means half of what
  sells a swing in a shipped game is simply absent here.
- **Input bindings are code, not assets.** Enhanced Input normally wants an
  `InputMappingContext` and one `InputAction` per binding as `.uasset` files,
  which are binary and cannot live in a text-only repo. They are constructed at
  runtime in `AWebSlingerCharacter::BuildInputAssets` instead - same behaviour,
  but you rebind keys by editing C++ rather than by opening an asset. If you
  later want them as real assets, author them in the editor and swap the
  `Act*` pointers for `UPROPERTY(EditDefaultsOnly)` references; the handlers do
  not change.

### Adding a body

The character deliberately has no visible mesh. To add first-person arms,
attach a skeletal mesh to `Camera` in the constructor and drop the
`GetMesh()->SetVisibility(false)` line. Drive the animation from
`GetSlingerMovement()->IsSwinging()`, `IsWallCrawling()` and `GetAnchor()` — the
anchor is what an IK-aimed web-shooter arm needs.

### On other engine versions

Written against **UE 5.5**. The one thing that breaks on 5.3 and earlier is
`DoJump`, which gained its `DeltaTime` parameter in 5.4 — drop the second
argument in `WebSlingerMovementComponent` and it builds.
