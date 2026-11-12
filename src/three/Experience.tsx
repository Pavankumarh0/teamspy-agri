import { Suspense, useEffect, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { Environment, PerformanceMonitor, Preload } from '@react-three/drei'
import { ACESFilmicToneMapping, FogExp2, SRGBColorSpace } from 'three'
import type { Quality } from '../lib/quality'
import { installAtmosphere } from './shaders/chunks'
import { CameraRig } from './CameraRig'
import { Sun } from './Sun'
import { Effects } from './Effects'
import { Sky } from './world/Sky'
import { Terrain } from './world/Terrain'
import { Grass } from './world/Grass'
import { Wheat } from './world/Wheat'
import { Flowers } from './world/Flowers'
import { Crops } from './world/Crops'
import { Trees } from './world/Trees'
import { Farmer } from './world/Farmer'
import { Cows } from './world/Cows'
import { Tractor } from './world/Tractor'
import { Windmill } from './world/Windmill'
import { Farmstead } from './world/Farmstead'
import { Birds, Butterflies, Pollen } from './world/Ambient'
import { Markers } from './world/Markers'

installAtmosphere()

/** Debug switch for profiling: ?off=grass,wheat,post,shadows,trees,sky,flowers,crops,animals */
const OFF = new Set((new URLSearchParams(window.location.search).get('off') ?? '').split(',').filter(Boolean))
const on = (k: string) => !OFF.has(k)

/** Fires once the scene has committed and rendered two frames (shaders compiled). */
function SceneReady() {
  useEffect(() => {
    let id = requestAnimationFrame(() => {
      id = requestAnimationFrame(() => window.dispatchEvent(new Event('scene-ready')))
    })
    return () => cancelAnimationFrame(id)
  }, [])
  return null
}

export function Experience({ quality }: { quality: Quality }) {
  const [dpr, setDpr] = useState(quality.startDpr ?? quality.dpr[1])

  return (
    <Canvas
      className="webgl"
      dpr={dpr}
      shadows={on('shadows') ? 'percentage' : false}
      eventSource={document.getElementById('root') ?? undefined}
      eventPrefix="client"
      camera={{ fov: 38, near: 0.1, far: 4200, position: [-26, 26, 46] }}
      gl={{
        antialias: !quality.post,
        powerPreference: 'high-performance',
        toneMapping: ACESFilmicToneMapping,
        outputColorSpace: SRGBColorSpace,
        stencil: false,
      }}
      onCreated={({ scene, gl }) => {
        if (import.meta.env.DEV || OFF.size) (window as unknown as { __gl: unknown }).__gl = gl
        scene.fog = new FogExp2('#cfd9d6', 0.00115)
        gl.toneMappingExposure = 1.05
      }}
    >
      <PerformanceMonitor
        bounds={(refresh) => (refresh > 90 ? [55, 90] : [42, 58])}
        onDecline={() => setDpr((d) => Math.max(quality.dpr[0], +(d - 0.12).toFixed(2)))}
        onIncline={() => setDpr((d) => Math.min(quality.dpr[1], +(d + 0.1).toFixed(2)))}
        flipflops={4}
      />
      <Suspense fallback={null}>
        {on('sky') && <Sky clouds />}
        <Environment resolution={128} frames={1} environmentIntensity={0.45}>
          <Sky clouds={false} />
        </Environment>
        <Sun mapSize={quality.shadowMap} throttle={quality.tier !== 'high'} />
        <CameraRig />

        <Terrain />
        {on('grass') && <Grass density={quality.grass} />}
        {on('wheat') && <Wheat density={quality.wheat} />}
        {on('flowers') && <Flowers density={quality.flowers} />}
        {on('crops') && <Crops density={quality.tier === 'low' ? 0.5 : 1} />}
        {on('trees') && <Trees fraction={quality.trees} forest={quality.forest} />}
        <Farmstead />
        <Windmill />
        <Farmer />
        {on('animals') && <Cows />}
        <Tractor />
        <Birds count={quality.birds} />
        <Butterflies count={quality.tier === 'low' ? 5 : 9} />
        <Pollen count={quality.pollen} />
        <Markers />

        <Preload all />
        <SceneReady />
      </Suspense>
      {quality.post && on('post') && <Effects msaa={quality.msaa} />}
    </Canvas>
  )
}
