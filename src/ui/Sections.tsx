import { useEffect, useState, type FormEvent } from 'react'
import { scrollToId } from './scroll'
import { Arrow, ArrowDown, Drop, Globe, Leaf, LogoMark, Mic, Play, Sensor, Speaker, Sun, Wheat, Wind } from './Icons'

function Kicker({ n, children }: { n: string; children: string }) {
  return (
    <p className="kicker" data-reveal>
      <span>{n}</span>
      {children}
    </p>
  )
}

/** "Chiguru" written in the scripts of the languages the device speaks. */
const CHIGURU_NAMES = [
  { lang: 'kn', label: 'Kannada', text: 'ಚಿಗುರು' },
  { lang: 'hi', label: 'Hindi', text: 'चिगुरु' },
  { lang: 'ta', label: 'Tamil', text: 'சிகுரு' },
  { lang: 'te', label: 'Telugu', text: 'చిగురు' },
  { lang: 'ml', label: 'Malayalam', text: 'ചിഗുരു' },
  { lang: 'bn', label: 'Bengali', text: 'চিগুরু' },
  { lang: 'gu', label: 'Gujarati', text: 'ચિગુરુ' },
  { lang: 'pa', label: 'Punjabi', text: 'ਚਿਗੁਰੁ' },
  { lang: 'or', label: 'Odia', text: 'ଚିଗୁରୁ' },
]

const HERO_WORDS = [{ lang: 'en', label: 'English', text: 'Chiguru' }, ...CHIGURU_NAMES]

/** Large hero word that cycles "Chiguru" through each language. */
function ChiguruWord() {
  const [active, setActive] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setActive((i) => (i + 1) % HERO_WORDS.length), 2200)
    return () => window.clearInterval(id)
  }, [])
  return (
    <span className="hero-word" aria-hidden>
      {HERO_WORDS.map((w, i) => (
        <span key={w.lang} lang={w.lang} className={i === active ? 'is-on' : ''}>
          {w.text}
        </span>
      ))}
    </span>
  )
}

export function Hero() {
  return (
    <section className="section hero" id="top" data-section="0">
      <div className="hero-scrim" aria-hidden />
      <div className="hero-copy">
        <p className="eyebrow glass" data-intro>
          <span className="pulse" />
          IoT farm assistant · Speaks your language
        </p>
        <h1 className="display" data-intro>
          <span className="sr-only">Chiguru</span>
          <ChiguruWord />
        </h1>
        <ul className="hero-names" aria-label="Chiguru, written in Indian languages" data-intro>
          {CHIGURU_NAMES.map((n) => (
            <li key={n.lang} lang={n.lang} title={n.label}>
              {n.text}
            </li>
          ))}
        </ul>
        <p className="lede" data-intro>
          Chiguru is an IoT device for the farm that listens and speaks in your own language. Ask it anything about your
          land — in Kannada, Hindi, Tamil, Telugu or your mother tongue — and it answers right back in the same language.
        </p>
        <div className="cta-row" data-intro>
          <button className="btn btn-primary" type="button" onClick={() => scrollToId('land')}>
            Explore Chiguru <Arrow width={18} height={18} />
          </button>
          <button className="btn btn-glass" type="button" onClick={() => scrollToId('contact')}>
            <span className="play">
              <Play width={12} height={12} />
            </span>
            Partner with us
          </button>
        </div>
        <dl className="hero-stats" data-intro>
          <div>
            <dt>Indian languages</dt>
            <dd>5+</dd>
          </div>
          <div>
            <dt>Live answers</dt>
            <dd>24/7</dd>
          </div>
          <div>
            <dt>Typing needed</dt>
            <dd>Zero</dd>
          </div>
        </dl>
      </div>

      <aside className="hero-aside glass" aria-label="Live readings from your field, shown in Kannada">
        <div className="aside-head">
          <span className="live" /> Your field · <span lang="kn">ಕನ್ನಡ</span>
        </div>
        <div className="aside-temp">
          <Sun width={30} height={30} />
          <strong>24°</strong>
          <span lang="kn">ಬಿಸಿಲು · ಸಂಜೆ 6:42</span>
        </div>
        <ul className="aside-list" lang="kn">
          <li>
            <Wind width={16} height={16} /> ಗಾಳಿ <b>12 km/h</b>
          </li>
          <li>
            <Drop width={16} height={16} /> ಮಣ್ಣಿನ ತೇವಾಂಶ <b>42%</b>
          </li>
          <li>
            <Wheat width={16} height={16} /> ಕೊಯ್ಲು <b className="ok">ಸಿದ್ಧ</b>
          </li>
        </ul>
      </aside>

      <button className="scroll-cue" type="button" onClick={() => scrollToId('land')} data-intro>
        <span className="scroll-line" />
        Scroll to see how it works
        <ArrowDown width={14} height={14} />
      </button>
    </section>
  )
}

