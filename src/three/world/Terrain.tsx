import { useMemo } from 'react'
import { useTexture } from '@react-three/drei'
import { BufferAttribute, BufferGeometry, ClampToEdgeWrapping, DataTexture, Float32BufferAttribute, LinearFilter, MeshStandardMaterial, RedFormat, RepeatWrapping, SRGBColorSpace, UnsignedByteType, Vector4 } from 'three'
import CustomShaderMaterial from 'three-custom-shader-material/vanilla'
import { heightAt } from '../../lib/terrain'
import { CROPS, CROP_ROW_SPACING, PASTURE, ROAD_SEGMENTS, ROAD_WIDTH, WHEAT } from '../../config/world'
import { NOISE_GLSL } from '../shaders/chunks'

const HALF = 1600
const SEGMENTS = 360

/** Grid with vertices concentrated near the farm and coarse toward the mountains. */
function buildTerrainGeometry(segments: number) {
  const n = segments + 1
  const warp = (u: number) => Math.sign(u) * (0.14 * Math.abs(u) + 0.42 * Math.abs(u) ** 2 + 0.44 * Math.abs(u) ** 4) * HALF
  const pos = new Float32Array(n * n * 3)
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const x = warp((i / segments) * 2 - 1)
      const z = warp((j / segments) * 2 - 1)
      const k = (j * n + i) * 3
      pos[k] = x
      pos[k + 1] = heightAt(x, z)
      pos[k + 2] = z
    }
  }
  const idx = new Uint32Array(segments * segments * 6)
  let p = 0
  for (let j = 0; j < segments; j++) {
    for (let i = 0; i < segments; i++) {
      const a = j * n + i
      const b = a + 1
      const c = a + n
      const d = c + 1
      idx[p++] = a
      idx[p++] = c
      idx[p++] = b
      idx[p++] = b
      idx[p++] = c
      idx[p++] = d
    }
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new Float32BufferAttribute(pos, 3))
  g.setIndex(new BufferAttribute(idx, 1))
  g.computeVertexNormals()
  g.computeBoundingSphere()
  return g
}

const ROAD_MAX = 6 // metres encoded in the distance field
const ROAD_RES = 0.25 // metres per texel

/** Bakes distance-to-nearest-road into a small texture so the ground shader does one lookup instead of a loop. */
function buildRoadField() {
  let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity
  for (const [ax, az, bx, bz] of ROAD_SEGMENTS) {
    minX = Math.min(minX, ax, bx); maxX = Math.max(maxX, ax, bx)
    minZ = Math.min(minZ, az, bz); maxZ = Math.max(maxZ, az, bz)
  }
  minX -= ROAD_MAX; minZ -= ROAD_MAX; maxX += ROAD_MAX; maxZ += ROAD_MAX
  const w = Math.ceil((maxX - minX) / ROAD_RES)
  const h = Math.ceil((maxZ - minZ) / ROAD_RES)
  const data = new Uint8Array(w * h)
  for (let j = 0; j < h; j++) {
    const z = minZ + (j + 0.5) * ROAD_RES
    for (let i = 0; i < w; i++) {
      const x = minX + (i + 0.5) * ROAD_RES
      let d2 = ROAD_MAX * ROAD_MAX
      for (const [ax, az, bx, bz] of ROAD_SEGMENTS) {
        const abx = bx - ax, abz = bz - az
        const t = Math.max(0, Math.min(1, ((x - ax) * abx + (z - az) * abz) / (abx * abx + abz * abz)))
        const dx = x - ax - abx * t, dz = z - az - abz * t
        const dd = dx * dx + dz * dz
        if (dd < d2) d2 = dd
      }
      data[j * w + i] = Math.round((Math.sqrt(d2) / ROAD_MAX) * 255)
    }
  }
  const tex = new DataTexture(data, w, h, RedFormat, UnsignedByteType)
  tex.magFilter = tex.minFilter = LinearFilter
  tex.wrapS = tex.wrapT = ClampToEdgeWrapping
  tex.needsUpdate = true
  return { tex, box: new Vector4(minX, minZ, maxX, maxZ) }
}

