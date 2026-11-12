import type { SVGProps } from 'react'

const base = (p: SVGProps<SVGSVGElement>) => ({
  width: 24,
  height: 24,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
  ...p,
})

export const LogoMark = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)} viewBox="0 0 32 32" strokeWidth={1.8}>
    <path d="M16 29V14" />
    <path d="M16 18c0-6 4.5-10 11-10 0 6.5-4.5 10-11 10Z" fill="currentColor" fillOpacity={0.18} />
    <path d="M16 22c0-5-3.8-8.5-9.5-8.5 0 5.5 3.8 8.5 9.5 8.5Z" fill="currentColor" fillOpacity={0.18} />
    <path d="M6 29h20" />
  </svg>
)

export const Arrow = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
)

export const ArrowDown = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M12 5v14M6 13l6 6 6-6" />
  </svg>
)

export const Wheat = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M12 22V9" />
    <path d="M12 9c-2-1-3-3-3-5 2 0 3 1.5 3 3.5M12 9c2-1 3-3 3-5-2 0-3 1.5-3 3.5" />
    <path d="M12 14c-2.2-.8-3.5-2.6-3.5-4.8 2.2.3 3.5 2 3.5 4.1M12 14c2.2-.8 3.5-2.6 3.5-4.8-2.2.3-3.5 2-3.5 4.1" />
    <path d="M12 19c-2.2-.8-3.5-2.6-3.5-4.8 2.2.3 3.5 2 3.5 4.1M12 19c2.2-.8 3.5-2.6 3.5-4.8-2.2.3-3.5 2-3.5 4.1" />
  </svg>
)

export const Leaf = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M5 19c0-8 5-14 15-14 0 10-6 15-14 15" />
    <path d="M5 19 13 11" />
  </svg>
)

export const Drop = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z" />
    <path d="M9.5 15a2.5 2.5 0 0 0 2.5 2.5" />
  </svg>
)

export const Sun = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
)

export const Satellite = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="m13 7 4 4M9.5 10.5l4 4" />
    <rect x="9" y="7" width="6" height="6" rx="1" transform="rotate(45 12 10)" />
    <path d="M3 13l3-3 3 3-3 3zM15 5l3-3 3 3-3 3z" />
    <path d="M5 19a4 4 0 0 0 4-4M3 21a8 8 0 0 0 8-8" />
  </svg>
)

export const Sensor = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M12 21v-8" />
    <circle cx="12" cy="10" r="2" />
    <path d="M8.5 6.5a5 5 0 0 1 7 0M6 4a8.5 8.5 0 0 1 12 0" />
    <path d="M5 21h14" />
  </svg>
)

export const TractorIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <circle cx="7" cy="16" r="4" />
    <circle cx="18" cy="17.5" r="2.5" />
    <path d="M7 16h0M10.5 14H15.5M4 12V7h6l2 5M12 12h7l1 3.5" />
    <path d="M17 12V8" />
  </svg>
)

export const Cow = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M5 8 3 6M19 8l2-2" />
    <path d="M6 9c0-2 2.7-3 6-3s6 1 6 3v4c0 3-2.7 6-6 6s-6-3-6-6Z" />
    <path d="M9 15.5h6M10 12h.01M14 12h.01" />
  </svg>
)

export const Wind = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M3 8h11a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h7" />
  </svg>
)

export const Bird = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M3 11c3-1 5 0 7 2 1.5-4 4.5-6 9-6-1 4-3 7-7 8l1 4-3-2c-3-1-5-3-7-6Z" />
  </svg>
)

export const Mic = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" />
  </svg>
)

export const Speaker = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M4 9.5v5h3.5L12 19V5L7.5 9.5Z" />
    <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />
  </svg>
)

export const Globe = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3Z" />
  </svg>
)

export const Play = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M8 5.5v13l10.5-6.5z" fill="currentColor" />
  </svg>
)

export const Menu = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M4 8h16M4 16h16" />
  </svg>
)

export const Close = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
)
