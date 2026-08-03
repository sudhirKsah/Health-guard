import Link from "next/link";

const steps = [
  {
    n: "01",
    title: "Tell us what runs out",
    body: "Add the person, the supply, and how much they use a day. Ordinary words — no product codes.",
  },
  {
    n: "02",
    title: "Approve once, with a passkey",
    body: "Set a spending limit per shop and how often it may be used. One fingerprint. Never again.",
  },
  {
    n: "03",
    title: "We watch, and reorder",
    body: "When stock gets low, Health Guard buys the exact item you approved — and shows you why.",
  },
];

const features = [
  { icon: "◎", title: "One person, one address", body: "Everything ships where that person actually lives.", tone: "mint" },
  { icon: "▣", title: "A limit you set", body: "Per shop, per amount, per cycle. Pause it any time.", tone: "plain" },
  { icon: "✓", title: "Only what you approved", body: "Never a substitute, never a different size.", tone: "plain" },
  { icon: "≡", title: "Every decision in plain English", body: "What it saw, what it chose, what it paid.", tone: "sun" },
];

export default function Home() {
  return (
    <main className="landing">
      <header className="landing-bar">
        <Link className="brand" href="/">
          <span className="brand-mark">H</span>
          <span>Health Guard</span>
        </Link>
        <Link className="button-link compact-cta" href="/auth">Get started</Link>
      </header>

      <section className="hero">
        <p className="eyebrow">Autonomous care, with boundaries</p>
        <h1>Never run out of the things that keep a routine going.</h1>
        <p className="hero-sub">
          Health Guard watches the supplies you declare, buys only the products you approve, and
          spends only inside a limit you set once.
        </p>
        <div className="hero-actions">
          <Link className="button-link" href="/auth">Set up care — it&apos;s free</Link>
          <a className="quiet-link" href="#how">See how it works ↓</a>
        </div>

        <div className="phone-preview" aria-hidden>
          <div className="phone">
            <div className="phone-notch" />
            <div className="phone-screen">
              <div className="pv-greet">
                <span className="pv-avatar">M</span>
                <div><small>Good morning</small><strong>Mum&apos;s supplies</strong></div>
              </div>
              <div className="pv-tile pv-wide">
                <small>Supply level</small>
                <div className="pv-meter"><i style={{ width: "68%" }} /></div>
                <span className="pv-state">Well stocked · 9 days of cover</span>
              </div>
              <div className="pv-row">
                <div className="pv-tile pv-mint"><small>Next check</small><strong>Tue</strong><span>09:40</span></div>
                <div className="pv-tile pv-sun"><small>Limit left</small><strong>₹550</strong><span>this month</span></div>
              </div>
              <div className="pv-tile pv-note"><span className="pv-dot" />Ashwagandha reordered · ₹450</div>
            </div>
          </div>
        </div>
      </section>

      <section className="strip">
        <article><strong>Once</strong><span>You approve, with a passkey</span></article>
        <article><strong>Zero</strong><span>Open cards handed to anyone</span></article>
        <article><strong>Always</strong><span>A reason you can read</span></article>
      </section>

      <section className="band">
        <p className="eyebrow">The problem</p>
        <h2 className="band-title">Remembering shouldn&apos;t be load-bearing.</h2>
        <p className="band-sub">
          For an older adult — or someone caring from another city — reordering strips, swabs and
          supplements is easy to postpone and expensive to forget. The usual fix is handing over a
          card. That shouldn&apos;t be the only option.
        </p>
      </section>

      <section id="how" className="how-section">
        <p className="eyebrow">How it works</p>
        <h2 className="band-title">Three steps, then it&apos;s quiet.</h2>
        <ol className="steps">
          {steps.map((s) => (
            <li key={s.n} className="step">
              <span className="step-n">{s.n}</span>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="feature-section">
        <p className="eyebrow">Built for trust</p>
        <h2 className="band-title">Boundaries you can see.</h2>
        <div className="feature-grid">
          {features.map((f) => (
            <article key={f.title} className={`feature f-${f.tone}`}>
              <span className="feature-icon" aria-hidden>{f.icon}</span>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="cta-band">
        <h2>Set it up once. Then stop worrying about it.</h2>
        <p>Takes about five minutes. You can pause or cancel everything at any time.</p>
        <Link className="button-link cta-big" href="/auth">Create your account</Link>
      </section>

      <footer className="landing-foot">
        <Link className="brand" href="/"><span className="brand-mark">H</span><span>Health Guard</span></Link>
        <small>For recurring over-the-counter supplies. Not medical advice, and never a prescription.</small>
      </footer>
    </main>
  );
}