export function Fields() {
  return (
    <section className="section align-right" id="land" data-section="1">
      <div className="panel">
        <Kicker n="01">Your Land</Kicker>
        <h2 className="title" data-split>
          Your land, in <em>your</em> language.
        </h2>
        <p className="body" data-reveal>
          Every farmer sees the details of their own land — soil, water, weather, crop health and harvest timing — in the
          language they choose. Kannada for one farmer, Hindi or Telugu for the next: the same live data, in words that feel
          like home.
        </p>
        <div className="crop-cards">
          {[
            { name: 'Wheat', native: 'गेहूँ', lang: 'hi', area: '2.5 ac · Hindi', yieldV: '3.4', pct: 82 },
            { name: 'Paddy', native: 'ಭತ್ತ', lang: 'kn', area: '1.8 ac · Kannada', yieldV: '4.1', pct: 74 },
            { name: 'Ragi', native: 'రాగులు', lang: 'te', area: '1.2 ac · Telugu', yieldV: '2.2', pct: 63 },
          ].map((c, i) => (
            <article className="crop-card glass" key={c.name} data-reveal data-delay={i * 0.08}>
              <header>
                <Wheat width={18} height={18} />
                <span>
                  {c.name} · <span lang={c.lang}>{c.native}</span>
                </span>
                <em>{c.area}</em>
              </header>
              <p>
                <strong>{c.yieldV}</strong> t/ha
              </p>
              <span className="meter">
                <i style={{ width: `${c.pct}%` }} />
              </span>
            </article>
          ))}
        </div>
        <ul className="chips" data-reveal>
          <li>Soil &amp; water</li>
          <li>Crop health alerts</li>
          <li>Read or listen</li>
        </ul>
      </div>
    </section>
  )
}

export function Pasture() {
  return (
    <section className="section align-left" id="voice" data-section="2">
      <div className="panel">
        <Kicker n="02">Ask Chiguru</Kicker>
        <h2 className="title" data-split>
          Just ask — in <em>your</em> own words.
        </h2>
        <p className="body" data-reveal>
          Farmers talk to the Chiguru device the way they would talk to a neighbour. It understands the question, checks what
          the sensors on their land are saying, and answers out loud in the very same language — no typing, no menus, no
          reading required.
        </p>
        <div className="feature-list">
          {[
            { icon: <Mic width={20} height={20} />, k: '5+', u: 'languages', t: 'understood by voice' },
            { icon: <Speaker width={20} height={20} />, k: 'Same', u: 'language', t: 'for every spoken answer' },
            { icon: <Sensor width={20} height={20} />, k: '24/7', u: 'live', t: 'answers from your own field' },
          ].map((f, i) => (
            <div className="feature glass" key={f.t} data-reveal data-delay={i * 0.08}>
              <span className="icon">{f.icon}</span>
              <strong>
                {f.k}
                <small>{f.u}</small>
              </strong>
              <span>{f.t}</span>
            </div>
          ))}
        </div>
        <blockquote className="quote glass" data-reveal>
          “If a farmer can say it, Chiguru should understand it — and answer the same way.”
          <cite>The idea behind Chiguru</cite>
        </blockquote>
      </div>
    </section>
  )
}

