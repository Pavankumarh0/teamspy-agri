import { useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { BackSide, ShaderMaterial } from 'three'
import { ATMOSPHERE_GLSL, NOISE_GLSL } from '../shaders/chunks'

/**
 * Infinite sky dome: the same atmosphere gradient the fog uses, an HDR sun
 * disc (feeds the bloom pass) and drifting fbm cumulus lit from the sun side.
 */
export function Sky({ clouds = true }: { clouds?: boolean }) {
  const material = useMemo(
    () =>
      new ShaderMaterial({
        uniforms: { uTime: { value: 0 } },
        side: BackSide,
        depthWrite: false,
        defines: clouds ? { CLOUDS: 1 } : {},
        vertexShader: /* glsl */ `
          varying vec3 vDir;
          void main() {
            vDir = position;
            vec4 p = projectionMatrix * vec4(mat3(viewMatrix) * position, 1.0);
            gl_Position = p.xyww;
            gl_Position.z = gl_Position.w * 0.99999;
          }
        `,
        fragmentShader: /* glsl */ `
          uniform float uTime;
          varying vec3 vDir;
          ${NOISE_GLSL}
          ${ATMOSPHERE_GLSL}
          void main() {
            vec3 dir = normalize(vDir);
            vec3 col = fh_atmosphere(dir);
            float sd = dot(dir, FH_SUN_DIR);

            #ifdef CLOUDS
            float cover = 0.0;
            if (dir.y > 0.0) {
              vec2 uv = dir.xz / (dir.y + 0.1);
              uv = uv * 0.42 + uTime * vec2(0.0035, 0.0012);
              float d = fh_fbm(uv * 1.25) * 0.78 + fh_fbm(uv * 4.0 + 3.1) * 0.32;
              cover = smoothstep(0.55, 0.86, d);
              vec2 toSun = normalize(FH_SUN_DIR.xz) * 0.05;
              float dl = fh_fbm((uv + toSun) * 1.25) * 0.78 + fh_vnoise((uv + toSun) * 4.0 + 3.1) * 0.16 + 0.08;
              float shade = clamp((d - dl) * 4.0 + 0.6, 0.0, 1.0);
              vec3 shadowCol = mix(FH_HORIZON_COOL, FH_UPPER, 0.5) * 0.78;
              vec3 litCol = vec3(1.04, 0.99, 0.93) * 1.12;
              vec3 cloud = mix(shadowCol, litCol, shade);
              cloud += FH_SUN_GLOW * pow(max(sd, 0.0), 7.0) * 1.1 * (1.0 - cover * 0.6);
              cloud = mix(fh_atmosphere(dir), cloud, smoothstep(0.0, 0.3, dir.y));
              col = mix(col, cloud, cover * smoothstep(0.015, 0.2, dir.y) * 0.95);
            }
            float sunVis = 1.0 - cover * 0.85;
            #else
            float sunVis = 1.0;
            #endif

            col += FH_SUN * smoothstep(0.99955, 0.9998, sd) * 22.0 * sunVis;
            col += FH_SUN_GLOW * pow(max(sd, 0.0), 700.0) * 2.5 * sunVis;

            gl_FragColor = vec4(col, 1.0);
            #include <tonemapping_fragment>
            #include <colorspace_fragment>
          }
        `,
      }),
    [clouds],
  )

  useFrame((_, dt) => {
    material.uniforms.uTime.value += dt
  })

  return (
    <mesh material={material} renderOrder={-1000} frustumCulled={false}>
      <sphereGeometry args={[1, 48, 24]} />
    </mesh>
  )
}
