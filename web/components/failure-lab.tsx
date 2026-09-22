'use client';
import { useEffect, useState } from 'react';
import { FlaskConical, Play, CheckCircle2, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { read, write } from '@/lib/client';
import examples from '@/lib/lab-examples.json';

type Run = {
  scenario_id: string;
  passed: boolean;
  events: { at_ms: number; type: string }[];
  actions: { at_ms: number; type: string }[];
  assertions: {
    name: string;
    passed: boolean;
    expected: unknown;
    actual: unknown;
  }[];
  metrics: {
    duration_ms: number;
    action_count: number;
    score: number | null;
    route: string | null;
  };
  config: Record<string, number>;
};
type Comparison = {
  simulated: boolean;
  baseline: Run;
  candidate: Run;
  changes: { field: string; before: unknown; after: unknown }[];
};
export function FailureLab({ demo }: { demo: boolean }) {
  const [catalog, setCatalog] = useState(examples.items);
  const [scenario, setScenario] = useState(examples.items[0].id);
  const [result, setResult] = useState<Comparison | null>(
    demo ? (Object.values(examples.examples)[0] as Comparison) : null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    read<{ items: typeof catalog }>('lab/scenarios', controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setCatalog(data.items);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            'The scenario catalog could not be loaded. Reconnect before running experiments.',
          );
      });
    return () => controller.abort();
  }, [demo, reload]);
  async function run(form: HTMLFormElement) {
    const data = new FormData(form);
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const response = await write<Comparison>('lab/replay', {
        scenario_id: scenario,
        candidate_config: {
          vendor_timeout_ms: Number(data.get('vendor_timeout_ms')),
          transcript_timeout_ms: Number(data.get('transcript_timeout_ms')),
          handoff_threshold: Number(data.get('handoff_threshold')),
        },
      });
      if (
        response.simulated !== true ||
        !response.baseline ||
        !response.candidate
      )
        throw Error('Invalid experiment response');
      setResult(response);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Experiment unavailable. Try again.',
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="workbench">
      <header className="workbench-heading">
        <div>
          <p className="eyebrow text-primary">FAILURE & COUNTERFACTUAL LAB</p>
          <h1>Make failure repeatable.</h1>
          <p>
            Compare a fixed scenario against a changed policy, before touching
            live calls.
          </p>
        </div>
        <Badge variant="outline">
          <FlaskConical size={14} /> Synthetic policy model
        </Badge>
      </header>
      <p className="lab-notice">
        No calls, messages, vendor requests, or production changes. Timing here
        is simulated. These checks complement the production integration tests;
        they do not measure live audio performance.
      </p>
      <div className="workbench-grid lab-layout">
        <section className="workbench-card">
          <h2 className="mb-5">Choose the failure</h2>
          <label className="field-label">
            Scenario
            <select
              className="workbench-input"
              disabled={busy}
              value={scenario}
              onChange={(e) => {
                setScenario(e.target.value);
                setResult(
                  demo
                    ? (examples.examples as Record<string, Comparison>)[
                        e.target.value
                      ]
                    : null,
                );
              }}
            >
              {catalog.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <p className="text-sm text-muted-foreground mb-6">
            {catalog.find((item) => item.id === scenario)?.description}
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(e.currentTarget);
            }}
          >
            <fieldset disabled={demo || busy}>
              <label className="field-label">
                Vendor timeout (ms)
                <input
                  className="workbench-input"
                  name="vendor_timeout_ms"
                  type="number"
                  defaultValue={2000}
                  min={100}
                  max={30000}
                  required
                />
              </label>
              <label className="field-label">
                Transcript timeout (ms)
                <input
                  className="workbench-input"
                  name="transcript_timeout_ms"
                  type="number"
                  defaultValue={4000}
                  min={100}
                  max={10000}
                  required
                />
              </label>
              <label className="field-label">
                Handoff threshold
                <input
                  className="workbench-input"
                  name="handoff_threshold"
                  type="number"
                  defaultValue={100}
                  min={0}
                  max={100}
                  required
                />
              </label>
              <Button type="submit" disabled={demo || busy}>
                <Play size={15} />
                {busy ? 'Running…' : 'Compare with baseline'}
              </Button>
            </fieldset>
          </form>
          {demo && (
            <p className="text-sm mt-4 text-muted-foreground">
              Showing saved synthetic comparisons. Connect your workspace to run
              custom configurations.
            </p>
          )}
          {error && (
            <div role="alert" className="error-panel mt-4">
              <div>
                <p>{error}</p>
                <Button
                  variant="outline"
                  className="mt-3"
                  onClick={() => {
                    setError('');
                    setReload((v) => v + 1);
                  }}
                >
                  Reload catalog
                </Button>
              </div>
            </div>
          )}
        </section>
        <section>
          {!result ? (
            <div className="workbench-card min-h-80 flex flex-col justify-center">
              <FlaskConical className="text-primary mb-4" size={28} />
              <h2>
                {busy ? 'Replaying the scenario…' : 'A controlled comparison'}
              </h2>
              <p className="text-muted-foreground mt-3">
                Run a scenario to see its timeline, fallback actions, and
                independently fixed expectations. A changed result can be a
                tradeoff or a regression; inspect the assertion before deciding.
              </p>
            </div>
          ) : (
            <>
              <div className="grid sm:grid-cols-2 gap-4">
                {(
                  [
                    ['Baseline', result.baseline],
                    ['Candidate', result.candidate],
                  ] as const
                ).map(([title, item]) => (
                  <article className="workbench-card" key={title}>
                    <div className="flex justify-between items-center">
                      <h2>{title}</h2>
                      {item.passed ? (
                        <CheckCircle2 className="text-primary" size={20} />
                      ) : (
                        <TriangleAlert className="text-destructive" size={20} />
                      )}
                    </div>
                    <p className="text-sm mt-3">
                      {item.passed
                        ? 'Matches fixture expectations'
                        : 'Differs from fixture expectations'}
                    </p>
                    <dl className="lab-metrics">
                      <div>
                        <dt>Simulated duration</dt>
                        <dd>{item.metrics.duration_ms} ms</dd>
                      </div>
                      <div>
                        <dt>Policy actions</dt>
                        <dd>{item.metrics.action_count}</dd>
                      </div>
                      <div>
                        <dt>Routing decision</dt>
                        <dd>{item.metrics.route ?? 'Not applicable'}</dd>
                      </div>
                    </dl>
                    <details className="text-sm mt-4">
                      <summary className="cursor-pointer">
                        Configuration
                      </summary>
                      <pre className="lab-code">
                        {JSON.stringify(item.config, null, 2)}
                      </pre>
                    </details>
                    <ol className="lab-timeline mt-6">
                      {item.actions.map((action, index) => (
                        <li key={index}>
                          <span>{action.at_ms} ms</span>
                          <strong>{action.type.replaceAll('_', ' ')}</strong>
                        </li>
                      ))}
                    </ol>
                  </article>
                ))}
              </div>
              <article className="workbench-card mt-4">
                <h2 className="mb-4">What changed?</h2>
                {result.changes.length ? (
                  result.changes.map((change) => (
                    <details key={change.field} className="py-3 border-b">
                      <summary className="cursor-pointer text-sm font-medium">
                        {change.field.replaceAll('_', ' ')}
                      </summary>
                      <div className="grid sm:grid-cols-2 gap-3">
                        <pre className="lab-code">
                          {JSON.stringify(change.before, null, 2)}
                        </pre>
                        <pre className="lab-code">
                          {JSON.stringify(change.after, null, 2)}
                        </pre>
                      </div>
                    </details>
                  ))
                ) : (
                  <p>No differences for this scenario.</p>
                )}
                <h3 className="font-medium mt-6 mb-4">Candidate assertions</h3>
                {result.candidate.assertions.map((assertion) => (
                  <div key={assertion.name} className="py-3 border-b">
                    <div className="flex justify-between gap-3 text-sm">
                      <span>{assertion.name.replaceAll('_', ' ')}</span>
                      <Badge
                        variant={assertion.passed ? 'secondary' : 'destructive'}
                      >
                        {assertion.passed ? 'Pass' : 'Mismatch'}
                      </Badge>
                    </div>
                    <details className="text-xs mt-2">
                      <summary className="cursor-pointer">
                        Expected and actual
                      </summary>
                      <pre className="lab-code">
                        {JSON.stringify(
                          {
                            expected: assertion.expected,
                            actual: assertion.actual,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </div>
                ))}
              </article>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
