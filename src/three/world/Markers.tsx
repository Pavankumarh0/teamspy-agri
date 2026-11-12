import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { AdditiveBlending, DoubleSide, Group, Mesh, PlaneGeometry, ShaderMaterial, Vector3 } from 'three'
import { CROPS, CROP_ROW_SPACING, SHOTS_LANDSCAPE, fromLocal, groundUnderShot } from '../../config/world'
import { heightAt } from '../../lib/terrain'
import { worldUiRef, onActiveSection, sectionWeight } from '../../lib/store'
import { globalUniforms } from '../uniforms'

/** A glass info card pinned to a point in the world, shown while its section is active. */
function WorldCard({ position, section, children, align = 'center' }: { position: [number, number, number]; section: number; children: ReactNode; align?: 'left' | 'center' | 'right' }) {
  const [on, setOn] = useState(false)
  useEffect(() => onActiveSection((a) => setOn(a === section)), [section])
  return (
    <Html position={position} center portal={worldUiRef as RefObject<HTMLElement>} zIndexRange={[4, 0]} className="world-card-wrap">
      <div className={`world-card align-${align} ${on ? 'is-on' : ''}`} aria-hidden={!on}>
        {children}
      </div>
    </Html>
  )
}

/** Thin additive light beam + ground ring marking a sensor. */
function Beacon({ x, z, section }: { x: number; z: number; section: number }) {
  const group = useRef<Group>(null)
  const ring = useRef<Mesh>(null)
  const y = heightAt(x, z)
  const beamMat = useMemo(
    () =>
      new ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        side: DoubleSide,
        uniforms: { uOpacity: { value: 0 }, uTime: globalUniforms.uTime },
        vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
        fragmentShader: `
          uniform float uOpacity; uniform float uTime; varying vec2 vUv;
          void main(){
            float a = (1.0 - vUv.y) * (0.6 + 0.4 * sin(vUv.y * 30.0 - uTime * 4.0));
            gl_FragColor = vec4(vec3(0.62, 1.0, 0.66) * 1.4, a * uOpacity * 0.55);
          }`,
      }),
    [],
  )
  const ringMat = useMemo(
    () =>
      new ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        uniforms: { uOpacity: { value: 0 }, uTime: globalUniforms.uTime },
        vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
        fragmentShader: `
          uniform float uOpacity; uniform float uTime; varying vec2 vUv;
          void main(){
            float r = length(vUv - 0.5) * 2.0;
            float pulse = fract(uTime * 0.6);
            float ring = smoothstep(0.06, 0.0, abs(r - pulse)) * (1.0 - pulse);
            float core = smoothstep(0.25, 0.0, r) * 0.4;
            gl_FragColor = vec4(vec3(0.62, 1.0, 0.66) * 1.5, (ring + core) * uOpacity);
          }`,
      }),
    [],
  )
  useFrame(() => {
    const w = sectionWeight(section, 0.7)
    beamMat.uniforms.uOpacity.value = w
    ringMat.uniforms.uOpacity.value = w
    if (group.current) group.current.visible = w > 0.01
  })
  return (
    <group ref={group} position={[x, y, z]}>
      <mesh material={beamMat} position={[0, 2.2, 0]}>
        <cylinderGeometry args={[0.05, 0.05, 4.4, 8, 1, true]} />
      </mesh>
      <mesh ref={ring} material={ringMat} position={[0, 0.25, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[5, 5]} />
      </mesh>
    </group>
  )
}

