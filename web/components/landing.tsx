'use client';
import Link from 'next/link';
import { useState } from 'react';
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Headphones,
  Phone,
  ShieldCheck,
  Sparkles,
  Waypoints,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Brand } from '@/components/brand';
const exchanges = [
  {
    speaker: 'Caller',
    text: '“I’ve been thinking about implants. I’m missing most of my upper teeth.”',
    tags: ['Full arch interest', 'Treatment enquiry'],
  },
  {
    speaker: 'ArcAgent',
    text: '“I can help you take the next step. Are you experiencing any pain at the moment?”',
    tags: ['Situation assessment', 'One question at a time'],
  },
  {
    speaker: 'Caller',
    text: '“Quite a bit. About eight out of ten. I also have dental insurance through work.”',
    tags: ['Pain level · 8', 'Has dental insurance'],
  },
];
const bars = [
  12, 18, 26, 13, 33, 46, 22, 39, 58, 30, 44, 66, 34, 53, 74, 49, 30, 57, 38,
  63, 80, 47, 62, 39, 52, 28, 44, 66, 36, 24, 51, 31, 41, 26, 15, 28, 18, 12,
];
export function Landing() {
  const [step, setStep] = useState(0);
  const exchange = exchanges[step];
  return (
    <>
      <Link className="sr-only focus:not-sr-only" href="#main">
        Skip to content
      </Link>
      <header className="site-nav container">
        <Brand />
        <nav aria-label="Main navigation">
          <Link href="#how-it-works">How it works</Link>
          <Link href="#decisions">Built on evidence</Link>
          <Link href="/workspace" className="inline-flex items-center gap-2">
            Workspace <ArrowUpRight size={16} />
          </Link>
        </nav>
      </header>
      <main id="main">
        <section className="hero container">
          <div>
            <p className="eyebrow text-primary flex items-center gap-2">
              <span className="size-1.5 rounded-full bg-primary" /> Thoughtful
              conversations. Clear next steps.
            </p>
            <h1>
              Every enquiry
              <br />
              deserves a<br />
              <em className="serif">conversation.</em>
            </h1>
            <p className="hero-copy">
              Meet the voice agent that listens, qualifies, and connects dental
              implant enquiries with the right next step. With the context your
              team needs to pick up the conversation.
            </p>
            <div className="hero-actions">
              <Button
                className="large-button"
                nativeButton={false}
                render={<Link href="/demo" />}
              >
                Explore the workspace <ArrowRight size={17} />
              </Button>
              <Link
                className="text-sm inline-flex items-center gap-2"
                href="#how-it-works"
              >
                See how it works <ChevronRight size={16} />
              </Link>
            </div>
            <p className="hero-footnote">
              <ShieldCheck size={15} /> Interactive demo. No patient data. No
              phone call.
            </p>
          </div>
          <div className="hero-theater">
            <div className="theater-top">
              <span className="eyebrow">A conversation, in context</span>
              <span className="rounded-full border border-white/25 px-2.5 py-1">
                Synthetic demo
              </span>
            </div>
            <div className="theater-rule" />
            <div className="theater-person">
              <span className="avatar-ring">
                <Phone size={19} />
              </span>
              <div>
                <p className="text-sm font-medium">An implant enquiry</p>
                <p className="text-xs mt-1 text-[#b9cebd]">
                  Inbound · Qualification
                </p>
              </div>
              <span className="ml-auto text-xs text-[#b9cebd]">
                {String(step + 1).padStart(2, '0')} / 03
              </span>
            </div>
            <div className="waveform" aria-hidden="true">
              {bars.map((height, i) => (
                <span
                  key={i}
                  style={{
                    height: `${height * (step === 1 ? 0.7 : 1)}px`,
                    opacity: i % 4 === 0 ? 0.45 : 1,
                  }}
                />
              ))}
            </div>
            <div aria-live="polite">
              <p className="eyebrow text-[#b9cebd] mb-3">{exchange.speaker}</p>
              <p key={step} className="conversation-line serif">
                {exchange.text}
              </p>
              <div className="signal-chips">
                {exchange.tags.map((tag) => (
                  <span className="signal-chip" key={tag}>
                    {tag}
                  </span>
                ))}
              </div>
            </div>
            <div className="theater-footer">
              <span className="text-xs text-[#b9cebd] inline-flex items-center gap-1.5">
                <Sparkles size={13} /> Context, captured as it happens
              </span>
              <Button
                onClick={() => setStep((step + 1) % exchanges.length)}
                variant="ghost"
                className="text-white hover:bg-white/10 hover:text-white"
              >
                {step === 2 ? 'Start again' : 'Next exchange'}{' '}
                <ArrowRight size={14} />
              </Button>
            </div>
          </div>
        </section>
        <div className="trust-strip container">
          <span className="eyebrow">
            Purpose-built for the first conversation
          </span>
          <div>
            <Headphones /> Inbound voice
          </div>
          <div>
            <Waypoints /> Deterministic routing
          </div>
          <div>
            <ShieldCheck /> Reviewable decisions
          </div>
        </div>
        <section id="how-it-works" className="process-section container">
          <div className="section-head">
            <div>
              <p className="eyebrow text-primary">
                From first hello to next step
              </p>
              <h2>
                A little more understanding.
                <br />
                <span className="serif italic">A lot more context.</span>
              </h2>
            </div>
            <p>
              A structured conversation gives your coordinators something useful
              to work with, before they say their first hello.
            </p>
          </div>
          <div className="process-grid">
            {[
              [
                '01',
                'Listen with intention.',
                'Start with a clear disclosure. Understand the caller’s treatment interest, situation, and concerns.',
              ],
              [
                '02',
                'Find the useful details.',
                'Capture insurance signals, contact preferences, and objections in a consistent lead record.',
              ],
              [
                '03',
                'Make the next step clear.',
                'Route qualified leads to an available coordinator. Offer a callback when a handoff is not the right fit.',
              ],
            ].map(([number, title, text]) => (
              <article className="process-card" key={number}>
                <div className="process-number">
                  {number}
                  <span className="float-right text-muted-foreground">
                    <ArrowUpRight size={19} />
                  </span>
                </div>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>
        <section id="decisions" className="proof-section container">
          <div>
            <p className="eyebrow text-primary">A decision you can explain</p>
            <h2>
              No mystery behind
              <br />
              <span className="serif italic">the handoff.</span>
            </h2>
            <p>
              Every lead score comes from a defined rule table. Open a
              conversation, inspect the facts, and see why the agent chose its
              next step.
            </p>
            <Link
              href="/demo"
              className="inline-flex items-center gap-2 text-sm font-medium mt-7"
            >
              Look inside a conversation <ArrowRight size={16} />
            </Link>
          </div>
          <div className="rule-stack">
            <div className="flex justify-between items-center mb-3">
              <span className="eyebrow text-muted-foreground">
                Example qualification
              </span>
              <span className="text-xs text-muted-foreground">
                Illustrative
              </span>
            </div>
            <div className="rule-row">
              <span>Full arch interest</span>
              <span>+30</span>
            </div>
            <div className="rule-row">
              <span>Pain level of six or higher</span>
              <span>+20</span>
            </div>
            <div className="rule-row">
              <span>Has dental insurance</span>
              <span>+15</span>
            </div>
            <div className="rule-row">
              <span className="inline-flex items-center gap-2">
                <Check size={15} className="text-primary" /> Handoff if
                coordinator available
              </span>
              <span className="text-primary">65 points</span>
            </div>
          </div>
        </section>
      </main>
      <footer className="site-footer container">
        <Brand />
        <p>Built for dental teams. Designed around the conversation.</p>
        <Link
          href="/demo?view=evaluations"
          className="inline-flex gap-2 items-center"
        >
          Explore evaluations <ArrowUpRight size={14} />
        </Link>
      </footer>
    </>
  );
}
