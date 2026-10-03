'use client';
import { useEffect, useState } from 'react';
import {
  Database,
  FileText,
  ShieldCheck,
  Clock3,
  AlertTriangle,
} from 'lucide-react';
import { read } from '@/lib/client';
import { Badge } from '@/components/ui/badge';

type RetentionPreview = {
  checked_at: string;
  retention_days: number;
  before: string;
  preview_limit: number;
  candidate_turns: number;
  candidate_calls: number;
  candidate_text_characters: number;
  has_more: boolean;
};
type StorageReport = {
  database: { available: boolean };
  retention: RetentionPreview | null;
  automation: 'manual_only';
  physical_storage_bytes: null;
};
const example: StorageReport = {
  database: { available: true },
  retention: {
    checked_at: '2026-10-02T12:00:00Z',
    retention_days: 30,
    before: '2026-09-02T12:00:00Z',
    preview_limit: 1000,
    candidate_turns: 48,
    candidate_calls: 6,
    candidate_text_characters: 8240,
    has_more: false,
  },
  automation: 'manual_only',
  physical_storage_bytes: null,
};

export function StorageHealth({
  demo,
  refresh,
}: {
  demo: boolean;
  refresh: number;
}) {
  const [report, setReport] = useState<StorageReport | null>(
    demo ? example : null,
  );
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(!demo);
  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    // oxlint-disable-next-line react/react-compiler -- Synchronize the read-only storage preview.
    setLoading(true);
    setError('');
    void read<StorageReport>('storage', controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setReport(value);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : 'Data health is unavailable. Refresh to try again.',
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [demo, refresh]);
  const retention =
    !error && !loading && report?.database.available ? report.retention : null;
  return (
    <section className="space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <p className="eyebrow">Data health</p>
          <h2 className="text-2xl mt-3">Keep the evidence. Limit the text.</h2>
          <p className="text-muted-foreground mt-3 max-w-2xl">
            Preview expired conversation text while keeping call outcomes, staff
            activity, delivery receipts, and latency measurements.
          </p>
        </div>
        <Badge variant="outline">
          <ShieldCheck size={13} />
          Read-only preview
        </Badge>
      </div>
      {demo && (
        <p className="text-sm rounded-xl border border-amber-200 bg-amber-50 text-amber-950 p-4">
          Illustrative storage figures for the fictional demo. This is not a
          scan of the deployed database.
        </p>
      )}
      {loading ? (
        <output className="block py-6">Checking data health…</output>
      ) : error || !report?.database.available ? (
        <output className="block rounded-xl border border-amber-200 p-4 text-sm">
          <AlertTriangle className="inline mr-2" size={16} />
          {error ||
            'The database preview is unavailable. No zero counts or space estimates are inferred.'}
        </output>
      ) : null}
      <div className="grid sm:grid-cols-3 gap-4">
        {[
          ['Eligible turns', retention?.candidate_turns, FileText],
          ['Calls in preview', retention?.candidate_calls, Database],
          ['Text characters', retention?.candidate_text_characters, Clock3],
        ].map(([title, value, Icon]) => {
          const Glyph = Icon as typeof FileText;
          return (
            <article
              className="rounded-2xl border bg-card p-6"
              key={String(title)}
            >
              <div className="text-sm text-muted-foreground flex justify-between items-center">
                {String(title)}
                <Glyph size={17} />
              </div>
              <p className="text-3xl mt-4 tabular-nums">
                {typeof value === 'number'
                  ? `${retention?.has_more ? '≥ ' : ''}${value.toLocaleString()}`
                  : 'Unavailable'}
              </p>
            </article>
          );
        })}
      </div>
      {retention && (
        <p className="text-sm text-muted-foreground">
          Completed calls older than {retention.retention_days} days, before{' '}
          {new Date(retention.before).toLocaleString()}.{' '}
          {retention.has_more
            ? `This preview is limited to ${retention.preview_limit.toLocaleString()} turns; additional eligible text remains.`
            : 'All eligible turns fit in this bounded preview.'}{' '}
          Character counts describe text content, not disk bytes or guaranteed
          storage savings.
        </p>
      )}
      <div className="grid md:grid-cols-2 gap-5">
        <article className="rounded-2xl border p-6">
          <h3 className="font-medium">Retain operational evidence</h3>
          <p className="text-sm text-muted-foreground leading-relaxed mt-3">
            Cleanup clears expired turn text and records when it was removed.
            Turn timing, lead details, follow-up history, evaluation results,
            and CRM delivery records remain available.
          </p>
        </article>
        <article className="rounded-2xl border p-6">
          <h3 className="font-medium">Manual cleanup, with a preview first</h3>
          <p className="text-sm text-muted-foreground leading-relaxed mt-3">
            No cleanup runs from this page. An authorized operator reviews the
            preview and explicitly runs bounded redaction using the maintenance
            runbook. Backups and vendor copies require their own retention
            process.
          </p>
        </article>
      </div>
    </section>
  );
}