/** Holographic survey grid with a scan line sweeping the crop field. */
function HoloField() {
  const mesh = useRef<Mesh>(null)
  const geometry = useMemo(() => {
    const g = new PlaneGeometry(CROPS.hw * 2, CROPS.hd * 2, 52, 30)
    g.rotateX(-Math.PI / 2)
    const pos = g.attributes.position
    const v = new Vector3()
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i)
      const [wx, wz] = fromLocal(CROPS, v.x, v.z)
      pos.setY(i, heightAt(wx, wz) + 0.55)
    }
    return g
  }, [])
  const material = useMemo(
    () =>
      new ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        uniforms: { uOpacity: { value: 0 }, uTime: globalUniforms.uTime, uSize: { value: [CROPS.hw * 2, CROPS.hd * 2] } },
        vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
        fragmentShader: `
          uniform float uOpacity; uniform float uTime; uniform vec2 uSize; varying vec2 vUv;
          void main(){
            vec2 p = vUv * uSize;
            vec2 g = abs(fract(p / vec2(${CROP_ROW_SPACING * 2}, 3.0)) - 0.5);
            float grid = smoothstep(0.47, 0.5, max(g.x, g.y)) * 0.18;
            float scan = fract(uTime * 0.09);
            float band = exp(-pow((vUv.y - scan) * 26.0, 2.0));
            float trail = smoothstep(scan - 0.18, scan, vUv.y) * step(vUv.y, scan) * 0.25;
            vec2 e = min(vUv, 1.0 - vUv);
            float edge = smoothstep(0.012, 0.0, min(e.x, e.y));
            // health heat-map patches revealed behind the scan
            float heat = 0.5 + 0.5 * sin(p.x * 0.23 + 1.3) * sin(p.y * 0.31 - 0.4);
            vec3 healthy = vec3(0.55, 1.0, 0.55);
            vec3 attention = vec3(1.0, 0.82, 0.35);
            vec3 col = mix(healthy, attention, smoothstep(0.78, 0.95, heat));
            float a = grid + band * 0.26 + trail * 0.45 + edge * 0.45;
            gl_FragColor = vec4(col * 0.95, a * uOpacity);
          }`,
      }),
    [],
  )
  useFrame(() => {
    const w = sectionWeight(3, 0.75)
    material.uniforms.uOpacity.value = w
    if (mesh.current) mesh.current.visible = w > 0.01
  })
  const [cx, cz] = [CROPS.cx, CROPS.cz]
  return <mesh ref={mesh} geometry={geometry} material={material} position={[cx, 0, cz]} rotation={[0, CROPS.rot, 0]} renderOrder={5} />
}

export function Markers() {
  const sensors = useMemo(() => {
    // screen positions (NDC) on the left half of the technology shot
    const shot = SHOTS_LANDSCAPE[3]
    return ([[-0.74, -0.42], [-0.36, -0.3], [-0.6, -0.12]] as [number, number][]).map(([x, y]) => groundUnderShot(shot, x, y))
  }, [])
  const [wx, wz] = groundUnderShot(SHOTS_LANDSCAPE[1], -0.5, -0.32)

  return (
    <group>
      <WorldCard position={[wx, heightAt(wx, wz) + 2.4, wz]} section={1} align="left">
        <span className="wc-eyebrow">Field 07 · Wheat · Hindi</span>
        <strong lang="hi">कटाई में 12 दिन बाकी</strong>
        <span className="wc-meter"><i style={{ width: '86%' }} /></span>
        <span className="wc-foot" lang="hi">दाने की नमी 14.2%</span>
      </WorldCard>

      <HoloField />
      {sensors.map(([x, z], i) => (
        <Beacon key={i} x={x} z={z} section={3} />
      ))}
      <WorldCard position={[sensors[0][0], heightAt(sensors[0][0], sensors[0][1]) + 3.6, sensors[0][1]]} section={3}>
        <span className="wc-eyebrow">Sensor A3 · Tamil</span>
        <strong lang="ta">மண் ஈரப்பதம் 42%</strong>
        <span className="wc-foot" lang="ta">சரியான அளவு · பாசனம் தேவையில்லை</span>
      </WorldCard>
      <WorldCard position={[sensors[1][0], heightAt(sensors[1][0], sensors[1][1]) + 3.8, sensors[1][1]]} section={3}>
        <span className="wc-eyebrow">Crop health · Telugu</span>
        <strong lang="te">పంట ఆరోగ్యం బాగుంది</strong>
        <span className="wc-foot" lang="te">గత సీజన్ కంటే +18%</span>
      </WorldCard>
      <WorldCard position={[sensors[2][0], heightAt(sensors[2][0], sensors[2][1]) + 4.2, sensors[2][1]]} section={3}>
        <span className="wc-eyebrow">Nutrients · Bengali</span>
        <strong lang="bn">N · P · K সুষম</strong>
        <span className="wc-foot" lang="bn">এখন সার দেওয়ার দরকার নেই</span>
      </WorldCard>
    </group>
  )
}
