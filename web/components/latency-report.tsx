'use client';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { read } from '@/lib/client';

type Report = {
  stages: {
    key: string;
    label: string;
    description: string;
    samples: number;
    eligible_turns: number;
    coverage: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    missing: number;
    invalid: number;
  }[];
  caveats: string[];
};
export function LatencyReport({ callId }: { callId: number }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    read<Report>(`calls/${callId}/latency`, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setReport(data);
          setError(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setReport(null);
          setError(true);
        }
      });
    return () => controller.abort();
  }, [callId, refresh]);
  if (error)
    return (
      <div role="alert" className="lab-notice">
        Latency summary unavailable. The stored turn values remain below.{' '}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setRefresh((v) => v + 1)}
        >
          Retry summary
        </Button>
      </div>
    );
  if (!report)
    return (
      <output className="text-sm mb-6">Loading measurement coverage…</output>
    );
  return (
    <section className="mb-8">
      <h3 className="text-lg font-medium mb-4">Measurement coverage</h3>
      <div className="grid sm:grid-cols-2 gap-3">
        {report.stages.map((stage) => (
          <article className="workbench-card !p-4" key={stage.key}>
            <h4 className="text-sm font-medium">{stage.label}</h4>
            <p className="text-xs text-muted-foreground mt-2">
              {stage.description}
            </p>
            <p className="mt-4 text-sm">
              p50{' '}
              <strong>
                {stage.p50_ms === null ? 'Unavailable' : `${stage.p50_ms} ms`}
              </strong>{' '}
              · p95{' '}
              <strong>
                {stage.p95_ms === null ? 'Unavailable' : `${stage.p95_ms} ms`}
              </strong>
            </p>
            <p className="text-xs mt-3">
              {stage.samples}/{stage.eligible_turns} eligible turns measured ·{' '}
              {stage.missing} missing · {stage.invalid} invalid
            </p>
          </article>
        ))}
      </div>
      <ul className="list-disc pl-5 text-xs text-muted-foreground space-y-2 mt-4">
        {report.caveats.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </section>
  );
}
