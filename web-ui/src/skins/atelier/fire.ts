/**
 * A flame, drawn rather than downloaded.
 *
 * The forge's fire was a flat orange rectangle and a point light, which read
 * as a lit window. A flame has to move: this is two crossed quads running a
 * small noise shader -- rising scrolls of value noise shaped into a tongue,
 * additively blended so overlapping flames brighten the way embers do. Two
 * quads at right angles read as a volume from every direction an isometric
 * camera can take, without billboarding work per frame.
 *
 * Driven by the same elapsed clock as everything else, so a filmed replay
 * flickers exactly where the live run did.
 */

const VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const FRAGMENT = /* glsl */ `
  uniform float time;
  uniform vec3 base;
  uniform vec3 tip;
  varying vec2 vUv;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
      mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x),
      f.y
    );
  }

  void main() {
    vec2 uv = vUv;

    // Two octaves of noise scrolling upward at different speeds: the flame's
    // surface churns instead of sliding as one sheet.
    float churn = noise(vec2(uv.x * 3.0, uv.y * 4.0 - time * 2.1)) * 0.65
                + noise(vec2(uv.x * 7.0 + 3.7, uv.y * 9.0 - time * 3.7)) * 0.35;

    // How far up the flame this point is, once the noise has torn the edge.
    float up = uv.y + (churn - 0.5) * 0.6;

    // A tongue: bright and wide at the hearth, pinched and ragged at the tip.
    float fade = smoothstep(1.0, 0.25, up);
    float pinch = smoothstep(0.5, 0.1, abs(uv.x - 0.5) * (0.55 + up * 1.1));
    // The quad's own bottom edge must never print: feather the first few
    // percent so the flame grows out of the coals instead of off a rectangle.
    float seat = smoothstep(0.0, 0.07, uv.y);
    float flame = fade * pinch * seat;

    vec3 color = mix(base, tip, clamp(up, 0.0, 1.0));
    gl_FragColor = vec4(color * flame * 1.7, flame);
  }
`

export interface Fire {
  group: any
  /** Let the flame churn; elapsed in ms, shared with the rest of the board. */
  tick(elapsed: number): void
  /** Fire, banked coals, or the red of an alarm. */
  set(state: "burning" | "cold" | "alarmed"): void
  dispose(): void
}

/** How many embers drift up out of the fire at any moment. */
const EMBERS = 9

/** A flame `wide` across and `tall` high, standing on its own origin. */
export function makeFire(THREE: any, wide = 0.5, tall = 0.6): Fire {
  const uniforms = {
    time: { value: 0 },
    base: { value: new THREE.Color(1.0, 0.82, 0.35) },
    tip: { value: new THREE.Color(0.85, 0.22, 0.04) },
  }
  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  })

  const sheet = new THREE.PlaneGeometry(wide, tall)
  const group = new THREE.Group()
  for (const turn of [0, Math.PI / 2]) {
    const quad = new THREE.Mesh(sheet, material)
    quad.position.y = tall / 2
    quad.rotation.y = turn
    group.add(quad)
  }

  // -- embers: motes that break off the flame, sway, and die on the climb.
  // Per-point colours instead of per-point opacity, because PointsMaterial
  // has only one opacity and an ember must dim as it rises.
  const drift = (seed: number) => {
    const spun = Math.sin(seed * 127.1 + 311.7) * 43758.5453
    return spun - Math.floor(spun)
  }
  const emberSpots = new Float32Array(EMBERS * 3)
  const emberTints = new Float32Array(EMBERS * 3)
  const emberShape = new THREE.BufferGeometry()
  emberShape.setAttribute("position", new THREE.BufferAttribute(emberSpots, 3))
  emberShape.setAttribute("color", new THREE.BufferAttribute(emberTints, 3))
  const emberGlow = new THREE.PointsMaterial({
    size: 0.028,
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  const embers = new THREE.Points(emberShape, emberGlow)
  group.add(embers)

  return {
    group,
    tick(elapsed: number) {
      const time = elapsed / 1000
      uniforms.time.value = time

      for (let i = 0; i < EMBERS; i += 1) {
        const phase = drift(i * 3 + 1)
        const climb = (time * (0.16 + drift(i) * 0.1) + phase) % 1
        const sway = Math.sin(time * 1.7 + i * 2.1) * 0.05 * climb
        emberSpots[i * 3] = (drift(i * 7) - 0.5) * wide * 0.5 + sway
        emberSpots[i * 3 + 1] = tall * 0.25 + climb * tall * 1.15
        emberSpots[i * 3 + 2] = (drift(i * 11) - 0.5) * wide * 0.5 - sway
        // yellow at birth, red on the climb, dark by the top
        const dim = (1 - climb) * (1 - climb)
        emberTints[i * 3] = dim * 1.0
        emberTints[i * 3 + 1] = dim * (0.55 - climb * 0.3)
        emberTints[i * 3 + 2] = dim * 0.08
      }
      emberShape.attributes.position.needsUpdate = true
      emberShape.attributes.color.needsUpdate = true
    },
    set(state) {
      group.visible = state !== "cold"
      if (state === "alarmed") {
        // The same tongue, drained of heat: an alarm reads as wrong, not cosy.
        uniforms.base.value.setRGB(0.95, 0.3, 0.25)
        uniforms.tip.value.setRGB(0.5, 0.05, 0.1)
      } else {
        uniforms.base.value.setRGB(1.0, 0.82, 0.35)
        uniforms.tip.value.setRGB(0.85, 0.22, 0.04)
      }
    },
    dispose() {
      sheet.dispose()
      material.dispose()
      emberShape.dispose()
      emberGlow.dispose()
    },
  }
}
