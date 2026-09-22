'use client';
import { useEffect, useRef, useState } from 'react';
import {
  ClipboardCheck,
  RefreshCw,
  ArrowRight,
  ShieldCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { read, write } from '@/lib/client';

type Task = {
  id: number;
  call_id: number;
  revision: number;
  status: string;
  assignee: string | null;
  notes: string;
};
type Feedback = {
  id: number;
  call_id: number;
  revision: number;
  status: string;
  category: string;
  scenario: string;
  expected_behavior: string;
  created_by: string;
};
const example: Task = {
  id: 1,
  call_id: 1042,
  revision: 1,
  status: 'open',
  assignee: null,
  notes: 'Review the interrupted enquiry before arranging a callback.',
};
export function Workflows({
  demo,
  onReviewCall,
}: {
  demo: boolean;
  onReviewCall: (id: number) => void;
}) {
  const feedbackRequestId = useRef<string | null>(null);
  const [tab, setTab] = useState<'followups' | 'feedback'>('followups');
  const [tasks, setTasks] = useState<Task[]>(demo ? [example] : []);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [refresh, setRefresh] = useState(0);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(demo ? 1 : 0);
  const [loading, setLoading] = useState(!demo);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [selected, setSelected] = useState<Task | null>(null);
  const [artifact, setArtifact] = useState('');
  const [artifactTitle, setArtifactTitle] = useState(
    'Approved candidate artifact',
  );
  const locked = /refresh|may have been saved/i.test(error);
  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    // oxlint-disable-next-line react/react-compiler -- Synchronize remote query state.
    setLoading(true);
    setError('');
    setArtifact('');
    read<{ items: Task[] | Feedback[]; total: number }>(
      `${tab}?limit=25&offset=${offset}`,
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data.items) || !Number.isInteger(data.total))
          throw Error('Invalid workspace response');
        if (tab === 'followups') setTasks(data.items as Task[]);
        else setFeedback(data.items as Feedback[]);
        setTotal(data.total);
        setLoading(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError('Could not load this queue. Refresh to reconnect.');
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [demo, tab, refresh, offset]);
  async function act(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await action();
      setMessage(success);
      setRefresh((x) => x + 1);
      setSelected(null);
      if (success.startsWith('Feedback')) feedbackRequestId.current = null;
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'Action could not be confirmed. Refresh before retrying.',
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="workbench">
      <header className="workbench-heading">
        <div>
          <p className="eyebrow text-primary">HUMAN FOLLOW-THROUGH</p>
          <h1>Close the loop.</h1>
          <p>Own the next step. Turn reviewed failures into better tests.</p>
        </div>
        <Button
          variant="outline"
          disabled={busy || demo}
          onClick={() => {
            setMessage('');
            setRefresh((x) => x + 1);
          }}
        >
          <RefreshCw size={16} /> Refresh
        </Button>
      </header>
      <div className="flex gap-2 mb-6" aria-label="Workflow views">
        {(['followups', 'feedback'] as const).map((value) => (
          <Button
            key={value}
            variant={tab === value ? 'default' : 'outline'}
            onClick={() => {
              setTab(value);
              setOffset(0);
              setError('');
              setMessage('');
            }}
          >
            {value === 'followups' ? 'Follow-up queue' : 'Feedback review'}
          </Button>
        ))}
      </div>
      {demo && (
        <p className="lab-notice">
          Fictional queue preview. Saving, assigning, and reviewing require your
          connected workspace.
        </p>
      )}
      {error && (
        <div role="alert" className="error-panel">
          {error} Your draft is retained. After a conflict, copy your note
          before opening the latest record.
        </div>
      )}
      {message && <output className="lab-notice">{message}</output>}
      <div className="workbench-grid">
        <section className="workbench-card">
          <div className="flex justify-between items-center mb-6">
            <h2>
              {tab === 'followups' ? 'Coordinator queue' : 'Review candidates'}
            </h2>
            <Badge variant="outline">
              {loading
                ? 'Loading'
                : `${demo && tab === 'feedback' ? 0 : total} records`}
            </Badge>
          </div>
          {loading ? (
            <output>Loading saved records…</output>
          ) : error && !tasks.length && !feedback.length ? (
            <p>Records are unavailable.</p>
          ) : tab === 'followups' ? (
            <>
              {!tasks.length && (
                <p className="text-muted-foreground">
                  No follow-ups have been created. Add one using a saved call
                  ID.
                </p>
              )}
              {tasks.map((task) => (
                <article className="queue-row" key={task.id}>
                  <div>
                    <Badge variant="secondary">
                      {task.status.replaceAll('_', ' ')}
                    </Badge>
                    <h3 className="mt-3">Call #{task.call_id}</h3>
                    <p className="text-muted-foreground text-sm mt-1">
                      {task.assignee || 'Unassigned'}
                    </p>
                    <p className="mt-3 text-sm whitespace-pre-wrap">
                      {task.notes || 'No coordinator note yet.'}
                    </p>
                  </div>
                  <div className="flex gap-2 mt-4">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={demo || busy}
                      onClick={() => {
                        setSelected({ ...task });
                        setError('');
                      }}
                    >
                      Edit follow-up
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={demo}
                      onClick={() => onReviewCall(task.call_id)}
                    >
                      Review call <ArrowRight size={14} />
                    </Button>
                  </div>
                </article>
              ))}
            </>
          ) : (
            <>
              {!feedback.length && (
                <p className="text-muted-foreground">
                  No feedback candidates yet. Write a fictional reproduction
                  with an independently checkable expected result.
                </p>
              )}
              {feedback.map((item) => (
                <article className="queue-row" key={item.id}>
                  <Badge variant="secondary">{item.status}</Badge>
                  <h3 className="mt-3">
                    {item.category.replaceAll('_', ' ')} · Call #{item.call_id}
                  </h3>
                  <p className="mt-3 whitespace-pre-wrap">{item.scenario}</p>
                  <p className="text-sm mt-3">
                    <strong>Expected:</strong> {item.expected_behavior}
                  </p>
                  {item.status === 'pending' ? (
                    <form
                      className="mt-4"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const form = new FormData(e.currentTarget);
                        void act(
                          () =>
                            write(`feedback/${item.id}/review`, {
                              revision: item.revision,
                              decision: form.get('decision'),
                              review_note: form.get('review_note'),
                            }),
                          'Review saved.',
                        );
                      }}
                    >
                      <label className="field-label">
                        Independent review note
                        <textarea
                          name="review_note"
                          minLength={10}
                          required
                          maxLength={2000}
                          className="workbench-input"
                        />
                      </label>
                      <label className="field-label">
                        Decision
                        <select name="decision" className="workbench-input">
                          <option value="approved">Approve candidate</option>
                          <option value="rejected">Reject candidate</option>
                        </select>
                      </label>
                      <Button disabled={busy || locked}>Save review</Button>
                      <p className="text-xs text-muted-foreground mt-2">
                        The author cannot approve their own candidate.
                      </p>
                    </form>
                  ) : item.status === 'approved' ? (
                    <Button
                      className="mt-4"
                      variant="outline"
                      disabled={busy}
                      onClick={() => {
                        void read<unknown>(`feedback/${item.id}/export`)
                          .then((data) => {
                            setArtifactTitle('Approved candidate artifact');
                            setArtifact(JSON.stringify(data, null, 2));
                          })
                          .catch(() =>
                            setError(
                              'Export unavailable. Refresh and try again.',
                            ),
                          );
                      }}
                    >
                      View candidate export
                    </Button>
                  ) : null}
                </article>
              ))}
            </>
          )}
          {!demo && (
            <div className="flex justify-between gap-2 mt-6">
              <Button
                variant="outline"
                disabled={busy || loading || offset === 0}
                onClick={() => setOffset((x) => Math.max(0, x - 25))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                disabled={busy || loading || offset + 25 >= total}
                onClick={() => setOffset((x) => x + 25)}
              >
                Next
              </Button>
            </div>
          )}
        </section>
        <section className="workbench-card">
          <div className="flex gap-2 items-center mb-6">
            {tab === 'followups' ? (
              <ClipboardCheck size={20} />
            ) : (
              <ShieldCheck size={20} />
            )}
            <h2>
              {tab === 'followups'
                ? selected
                  ? 'Update follow-up'
                  : 'Add follow-up'
                : 'Create regression candidate'}
            </h2>
          </div>
          <form
            key={`${tab}-${selected?.id ?? 'new'}-${selected?.revision ?? 0}`}
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              if (tab === 'followups')
                void act(
                  () =>
                    selected
                      ? write(
                          `followups/${selected.id}`,
                          {
                            revision: selected.revision,
                            status: form.get('status'),
                            assignee: form.get('assignee') || null,
                            notes: form.get('notes'),
                          },
                          'PATCH',
                        )
                      : write('followups', {
                          call_id: Number(form.get('call_id')),
                        }),
                  'Follow-up saved.',
                );
              else
                void act(
                  () =>
                    write('feedback', {
                      client_request_id:
                        feedbackRequestId.current ??
                        (feedbackRequestId.current = crypto.randomUUID()),
                      call_id: Number(form.get('call_id')),
                      category: form.get('category'),
                      scenario: form.get('scenario'),
                      expected_behavior: form.get('expected_behavior'),
                      synthetic_confirmed:
                        form.get('synthetic_confirmed') === 'on',
                    }),
                  'Feedback submitted for independent review.',
                );
            }}
          >
            <fieldset disabled={demo || busy || locked}>
              {!selected || tab === 'feedback' ? (
                <label className="field-label">
                  Saved call ID
                  <input
                    className="workbench-input"
                    name="call_id"
                    type="number"
                    min="1"
                    step="1"
                    required
                  />
                </label>
              ) : (
                <>
                  <p className="text-sm mb-4">
                    Call #{selected.call_id} · Revision {selected.revision}
                  </p>
                  <label className="field-label">
                    Assigned coordinator
                    <input
                      className="workbench-input"
                      name="assignee"
                      defaultValue={selected.assignee ?? ''}
                      maxLength={128}
                    />
                  </label>
                  <label className="field-label">
                    Status
                    <select
                      className="workbench-input"
                      name="status"
                      defaultValue={selected.status}
                    >
                      <option value="open">Open</option>
                      <option value="in_progress">In progress</option>
                      <option value="resolved">Resolved</option>
                    </select>
                  </label>
                  <label className="field-label">
                    Coordinator note
                    <textarea
                      className="workbench-input"
                      name="notes"
                      defaultValue={selected.notes}
                      maxLength={2000}
                    />
                  </label>
                </>
              )}
              {tab === 'feedback' && (
                <>
                  <label className="field-label">
                    Category
                    <select name="category" className="workbench-input">
                      <option value="missed_clarification">
                        Missed clarification
                      </option>
                      <option value="incorrect_callback">
                        Incorrect callback
                      </option>
                      <option value="incorrect_routing">
                        Incorrect routing
                      </option>
                      <option value="other">Other</option>
                    </select>
                  </label>
                  <label className="field-label">
                    Fictional reproduction
                    <textarea
                      name="scenario"
                      minLength={10}
                      className="workbench-input"
                      maxLength={4000}
                      required
                      placeholder="Rewrite the situation with invented details. Do not paste a transcript."
                    />
                  </label>
                  <label className="field-label">
                    Expected behavior
                    <textarea
                      name="expected_behavior"
                      minLength={10}
                      className="workbench-input"
                      maxLength={2000}
                      required
                    />
                  </label>
                  <label className="flex items-start gap-2 text-sm mb-5">
                    <input
                      name="synthetic_confirmed"
                      type="checkbox"
                      required
                    />
                    I rewrote this with fictional details and removed personal
                    information.
                  </label>
                </>
              )}
              <Button type="submit" disabled={demo || busy || locked}>
                {busy
                  ? 'Saving…'
                  : tab === 'feedback'
                    ? 'Submit for review'
                    : selected
                      ? 'Save changes'
                      : 'Create follow-up'}
              </Button>
            </fieldset>
          </form>
          {selected && (
            <Button
              className="mt-3"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setSelected(null);
                setError('');
              }}
            >
              Cancel editing
            </Button>
          )}
          <p className="text-sm text-muted-foreground mt-6">
            {tab === 'followups'
              ? 'Queue actions update internal records only. They never place a call, send a message, or book a callback slot.'
              : 'Approval exports a candidate for test authoring. It does not change prompts or automatically enter the evaluation suite.'}
          </p>
        </section>
      </div>
      {artifact && (
        <section className="workbench-card mt-6">
          <label className="field-label">
            {artifactTitle}
            <textarea
              className="workbench-input font-mono text-xs"
              rows={16}
              value={artifact}
              readOnly
            />
          </label>
        </section>
      )}
    </div>
  );
}