export function Technology() {
  const items = [
    { icon: <Sensor />, t: 'Field sensors', d: 'Soil moisture, temperature and nutrient probes report from your land every 15 minutes.' },
    { icon: <Mic />, t: 'Understands your language', d: 'Recognises questions spoken in Indian languages, in the everyday way farmers talk.' },
    { icon: <Speaker />, t: 'Answers out loud', d: 'Replies are spoken back in the same language the farmer asked in.' },
    { icon: <Globe />, t: 'Your data, your language', d: 'Every reading, alert and piece of advice for your land, shown in your preferred language.' },
  ]
  return (
    <section className="section align-right" id="device" data-section="3">
      <div className="panel">
        <Kicker n="03">The Device</Kicker>
        <h2 className="title" data-split>
          Smart sensors. A <em>familiar</em> voice.
        </h2>
        <p className="body" data-reveal>
          Chiguru is an IoT device that lives on the farm. It connects to sensors in the field, reads the soil, water and
          weather around the clock, and turns that data into simple answers — spoken aloud and shown on screen.
        </p>
        <div className="tech-grid">
          {items.map((it, i) => (
            <article className="tech glass" key={it.t} data-reveal data-delay={i * 0.07}>
              <span className="icon">{it.icon}</span>
              <h3>{it.t}</h3>
              <p>{it.d}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

export function Impact() {
  const stats = [
    { icon: <Globe />, v: 5, suf: '+', t: 'Indian languages, spoken and on screen' },
    { icon: <Sensor />, v: 15, suf: ' min', t: 'between live readings from your land' },
    { icon: <Mic />, v: 24, suf: '/7', t: 'answers to your questions, day or night' },
    { icon: <Leaf />, v: 100, suf: '%', t: 'of your farm’s information in your language' },
  ]
  return (
    <section className="section align-center" id="impact" data-section="4">
      <div className="panel wide">
        <Kicker n="04">Why Chiguru</Kicker>
        <h2 className="title" data-split>
          Farm technology that speaks the farmer’s <em>language.</em>
        </h2>
        <div className="impact-grid">
          {stats.map((s, i) => (
            <div className="impact glass" key={s.t} data-reveal data-delay={i * 0.08}>
              <span className="icon">{s.icon}</span>
              <strong>
                <span data-count={s.v}>0</span>
                {s.suf}
              </strong>
              <p>{s.t}</p>
            </div>
          ))}
        </div>
        <p className="fine" data-reveal>
          Chiguru keeps adding Indian languages — ask us about yours.
        </p>
      </div>
    </section>
  )
}

export function Contact() {
  const [sent, setSent] = useState(false)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setSent(true)
  }
  return (
    <section className="section align-center contact" id="contact" data-section="5">
      <div className="panel wide">
        <Kicker n="05">Grow with us</Kicker>
        <h2 className="title xl" data-split>
          Bring Chiguru to <em>your field.</em>
        </h2>
        <p className="body center" data-reveal>
          Farmers, cooperatives, FPOs and agri partners — get a Chiguru device on your land or run a pilot with your
          community. Tell us which language you speak; we’d love to hear from you.
        </p>
        <form className="signup glass" onSubmit={submit} data-reveal>
          {sent ? (
            <p className="thanks">
              <Leaf width={18} height={18} /> Thank you — we’ll be in touch within two working days.
            </p>
          ) : (
            <>
              <label className="sr-only" htmlFor="email">
                Email address
              </label>
              <input id="email" type="email" required placeholder="you@example.com" autoComplete="email" />
              <button className="btn btn-primary" type="submit">
                Get in touch <Arrow width={18} height={18} />
              </button>
            </>
          )}
        </form>
      </div>

      <footer className="footer glass" data-reveal>
        <div className="foot-brand">
          <span className="brand">
            <LogoMark width={28} height={28} /> <span>Chiguru</span>
          </span>
          <p>An IoT farm assistant that listens, understands and answers in the farmer’s own language.</p>
        </div>
        <div className="foot-cols">
          <div>
            <h4>Explore</h4>
            <a href="#land" onClick={(e) => (e.preventDefault(), scrollToId('land'))}>Your land</a>
            <a href="#voice" onClick={(e) => (e.preventDefault(), scrollToId('voice'))}>Ask Chiguru</a>
            <a href="#device" onClick={(e) => (e.preventDefault(), scrollToId('device'))}>The device</a>
          </div>
          <div>
            <h4>Get started</h4>
            <a href="#contact">Request a demo</a>
            <a href="#contact">Run a pilot</a>
            <a href="#contact">Partner with us</a>
          </div>
          <div>
            <h4>Contact</h4>
            <a href="mailto:hello@chiguru.example">hello@chiguru.example</a>
            <a href="tel:+918000000000">+91 80 0000 0000</a>
          </div>
        </div>
        <div className="foot-base">
          <span>© {new Date().getFullYear()} Chiguru</span>
          <span className="credits">
            3D models: Quaternius (CC0) · Tractor by Poly by Google (CC-BY 3.0) · Textures: Poly Haven (CC0)
          </span>
        </div>
      </footer>
    </section>
  )
}
