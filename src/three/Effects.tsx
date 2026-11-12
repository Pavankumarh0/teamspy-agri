import { Bloom, BrightnessContrast, EffectComposer, HueSaturation, SMAA, ToneMapping } from '@react-three/postprocessing'
import { ToneMappingMode } from 'postprocessing'

/** Bloom on the HDR sun / pollen + filmic tone mapping. Vignette and grain are CSS overlays. */
export function Effects({ msaa }: { msaa: number }) {
  const bloom = <Bloom mipmapBlur intensity={0.55} luminanceThreshold={0.92} luminanceSmoothing={0.25} radius={0.7} resolutionScale={0.5} />
  const tone = (
    <>
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <HueSaturation saturation={0.14} />
      <BrightnessContrast contrast={0.07} />
    </>
  )
  if (msaa > 0) {
    return (
      <EffectComposer multisampling={msaa} enableNormalPass={false}>
        {bloom}
        {tone}
      </EffectComposer>
    )
  }
  return (
    <EffectComposer multisampling={0} enableNormalPass={false}>
      {bloom}
      {tone}
      <SMAA />
    </EffectComposer>
  )
}