export function Terrain() {
  const [soil, grass] = useTexture(['/textures/soil_diff.webp', '/textures/grass_diff.webp'])

  const geometry = useMemo(() => buildTerrainGeometry(SEGMENTS), [])

  const material = useMemo(() => {
    for (const t of [soil, grass]) {
      t.wrapS = t.wrapT = RepeatWrapping
      t.colorSpace = SRGBColorSpace
      t.anisotropy = 8
    }
    const road = buildRoadField()
    return new CustomShaderMaterial({
      baseMaterial: MeshStandardMaterial,
      roughness: 1,
      metalness: 0,
      uniforms: {
        uSoil: { value: soil },
        uGrass: { value: grass },
        uWheat: { value: new Vector4(WHEAT.cx, WHEAT.cz, WHEAT.hw, WHEAT.hd) },
        uWheatRot: { value: WHEAT.rot },
        uCrops: { value: new Vector4(CROPS.cx, CROPS.cz, CROPS.hw, CROPS.hd) },
        uCropRot: { value: CROPS.rot },
        uPasture: { value: new Vector4(PASTURE.cx, PASTURE.cz, PASTURE.hw, PASTURE.hd) },
        uRoadTex: { value: road.tex },
        uRoadBox: { value: road.box },
      },
      vertexShader: /* glsl */ `
        varying vec3 vWPos;
        varying vec3 vWNormal;
        void main() {
          vWPos = (modelMatrix * vec4(position, 1.0)).xyz;
          vWNormal = normalize(mat3(modelMatrix) * normal);
        }
      `,
      fragmentShader: /* glsl */ `
        uniform sampler2D uSoil;
        uniform sampler2D uGrass;
        uniform vec4 uWheat;
        uniform float uWheatRot;
        uniform vec4 uCrops;
        uniform float uCropRot;
        uniform vec4 uPasture;
        uniform sampler2D uRoadTex;
        uniform vec4 uRoadBox;
        varying vec3 vWPos;
        varying vec3 vWNormal;
        ${NOISE_GLSL}

        vec2 fhLocal(vec2 p, vec2 c, float r) {
          p -= c;
          float s = sin(r), co = cos(r);
          return vec2(co * p.x - s * p.y, s * p.x + co * p.y);
        }
        float fhBox(vec2 p, vec2 b) {
          vec2 d = abs(p) - b;
          return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
        }
        float lum(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

        void main() {
          vec2 p = vWPos.xz;
          float nA = fh_vnoise(p * 0.035);
          float nB = fh_vnoise(p * 0.21 + 4.0);
          float nC = fh_vnoise(p * 1.3);
          float gTex = lum(texture2D(uGrass, p * 0.21).rgb);
          vec3 soilTex = texture2D(uSoil, p * 0.27).rgb;
          float sTex = lum(soilTex);

          // --- meadow ---
          vec3 g1 = vec3(0.062, 0.135, 0.024);
          vec3 g2 = vec3(0.120, 0.205, 0.036);
          vec3 dry = vec3(0.24, 0.22, 0.075);
          vec3 col = mix(g1, g2, nA);
          col = mix(col, dry, smoothstep(0.62, 0.95, nB) * 0.3);
          col *= 0.62 + gTex * 1.15;

          // --- pasture: grazed, slightly brighter with worn patches ---
          float dP = fhBox(p - uPasture.xy, uPasture.zw);
          float inP = 1.0 - smoothstep(-0.5, 0.8, dP);
          vec3 grazed = mix(vec3(0.085, 0.175, 0.03), vec3(0.17, 0.16, 0.07), smoothstep(0.72, 0.95, nB) * 0.5);
          col = mix(col, grazed * (0.7 + gTex * 0.9), inP * 0.75);

          // --- wheat stubble under the wheat ---
          vec2 wl = fhLocal(p, uWheat.xy, uWheatRot);
          float inW = 1.0 - smoothstep(-0.4, 0.6, fhBox(wl, uWheat.zw));
          vec3 stubble = vec3(0.30, 0.21, 0.075) * (0.55 + sTex * 1.2);
          col = mix(col, stubble, inW);

          // --- ploughed field with crop rows ---
          vec2 cl = fhLocal(p, uCrops.xy, uCropRot);
          float inC = 1.0 - smoothstep(-0.4, 0.6, fhBox(cl, uCrops.zw));
          float ridge = 0.5 + 0.5 * cos(cl.x * 6.2831853 / ${CROP_ROW_SPACING.toFixed(3)});
          vec3 soil = soilTex * vec3(0.78, 0.62, 0.48) * (0.55 + 0.6 * ridge);
          vec3 rows = mix(soil, vec3(0.07, 0.15, 0.03) * (0.8 + 0.4 * nC), smoothstep(0.72, 0.96, ridge) * 0.65);
          col = mix(col, rows, inC);

          // --- dirt roads with tyre tracks and a grassy crown ---
          vec2 ruv = (p - uRoadBox.xy) / (uRoadBox.zw - uRoadBox.xy);
          float dR = ${ROAD_MAX.toFixed(1)};
          if (ruv.x > 0.0 && ruv.x < 1.0 && ruv.y > 0.0 && ruv.y < 1.0) dR = texture2D(uRoadTex, ruv).r * ${ROAD_MAX.toFixed(1)};
          float edge = ${(ROAD_WIDTH * 0.5).toFixed(2)} + (nC - 0.5) * 0.5;
          float road = 1.0 - smoothstep(edge - 0.3, edge + 0.45, dR);
          vec3 dirt = vec3(0.32, 0.24, 0.15) * (0.5 + sTex * 1.1);
          dirt *= 1.0 - smoothstep(0.35, 0.0, abs(dR - 0.85)) * 0.25;
          dirt = mix(dirt, col * 0.95, smoothstep(0.32, 0.0, dR) * 0.6);
          col = mix(col, dirt, road);

          // --- patchwork of neighbouring farms on the valley floor ---
          float rFarm = length(p - vec2(-4.0, -34.0));
          float far = smoothstep(90.0, 140.0, rFarm) * (1.0 - smoothstep(5.0, 18.0, vWPos.y));
          if (far > 0.001) {
            vec2 q = mat2(0.94, 0.34, -0.34, 0.94) * p;
            vec2 cell = vec2(64.0, 44.0);
            vec2 id = floor(q / cell);
            vec2 f = fract(q / cell);
            float h = fh_hash12(id);
            vec3 fc;
            if (h < 0.26) fc = vec3(0.40, 0.29, 0.085);
            else if (h < 0.52) fc = vec3(0.085, 0.17, 0.03);
            else if (h < 0.70) fc = vec3(0.17, 0.26, 0.045);
            else if (h < 0.85) fc = vec3(0.19, 0.12, 0.065);
            else fc = vec3(0.26, 0.25, 0.075);
            float stripes = 0.86 + 0.14 * sin((h > 0.5 ? f.x : f.y) * 6.2831 * 20.0);
            fc *= stripes * (0.82 + 0.36 * fh_vnoise(q * 0.04 + h * 10.0));
            vec2 e = min(f, 1.0 - f) * cell;
            float hedge = 1.0 - smoothstep(1.0, 3.2, min(e.x, e.y));
            fc = mix(fc, vec3(0.025, 0.06, 0.014), hedge * 0.9);
            col = mix(col, fc, far);
          }

          // --- forested foothills, rock and snow on the range ---
          float slope = 1.0 - clamp(vWNormal.y, 0.0, 1.0);
          vec3 forest = vec3(0.03, 0.065, 0.018) * (0.75 + 0.5 * nB);
          col = mix(col, forest, smoothstep(9.0, 28.0, vWPos.y) * 0.85);
          vec3 rock = vec3(0.16, 0.15, 0.14) * (0.7 + 0.6 * fh_vnoise(p * 0.018));
          col = mix(col, rock, smoothstep(0.38, 0.62, slope) * smoothstep(40.0, 90.0, vWPos.y));
          col = mix(col, rock * vec3(0.95, 0.98, 1.05), smoothstep(95.0, 150.0, vWPos.y) * 0.75);
          float snow = smoothstep(150.0, 185.0, vWPos.y + (fh_vnoise(p * 0.025) - 0.5) * 40.0);
          snow *= 1.0 - smoothstep(0.5, 0.78, slope);
          col = mix(col, vec3(0.82, 0.85, 0.9), snow);

          csm_DiffuseColor = vec4(col, 1.0);
          csm_Roughness = 1.0 - snow * 0.4;
        }
      `,
    })
  }, [soil, grass])

  return <mesh geometry={geometry} material={material} receiveShadow />
}
