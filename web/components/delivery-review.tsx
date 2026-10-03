'use client';
import { useEffect, useRef, useState } from 'react';
import { X, ClipboardCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { read, write } from '@/lib/client';
import { REVIEW_LABELS, type Delivery, type DeliveryReview } from '@/lib/group';

export function DeliveryReviewDialog({
  entry,
  demo,
  onClose,
  onReviewed,
}: {
  entry: Delivery;
  demo: boolean;
  onClose: () => void;
  onReviewed: (review: DeliveryReview) => void;
}) {
  const [resolution, setResolution] =
    useState<DeliveryReview['resolution']>('needs_followup');
  const [evidence, setEvidence] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [history, setHistory] = useState<DeliveryReview[]>(
    entry.latest_review ? [entry.latest_review] : [],
  );
  const requestId = useRef<string | null>(null);
  const locked = /refresh|may have been saved/i.test(error);
  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    void read<{ items: DeliveryReview[] }>(
      `integrations/deliveries/${entry.id}/reviews?limit=5`,
      controller.signal,
    )
      .then((page) => {
        if (!controller.signal.aborted) setHistory(page.items);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setHistoryError(
            'Review history is unavailable. Refresh the workspace before reviewing.',
          );
      });
    return () => controller.abort();
  }, [demo, entry.id]);
  async function submit() {
    setBusy(true);
    setError('');
    try {
      if (!confirmed || !evidence.trim())
        throw Error('Describe the evidence and confirm your review.');
      requestId.current ??= crypto.randomUUID();
      const body = {
        client_request_id: requestId.current,
        expected_status: entry.status,
        expected_attempt_count: entry.attempt_count,
        expected_review_revision: entry.review_revision,
        resolution,
        evidence: evidence.trim(),
      };
      const review = demo
        ? {
            id: Date.now(),
            delivery_id: entry.id,
            provider_status: entry.status,
            attempt_count: entry.attempt_count,
            review_revision: entry.review_revision + 1,
            resolution,
            evidence: evidence.trim(),
            created_by: 'Demo coordinator',
            created_at: new Date().toISOString(),
          }
        : await write<DeliveryReview>(
            `integrations/deliveries/${entry.id}/reviews`,
            body,
          );
      onReviewed(review);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : 'The review could not be confirmed. Refresh before trying again.',
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent
        showCloseButton={false}
        className="max-h-[90dvh] overflow-y-auto sm:max-w-lg p-6"
      >
        <div className="flex justify-between gap-4 items-start">
          <div>
            <p className="eyebrow">Delivery review</p>
            <DialogTitle className="text-2xl mt-3">
              Record what you verified.
            </DialogTitle>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close delivery review"
            disabled={busy}
            onClick={onClose}
          >
            <X size={18} />
          </Button>
        </div>
        <div className="rounded-xl border bg-muted/30 p-4 text-sm space-y-2">
          <p>
            {entry.contact_name} · {entry.contact_phone}
          </p>
          <p>
            {entry.location_name} → {entry.destination}
          </p>
          <p>
            Provider result: <strong>{entry.status}</strong> ·{' '}
            {entry.attempt_count} attempt(s)
          </p>
        </div>
        <p className="text-sm text-muted-foreground">
          This records a staff assessment. It does not change the provider
          result, prove delivery automatically, or resend the contact.
        </p>
        {historyError && (
          <p className="text-sm text-destructive">{historyError}</p>
        )}
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label className="block text-sm">
            Your finding
            <select
              className="mt-2 w-full h-10 rounded-lg border bg-background px-3"
              value={resolution}
              disabled={busy || locked}
              onChange={(event) =>
                setResolution(
                  event.target.value as DeliveryReview['resolution'],
                )
              }
            >
              <option value="needs_followup">
                Further investigation needed
              </option>
              <option value="verified_received">
                I found the contact at the destination
              </option>
              <option value="verified_not_received">
                I verified the contact was not received
              </option>
            </select>
          </label>
          <label className="block text-sm">
            Evidence or next investigation step
            <textarea
              className="mt-2 w-full rounded-lg border bg-background p-3 text-sm min-h-24"
              required
              maxLength={1000}
              value={evidence}
              disabled={busy || locked}
              onChange={(event) => setEvidence(event.target.value)}
              placeholder="Describe what you checked and the relevant record reference."
            />
          </label>
          <p className="text-xs text-muted-foreground">
            Use an operational reference. Leave clinical details, passwords, and
            access tokens out of this note.
          </p>
          <label className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              className="mt-1 accent-primary"
              checked={confirmed}
              required
              disabled={busy || locked}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>
              I reviewed the evidence and understand this will not resend the
              contact.
            </span>
          </label>
          {error && (
            <output className="block text-sm text-destructive">{error}</output>
          )}
          <Button
            type="submit"
            disabled={
              busy || locked || !!historyError || !confirmed || !evidence.trim()
            }
          >
            <ClipboardCheck size={16} />
            {demo ? 'Save demo review' : 'Record staff review'}
          </Button>
        </form>
        {history.length > 0 && (
          <section className="border-t pt-4">
            <h3 className="text-sm font-medium mb-3">Recent reviews</h3>
            <div className="space-y-3">
              {history.map((review) => (
                <article
                  key={review.id}
                  className="rounded-lg border p-3 text-xs space-y-2"
                >
                  <p className="font-medium">
                    {REVIEW_LABELS[review.resolution]}
                  </p>
                  <p className="whitespace-pre-wrap break-words">
                    {review.evidence}
                  </p>
                  <p className="text-muted-foreground break-all">
                    {review.created_by} ·{' '}
                    {new Date(review.created_at).toLocaleString()}
                  </p>
                </article>
              ))}
            </div>
          </section>
        )}
      </DialogContent>
    </Dialog>
  );
}
