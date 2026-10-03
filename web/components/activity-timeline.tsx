'use client';
import { useEffect, useState } from 'react';
import { History, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { read } from '@/lib/client';
import { type ActivityEvent } from '@/lib/group';

type ActivityPage = {
  items: ActivityEvent[];
  next_before: number | null;
  has_more: boolean;
};
const label = (value: string) => value.replaceAll('_', ' ');
export function ActivityTimeline({
  callId,
  demo,
  demoItems,
}: {
  callId: number;
  demo: boolean;
  demoItems: ActivityEvent[];
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ActivityEvent[]>([]);
  const [before, setBefore] = useState<number | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open || demo) return;
    const controller = new AbortController();
    // oxlint-disable-next-line react/react-compiler -- Fetch a bounded activity page on demand.
    setLoading(true);
    setError('');
    void read<ActivityPage>(
      `calls/${callId}/activity?limit=15${before ? `&before=${before}` : ''}`,
      controller.signal,
    )
      .then((page) => {
        if (controller.signal.aborted) return;
        setItems((old) =>
          before === null
            ? page.items
            : [
                ...old,
                ...page.items.filter(
                  (item) => !old.some((known) => known.id === item.id),
                ),
              ],
        );
        setNext(page.next_before);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : 'Activity is unavailable.',
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [callId, demo, open, before, retry]);
  const events = demo ? demoItems : items;
  return (
    <section className="border-t pt-5 mt-6">
      <Button
        variant="ghost"
        className="w-full justify-between px-0"
        aria-expanded={open}
        onClick={() => {
          if (!open) {
            setBefore(null);
            setNext(null);
            setItems([]);
            setError('');
          }
          setOpen(!open);
        }}
      >
        <span className="inline-flex items-center gap-2">
          <History size={16} />
          Staff activity
        </span>
        <ChevronDown size={16} className={open ? 'rotate-180' : ''} />
      </Button>
      {open && (
        <div className="space-y-4 mt-4">
          <p className="text-xs text-muted-foreground">
            {demo
              ? 'Demo activity tracks edits you make during this session.'
              : 'Newest events first. Contact corrections and notes show field names only; private text values are hidden.'}
          </p>
          {error && (
            <div className="rounded-lg border p-3 text-sm">
              <p>{error}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => setRetry((value) => value + 1)}
              >
                Retry activity
              </Button>
            </div>
          )}
          {events.map((event) => (
            <article
              key={event.id}
              className="border-l-2 border-primary/25 pl-4 space-y-2"
            >
              <p className="text-sm font-medium capitalize">
                {label(event.entity)} · {label(event.action)}
              </p>
              <p className="text-xs text-muted-foreground break-all">
                {event.actor} · {new Date(event.created_at).toLocaleString()}
              </p>
              {Object.keys(event.changes).length > 0 && (
                <dl className="text-xs space-y-1">
                  {Object.entries(event.changes).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-3">
                      <dt className="capitalize">{label(key)}</dt>
                      <dd className="break-words text-right">
                        {value === null ? 'Cleared' : String(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              {event.fields_changed.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Fields: {event.fields_changed.map(label).join(', ')}
                </p>
              )}
            </article>
          ))}
          {loading && (
            <output className="block text-sm">Loading activity…</output>
          )}
          {!loading && !error && events.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No staff activity recorded yet.
            </p>
          )}
          {!demo && next !== null && !error && (
            <Button
              size="sm"
              variant="outline"
              disabled={loading}
              onClick={() => setBefore(next)}
            >
              Load older activity
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
