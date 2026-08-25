// The four spaces. Dimensions are the "100% size" starting point; the size
// control scales them, and the user can also drag individual walls.

/**
 * @typedef {Object} SpacePreset
 * @property {string} id
 * @property {string} name
 * @property {string} blurb
 * @property {{w:number,d:number,h:number}} dims   metres (width, depth, height)
 * @property {[number,number]} sizeRange           allowed scale factors
 * @property {{floor:string,ceiling:string,walls:string}} surfaces material ids
 * @property {{coverage:number,material:string}|null} seating fraction of floor
 * @property {{stage:number,type:string}} treatment  how far through the plan
 * @property {number} [pitch]  gable rise above the mean ceiling height, metres
 * @property {{x:number,z:number}} sourceAt        default position, 0..1 of room
 * @property {number} micDistance                  default metres from source
 * @property {string} palette                      renderer accent
 */

/** @type {SpacePreset[]} */
export const PRESETS = [
  {
    id: 'studio',
    name: 'Studio',
    blurb: 'Small, dead, controlled. The tail is over before you notice it.',
    dims: { w: 7.5, d: 5.5, h: 3.2 },
    sizeRange: [0.45, 2.6],
    // Gable running the length of the room. Rises this far above the mean at
    // the ridge and drops as far below it at the eaves, so the volume is
    // exactly what a flat ceiling at `h` would give.
    pitch: 0.46,
    surfaces: { floor: 'woodFloor', ceiling: 'woodPanel', walls: 'woodPanel' },
    seating: null,
    treatment: { stage: 5, type: 'rockwool' },
    sourceAt: { x: 0.5, z: 0.35 },
    micDistance: 0.85,
    palette: '#e8a33d',
  },
  {
    id: 'hall',
    name: 'Concert hall',
    blurb: 'Wood and plaster, seats soaking up the mids. Long but warm.',
    dims: { w: 26, d: 40, h: 15 },
    sizeRange: [0.4, 2.0],
    surfaces: { floor: 'woodFloor', ceiling: 'plaster', walls: 'woodPanel' },
    seating: { coverage: 0.62, material: 'seatsEmpty' },
    treatment: { stage: 0, type: 'drapes' },
    sourceAt: { x: 0.5, z: 0.16 },
    micDistance: 3.0,
    palette: '#5fb0d6',
  },
  {
    id: 'cathedral',
    name: 'Cathedral',
    blurb: 'Stone on every surface. Nothing absorbs, so nothing stops.',
    dims: { w: 24, d: 68, h: 27 },
    sizeRange: [0.35, 1.8],
    surfaces: { floor: 'marble', ceiling: 'stone', walls: 'stone' },
    wallBlend: { material: 'glass', coverage: 0.2 },
    seating: { coverage: 0.38, material: 'seatsEmpty' },
    treatment: { stage: 0, type: 'drapes' },
    sourceAt: { x: 0.5, z: 0.2 },
    micDistance: 5.0,
    palette: '#9b8cd6',
  },
  {
    id: 'theater',
    name: 'Theatre',
    blurb: 'Drapes, plush seats, a fly tower over the stage. Dry and intimate.',
    dims: { w: 22, d: 26, h: 12 },
    sizeRange: [0.4, 2.2],
    surfaces: { floor: 'woodFloor', ceiling: 'plaster', walls: 'woodPanel' },
    seating: { coverage: 0.7, material: 'seatsFull' },
    treatment: { stage: 5, type: 'drapes' },
    sourceAt: { x: 0.5, z: 0.14 },
    micDistance: 2.2,
    palette: '#e0685f',
  },
];

export const PRESETS_BY_ID = Object.fromEntries(PRESETS.map((p) => [p.id, p]));
