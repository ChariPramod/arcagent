'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleHelp,
  Database,
  FileCheck2,
  Headphones,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Unplug,
  Waypoints,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion';
import { DotPattern } from '@/components/magicui/dot-pattern';
import { read } from '@/lib/client';
import {
  demoOperations,
  parseOperations,
  recoveryGuides,
  reportOperations,
} from '@/lib/operations';
import type { Check as CheckData, OperationsData } from '@/lib/operations';

type Mode = 'setup' | 'ready' | 'outage';
export function Operations({
  demo,
  onReviewCall,
}: {
  demo: boolean;
  onReviewCall: (id: number) => void;
}) {
  const [mode, setMode] = useState<Mode>('setup');
  const [live, setLive] = useState<OperationsData | null>(null);
  const [loading, setLoading] = useState(!demo);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [report, setReport] = useState('');
  const reduce = useReducedMotion();
  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    // oxlint-disable-next-line react/react-compiler -- Reset asynchronous request state before refresh.
    setLoading(true);
    setError('');
    setLive(null);
    setReport('');
    read<unknown>('operations', controller.signal)
      .then(parseOperations)
      .then((data) => {
        if (!controller.signal.aborted) {
          setLive(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError('The operations check could not be completed.');
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [demo, refresh]);
  const data = demo ? demoOperations(mode) : live;
  const checks = data?.readiness.checks ?? [];
  const configured = checks.filter((c) => c.status === 'ready').length;
  const required = checks.filter((c) => c.status !== 'unknown').length;
  const needsAttention = checks.filter((c) => c.status === 'blocked').length;
  const heading = loading
    ? 'Checking your workspace'
    : error
      ? 'Connection needs attention'
      : data?.readiness.ready
        ? 'Configuration in place'
        : 'A few things need attention';
  function saveReport() {
    if (data) setReport(reportOperations(data));
  }
  return (
    <div className="ops-workspace">
      <div className="ops-heading">
        <div>
          <p className="eyebrow text-primary">WORKSPACE / OPERATIONS</p>
          <h1>
            Ready for the next <span className="serif italic">hello.</span>
          </h1>
          <p className="text-muted-foreground mt-3">
            Check your setup. Review interrupted calls. Find the next step.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={saveReport}
            disabled={!data || loading}
          >
            <ArrowDownToLine size={16} />
            View report
          </Button>
          <Button
            onClick={() => {
              setRefresh((v) => v + 1);
              setReport('');
            }}
            disabled={loading || demo}
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
          </Button>
        </div>
      </div>
      {demo && (
        <div
          className="ops-scenarios"
          aria-label="Explore fictional operating states"
        >
          <span>Try a scenario</span>
          <div className="flex flex-wrap gap-1">
            {(
              [
                ['setup', 'Needs setup'],
                ['ready', 'Configured'],
                ['outage', 'Database offline'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                aria-pressed={mode === value}
                onClick={() => {
                  setMode(value);
                  setReport('');
                }}
                className={mode === value ? 'selected' : ''}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="ops-fiction">
            Fictional checks · no services contacted
          </span>
        </div>
      )}
      <motion.section
        initial={false}
        animate={{ opacity: 1 }}
        transition={{ duration: reduce ? 0 : 0.2 }}
        className="ops-status"
        aria-labelledby="ops-status-heading"
      >
        <DotPattern className="ops-dots" />
        <div className="ops-status-copy">
          <Badge className="ops-status-badge">
            <ShieldCheck size={14} />
            {demo ? 'SIMULATED CONFIGURATION' : 'CONFIGURATION CHECK'}
          </Badge>
          <h2 id="ops-status-heading">{heading}</h2>
          <p>
            {error
              ? 'Live status is unavailable. Retry the check or use the recovery guides below.'
              : loading
                ? 'Reading configuration and recent call records.'
                : data?.readiness.ready
                  ? 'Required configuration checks passed. Verify a controlled live call before making readiness claims.'
                  : `${needsAttention} configuration ${needsAttention === 1 ? 'check needs' : 'checks need'} attention. Resolve the items below before a controlled call.`}
          </p>
          <div className="ops-status-meta">
            <span>
              <span className="ops-pulse" />{' '}
              {error
                ? 'Status unknown'
                : loading
                  ? 'Checking'
                  : demo
                    ? 'Demo snapshot'
                    : `Checked ${new Date(data?.checked_at ?? '').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`}
            </span>
            <span>Live call performance unverified</span>
          </div>
        </div>
        <figure
          className="ops-ring"
          aria-label={
            data
              ? `${configured} of ${required} required configuration checks passed`
              : 'Configuration status unavailable'
          }
        >
          <svg viewBox="0 0 120 120" aria-hidden="true">
            <circle cx="60" cy="60" r="51" className="ring-track" />
            <motion.circle
              cx="60"
              cy="60"
              r="51"
              className="ring-value"
              pathLength="100"
              initial={false}
              animate={{
                strokeDasharray: `${required ? (configured / required) * 100 : 0} 100`,
              }}
              transition={{ duration: reduce ? 0 : 0.5 }}
            />
          </svg>
          <div>
            <strong>{data ? `${configured}/${required}` : '—'}</strong>
            <span>checks passed</span>
          </div>
        </figure>
      </motion.section>
      {error && (
        <div className="ops-error" role="alert">
          <Unplug size={22} />
          <div>
            <strong>{error}</strong>
            <p>
              Previous status has been cleared. Sample records never replace a
              failed live response.
            </p>
          </div>
          <Button variant="outline" onClick={() => setRefresh((v) => v + 1)}>
            Try again
          </Button>
          <Link href="/demo?view=operations" className="underline text-sm">
            Explore demo
          </Link>
        </div>
      )}
      <div
        className="ops-metrics"
        aria-label="Call activity in the last twenty-four hours"
      >
        {[
          {
            label: 'Recent calls',
            value: data?.summary?.recent_calls,
            icon: Headphones,
            note: 'Received in the last 24 hours',
          },
          {
            label: 'Ended early',
            value: data?.summary?.abandoned_calls,
            icon: Activity,
            note: 'Abandoned conversations',
          },
          {
            label: 'Unfinished records',
            value: data?.summary?.incomplete_calls,
            icon: Waypoints,
            note: 'Includes calls still in progress',
          },
        ].map((item) => (
          <div className="ops-stat" key={item.label}>
            <div className="ops-stat-label">
              <span>{item.label}</span>
              <item.icon size={18} />
            </div>
            {loading ? (
              <Skeleton className="h-10 w-16 my-3" />
            ) : (
              <strong>{item.value ?? '—'}</strong>
            )}
            <p>
              {data?.summary
                ? item.note
                : 'Unavailable until records can be read'}
            </p>
          </div>
        ))}
      </div>
      <div className="ops-grid">
        <section className="ops-card">
          <div className="ops-card-heading">
            <div>
              <p className="eyebrow">SYSTEM CHECKS</p>
              <h2>Everything in its place.</h2>
            </div>
            <FileCheck2 size={22} className="text-primary" />
          </div>
          {loading ? (
            <div className="space-y-4 p-6">
              {[0, 1, 2].map((n) => (
                <Skeleton key={n} className="h-16" />
              ))}
            </div>
          ) : checks.length ? (
            <div>
              {checks.map((check) => (
                <CheckRow key={check.id} check={check} />
              ))}
            </div>
          ) : (
            <div className="p-6 text-muted-foreground">
              Refresh to retrieve configuration checks.
            </div>
          )}
          {!!data?.readiness.issues.length && (
            <div className="ops-findings">
              <strong>Prompt findings · {data.readiness.prompt_version}</strong>
              <div>
                {data.readiness.issues.map((issue) => (
                  <span key={issue.name}>
                    {issue.name.replaceAll('_', ' ')}{' '}
                    <em>{issue.reason.replaceAll('_', ' ')}</em>
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>
        <div className="space-y-5">
          <section className="ops-card">
            <div className="ops-card-heading">
              <div>
                <p className="eyebrow">REVIEW QUEUE</p>
                <h2>Calls to look into.</h2>
              </div>
              <Badge variant="secondary">Last 24h</Badge>
            </div>
            <p className="px-6 text-sm text-muted-foreground">
              Recent abandoned or unfinished records. An active call can appear
              here.
            </p>
            {loading ? (
              <div className="p-6">
                <Skeleton className="h-28" />
              </div>
            ) : data?.database.available ? (
              <div className="p-3">
                {data.recent_failures.length ? (
                  data.recent_failures.map((call) => (
                    <div key={call.id} className="ops-failure">
                      <span className="ops-call-icon">
                        <Headphones size={18} />
                      </span>
                      <div className="flex-1">
                        <strong>Call #{call.id}</strong>
                        <p>
                          {call.outcome === 'abandoned'
                            ? 'Ended early'
                            : 'Unfinished record'}{' '}
                          ·{' '}
                          {call.started_at
                            ? new Date(call.started_at).toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                              })
                            : 'Time unavailable'}
                        </p>
                      </div>
                      {demo ? (
                        <Badge variant="outline">Example</Badge>
                      ) : (
                        <Button
                          variant="ghost"
                          aria-label={`Review call ${call.id}`}
                          onClick={() => onReviewCall(call.id)}
                        >
                          <ArrowRight size={17} />
                        </Button>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="ops-empty">
                    <CheckCircle2 size={24} />
                    <p>No matching records in this window.</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="ops-empty">
                <Database size={24} />
                <p>Queue unavailable while records cannot be read.</p>
              </div>
            )}
          </section>
          <section className="ops-card ops-playbook">
            <div className="ops-card-heading">
              <div>
                <p className="eyebrow">WHEN SOMETHING BREAKS</p>
                <h2>A clear next step.</h2>
              </div>
              <CircleHelp size={22} />
            </div>
            <Accordion>
              {recoveryGuides.map((guide) => (
                <AccordionItem key={guide.id} value={guide.id}>
                  <AccordionTrigger>{guide.title}</AccordionTrigger>
                  <AccordionContent>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {guide.text}
                    </p>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </section>
        </div>
      </div>
      {report && (
        <section className="ops-card p-6" aria-label="Operational report">
          <div className="flex items-center justify-between gap-4 mb-4">
            <h2 className="text-lg font-medium">Your configuration report</h2>
            <Button variant="ghost" onClick={() => setReport('')}>
              Close
            </Button>
          </div>
          <p className="text-sm text-muted-foreground mb-3">
            Select and copy this report for your engineering notes. It contains
            no conversation content.
          </p>
          <textarea
            readOnly
            aria-label="Copyable configuration report"
            value={report}
            onFocus={(e) => e.currentTarget.select()}
            className="w-full min-h-64 rounded-lg border bg-muted/30 p-4 font-mono text-sm"
          />
        </section>
      )}
      <footer className="ops-footer">
        <ShieldCheck size={16} />
        <span>
          Read-only workspace. These checks never place calls, send messages, or
          retry routing.
        </span>
      </footer>
    </div>
  );
}
function CheckRow({ check }: { check: CheckData }) {
  const Icon =
    check.status === 'ready'
      ? Check
      : check.status === 'blocked'
        ? TriangleAlert
        : CircleHelp;
  return (
    <div className="ops-check">
      <span className={`ops-check-icon ${check.status}`}>
        <Icon size={18} />
      </span>
      <div>
        <h3>{check.label}</h3>
        <p>{check.detail}</p>
      </div>
      <Badge variant="outline" className={`ops-check-badge ${check.status}`}>
        {check.status === 'ready'
          ? 'Configured'
          : check.status === 'blocked'
            ? 'Needs attention'
            : 'Not verified'}
      </Badge>
    </div>
  );
}
