'use client';
import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  CheckCheck,
  FlaskConical,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { Empty, EmptyDescription, EmptyTitle } from '@/components/ui/empty';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { Choice } from '@/components/choice';
import { demoComparison, demoEvals } from '@/lib/demo';
import { read } from '@/lib/client';
import type {
  Comparison,
  EvalDetail,
  EvalResult,
  EvalRun,
  Page,
} from '@/lib/domain';
import { Metric } from '@/components/metric';
import { date, display, label, percent } from '@/lib/domain';
export function Evaluations({ demo }: { demo: boolean }) {
  const [runs, setRuns] = useState<EvalRun[]>(
    demo ? [...demoEvals].reverse() : [],
  );
  const [selected, setSelected] = useState(demo ? 2 : 0);
  const [detail, setDetail] = useState<EvalDetail | null>(
    demo ? demoEvals[1] : null,
  );
  const [scenario, setScenario] = useState<EvalResult | null>(null);
  const [before, setBefore] = useState(demo ? 1 : 0);
  const [after, setAfter] = useState(demo ? 2 : 0);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(!demo);
  const [comparing, setComparing] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (demo) return;
    let active = true;
    // oxlint-disable-next-line react/react-compiler -- Reset stale request state before fetching.
    setLoading(true);
    read<Page<EvalRun>>('evals?limit=100')
      .then((data) => {
        if (active) {
          setRuns(data.items);
          setSelected(data.items[0]?.id ?? 0);
          setAfter(data.items[0]?.id ?? 0);
          setBefore(data.items[1]?.id ?? 0);
          setError('');
          setLoading(false);
        }
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [demo, retry]);
  useEffect(() => {
    if (!selected) return;
    if (demo) {
      // oxlint-disable-next-line react/react-compiler -- Synchronize the selected record before async loading.
      setDetail(demoEvals.find((r) => r.id === selected) ?? null);
      return;
    }
    let active = true;
    setDetail(null);
    read<EvalDetail>(`evals/${selected}`)
      .then((data) => {
        if (active) {
          setDetail(data);
          setError('');
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [selected, demo, retry]);
  async function compare() {
    setComparing(true);
    setError('');
    try {
      setComparison(
        demo
          ? demoComparison(before, after)
          : await read<Comparison>(`compare?before=${before}&after=${after}`),
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Comparison could not be loaded.',
      );
    } finally {
      setComparing(false);
    }
  }
  const chart = detail
    ? Array.from(new Set(detail.items.map((r) => r.group))).map((group) => {
        const rows = detail.items.filter((r) => r.group === group);
        return {
          group: label(group),
          passed: rows.filter((r) => r.passed).length,
          failed: rows.filter((r) => !r.passed).length,
        };
      })
    : [];
  return (
    <>
      <div className="workspace-heading">
        <div>
          <p className="eyebrow text-primary">Evidence before iteration</p>
          <h1>
            Better conversations,
            <br />
            <span className="serif italic">measured thoughtfully.</span>
          </h1>
        </div>
        <Badge variant="outline">
          <FlaskConical size={13} />{' '}
          {demo ? 'Illustrative evaluations' : 'Evaluation results'}
        </Badge>
      </div>
      {error && (
        <div role="alert" className="error-panel">
          {error}
          <Button variant="outline" onClick={() => setRetry(retry + 1)}>
            Try again
          </Button>
        </div>
      )}
      {loading ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : !runs.length ? (
        <Empty className="empty-panel">
          <FlaskConical />
          <EmptyTitle>No evaluation runs yet</EmptyTitle>
          <EmptyDescription>
            Saved runs will appear here after your team runs the evaluation
            harness.
          </EmptyDescription>
        </Empty>
      ) : (
        <Tabs defaultValue="runs" className="mt-6">
          <TabsList variant="line" className="mb-6">
            <TabsTrigger value="runs">Run explorer</TabsTrigger>
            <TabsTrigger value="compare">Compare iterations</TabsTrigger>
          </TabsList>
          <TabsContent value="runs">
            <div className="flex justify-between items-center mb-5 gap-3 flex-wrap">
              <h2 className="text-lg font-medium">A closer look at each run</h2>
              <Choice
                label="Evaluation run"
                value={String(selected)}
                onChange={(v) => setSelected(Number(v))}
                options={runs.map((r) => ({
                  value: String(r.id),
                  label: r.name,
                }))}
              />
            </div>
            {detail ? (
              <>
                <div className="metric-grid">
                  <Metric
                    name="Outcome pass rate"
                    value={percent(detail.pass_rate)}
                    note={`${detail.results} recorded results`}
                  />
                  <Metric
                    name="Field accuracy"
                    value={percent(detail.field_accuracy)}
                    note="Expected fields matched"
                  />
                  <Metric
                    name="Handoff recall"
                    value={percent(detail.handoff_recall)}
                    note="Expected handoffs completed"
                  />
                  <Metric
                    name="Flaky scenarios"
                    value={String(detail.flaky.length)}
                    note="Changed verdict across repeats"
                  />
                </div>
                <div className="eval-middle">
                  <div className="surface-panel">
                    <div className="pane-title">
                      <h3 className="text-sm font-semibold">
                        Results by category
                      </h3>
                      <span className="text-xs text-muted-foreground">
                        Scenario results
                      </span>
                    </div>
                    <ChartContainer
                      config={{
                        passed: { label: 'Passed', color: '#176452' },
                        failed: { label: 'Failed', color: '#c4a477' },
                      }}
                      className="h-52 w-full"
                    >
                      <BarChart data={chart} accessibilityLayer>
                        <CartesianGrid vertical={false} />
                        <XAxis
                          dataKey="group"
                          tickLine={false}
                          axisLine={false}
                          fontSize={12}
                        />
                        <YAxis
                          allowDecimals={false}
                          tickLine={false}
                          axisLine={false}
                          width={28}
                        />
                        <ChartTooltip content={<ChartTooltipContent />} />
                        <Bar
                          dataKey="passed"
                          fill="var(--color-passed)"
                          radius={[4, 4, 0, 0]}
                          maxBarSize={38}
                        />
                        <Bar
                          dataKey="failed"
                          fill="var(--color-failed)"
                          radius={[4, 4, 0, 0]}
                          maxBarSize={38}
                        />
                      </BarChart>
                    </ChartContainer>
                  </div>
                  <div className="surface-panel run-context">
                    <p className="eyebrow text-muted-foreground">Run context</p>
                    <h3 className="text-xl mt-4 mb-5">{detail.name}</h3>
                    <dl>
                      {[
                        ['Prompts', detail.prompt_version],
                        ['Suite', label(detail.suite)],
                        ['Tier', label(detail.tier)],
                        ['Created', `${date(detail.created_at)} UTC`],
                        ['Source', detail.git_sha.slice(0, 12)],
                      ].map(([key, value]) => (
                        <div key={key}>
                          <dt>{key}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                </div>
                <div className="table-panel">
                  <div className="pane-title">
                    <h3 className="font-medium">Scenario review</h3>
                    <span className="text-xs text-muted-foreground">
                      {detail.scenarios} scenarios
                    </span>
                  </div>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Scenario</TableHead>
                        <TableHead>Category</TableHead>
                        <TableHead>Repeat</TableHead>
                        <TableHead>Accuracy</TableHead>
                        <TableHead>Result</TableHead>
                        <TableHead>
                          <span className="sr-only">Review</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.items.map((row) => (
                        <TableRow key={row.id}>
                          <TableCell>
                            <Button
                              className="text-left justify-start h-auto p-0 whitespace-normal"
                              variant="link"
                              onClick={() => setScenario(row)}
                            >
                              {label(row.scenario_id)}
                            </Button>
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {label(row.group)}
                          </TableCell>
                          <TableCell>{row.repeat + 1}</TableCell>
                          <TableCell>{percent(row.field_accuracy)}</TableCell>
                          <TableCell>
                            <Badge
                              variant="secondary"
                              className={
                                row.passed
                                  ? 'outcome-badge handoff'
                                  : 'outcome-badge'
                              }
                            >
                              {row.passed ? 'Passed' : 'Needs review'}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => setScenario(row)}
                              aria-label={`Review ${label(row.scenario_id)}`}
                            >
                              <ArrowRight />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            ) : (
              <Skeleton className="h-96" />
            )}
          </TabsContent>
          <TabsContent value="compare">
            <div className="surface-panel">
              <p className="eyebrow text-primary mb-4">
                One change. Both sides of the story.
              </p>
              <h2 className="text-2xl tracking-tight mb-3">
                Did the iteration help?
              </h2>
              <p className="text-sm text-muted-foreground max-w-xl leading-relaxed mb-6">
                Compare the same benchmark across runs. A higher overall pass
                rate can still hide missed handoffs. Missing evidence gets its
                own verdict.
              </p>
              <div className="compare-controls">
                <div>
                  <div className="text-xs text-muted-foreground block mb-2">
                    Baseline
                  </div>
                  <Choice
                    label="Baseline run"
                    value={String(before)}
                    onChange={(v) => {
                      setBefore(Number(v));
                      setComparison(null);
                    }}
                    options={runs.map((r) => ({
                      value: String(r.id),
                      label: r.name,
                    }))}
                  />
                </div>
                <ArrowRight size={18} />
                <div>
                  <div className="text-xs text-muted-foreground block mb-2">
                    Candidate
                  </div>
                  <Choice
                    label="Candidate run"
                    value={String(after)}
                    onChange={(v) => {
                      setAfter(Number(v));
                      setComparison(null);
                    }}
                    options={runs.map((r) => ({
                      value: String(r.id),
                      label: r.name,
                    }))}
                  />
                </div>
                <Button
                  className="h-10"
                  disabled={!before || !after || before === after || comparing}
                  onClick={compare}
                >
                  {comparing ? 'Comparing…' : 'Compare runs'}
                </Button>
              </div>
              {before === after && (
                <p className="text-sm text-muted-foreground mt-3">
                  Select two different runs to compare.
                </p>
              )}
            </div>
            {comparison && (
              <div className={`comparison-result ${comparison.status}`}>
                <div className="flex items-start gap-3">
                  {comparison.status === 'clear' ? (
                    <CheckCheck size={22} />
                  ) : (
                    <AlertTriangle size={22} />
                  )}
                  <div>
                    <h3 className="font-medium text-lg">
                      {comparison.status === 'invalid'
                        ? 'Not enough comparable evidence'
                        : comparison.status === 'regression'
                          ? 'A guarded metric regressed'
                          : 'No guarded metric regressed'}
                    </h3>
                    <p className="text-sm mt-2 leading-relaxed">
                      {comparison.reason ??
                        (comparison.status === 'regression'
                          ? 'Review the missed handoffs before accepting this iteration.'
                          : 'The recorded benchmark is comparable and the configured guards did not regress.')}
                    </p>
                  </div>
                </div>
                {comparison.metrics.length > 0 && (
                  <Table className="mt-5">
                    <TableHeader>
                      <TableRow>
                        <TableHead>Metric / category</TableHead>
                        <TableHead>Before</TableHead>
                        <TableHead>After</TableHead>
                        <TableHead>Change</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {comparison.metrics.map((metric) => (
                        <TableRow key={`${metric.group}-${metric.name}`}>
                          <TableCell>
                            {label(metric.name)}
                            <span className="block text-xs text-muted-foreground mt-1">
                              {label(metric.group)}
                              {metric.guarded ? ' · Guarded' : ''}
                            </span>
                          </TableCell>
                          <TableCell>{percent(metric.before)}</TableCell>
                          <TableCell>{percent(metric.after)}</TableCell>
                          <TableCell
                            className={
                              metric.delta < 0
                                ? 'text-destructive'
                                : 'text-primary'
                            }
                          >
                            {metric.delta > 0 ? '+' : ''}
                            {Math.round(metric.delta * 100)} pp{' '}
                            {metric.delta < 0 && (
                              <ArrowDownRight className="inline" size={14} />
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>
            )}
          </TabsContent>
        </Tabs>
      )}
      <Sheet
        open={!!scenario}
        onOpenChange={(open) => {
          if (!open) setScenario(null);
        }}
      >
        <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
          <SheetHeader className="p-7 border-b">
            <SheetTitle>
              {scenario ? label(scenario.scenario_id) : 'Scenario review'}
            </SheetTitle>
            <SheetDescription>
              Expected facts, actual extraction, and the conversation that
              produced them.
            </SheetDescription>
          </SheetHeader>
          {scenario && (
            <div className="p-7">
              <Badge variant="secondary" className="mb-5">
                {scenario.passed ? 'Passed' : 'Needs review'} · Repeat{' '}
                {scenario.repeat + 1}
              </Badge>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Field</TableHead>
                    <TableHead>Expected</TableHead>
                    <TableHead>Actual</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Array.from(
                    new Set([
                      ...Object.keys(scenario.expected ?? {}),
                      ...Object.keys(scenario.actual ?? {}),
                    ]),
                  ).map((key) => (
                    <TableRow key={key}>
                      <TableCell>{label(key)}</TableCell>
                      <TableCell>{display(scenario.expected?.[key])}</TableCell>
                      <TableCell>{display(scenario.actual?.[key])}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <h3 className="text-lg mt-8 mb-5">Conversation</h3>
              {scenario.transcript?.length ? (
                scenario.transcript.map((turn, i) => (
                  <div className="mb-6" key={i}>
                    <p className="eyebrow text-muted-foreground mb-2">
                      {turn.speaker}
                    </p>
                    <p className="leading-relaxed text-sm whitespace-pre-wrap">
                      {turn.text}
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-muted-foreground text-sm">
                  No transcript was recorded for this result.
                </p>
              )}
              {scenario.notes && (
                <p className="error-panel">{scenario.notes}</p>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
