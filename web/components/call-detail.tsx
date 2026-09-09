'use client';
import {
  ArrowLeft,
  ArrowUpRight,
  CheckCheck,
  Clock3,
  FileText,
  Phone,
  ShieldCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable';
import { useIsMobile } from '@/hooks/use-mobile';
import type { CallDetail } from '@/lib/domain';
import { date, display, duration, label, ruleLabels } from '@/lib/domain';
export function CallReview({
  call,
  onBack,
  demo,
}: {
  call: CallDetail;
  onBack: () => void;
  demo: boolean;
}) {
  const mobile = useIsMobile();
  const transcript = (
    <div className="transcript-pane">
      <div className="pane-title">
        <div>
          <span className="eyebrow">The conversation</span>
          <p className="text-sm text-muted-foreground mt-1">
            {call.turns.length} turns ·{' '}
            {demo ? 'Illustrative transcript' : 'Recorded transcript'}
          </p>
        </div>
        <FileText size={18} className="text-muted-foreground" />
      </div>
      <Tabs defaultValue="transcript">
        <TabsList variant="line" className="mb-5">
          <TabsTrigger value="transcript">Transcript</TabsTrigger>
          <TabsTrigger value="timing">Turn timing</TabsTrigger>
        </TabsList>
        <TabsContent value="transcript">
          <div className="transcript-lines">
            {call.turns.length ? (
              call.turns.map((turn, index) => (
                <article
                  className={`transcript-turn ${turn.speaker === 'agent' ? 'agent-turn' : 'caller-turn'}`}
                  key={turn.id}
                >
                  <div className="turn-avatar">
                    {turn.speaker === 'agent' ? (
                      <span className="text-xs font-semibold">a.</span>
                    ) : (
                      (call.name ?? 'Caller').charAt(0)
                    )}
                  </div>
                  <div>
                    <div className="flex gap-3 items-center mb-2">
                      <span className="font-medium text-sm">
                        {turn.speaker === 'agent'
                          ? 'ArcAgent'
                          : (call.name ?? 'Caller')}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Turn {index + 1}
                      </span>
                      {turn.interrupted && (
                        <Badge variant="outline">Interrupted</Badge>
                      )}
                    </div>
                    <p className="turn-text">{turn.text}</p>
                    {turn.node && (
                      <p className="turn-node">{label(turn.node)}</p>
                    )}
                  </div>
                </article>
              ))
            ) : (
              <p className="text-muted-foreground text-sm py-8">
                No transcript was recorded for this call.
              </p>
            )}
          </div>
        </TabsContent>
        <TabsContent value="timing">
          <p className="text-sm text-muted-foreground mb-6">
            Stored measurements for each turn. A missing value means the stage
            was not measured. Playback acknowledgement measures completion, not
            first audio.
          </p>
          {call.turns
            .filter((t) => t.speaker === 'agent')
            .map((turn) => (
              <div className="timing-row" key={turn.id}>
                <p className="text-sm font-medium mb-3">{label(turn.node)}</p>
                <div className="grid grid-cols-2 gap-3">
                  {Object.entries(turn.latency).map(([key, value]) => (
                    <div key={key}>
                      <p className="text-xs text-muted-foreground">
                        {key === 'playback_start_ms'
                          ? 'Playback acknowledgement'
                          : label(key.replace('_ms', ''))}
                      </p>
                      <p className="text-sm mt-1">
                        {value === null ? 'Not measured' : `${value} ms`}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
        </TabsContent>
      </Tabs>
    </div>
  );
  const facts = (
    <aside className="facts-pane">
      <div className="pane-title">
        <span className="eyebrow">The context</span>
        <ShieldCheck size={17} />
      </div>
      <div className="score-card">
        <div className="flex justify-between items-center">
          <span className="text-sm">Qualification score</span>
          <ArrowUpRight size={16} />
        </div>
        <div className="score-value">
          {call.score ?? 'N/A'}
          <span>
            {call.threshold !== null
              ? `/ ${call.threshold} threshold`
              : 'No score recorded'}
          </span>
        </div>
        {call.score !== null && (
          <div className="score-track">
            <span
              style={{
                width: `${Math.min(100, Math.max(0, (call.score / Math.max(call.threshold ?? 60, 1)) * 100))}%`,
              }}
            />
          </div>
        )}
        <p className="text-sm mt-4 font-medium">{label(call.outcome)}</p>
      </div>
      <div className="mt-6">
        <h3 className="text-sm font-semibold mb-3">Why this score?</h3>
        {Object.entries(call.score_breakdown ?? {}).length ? (
          Object.entries(call.score_breakdown).map(([rule, points]) => (
            <div className="score-rule" key={rule}>
              <span>{ruleLabels[rule] ?? label(rule)}</span>
              <strong
                className={points < 0 ? 'text-destructive' : 'text-primary'}
              >
                {points > 0 ? '+' : ''}
                {points}
              </strong>
            </div>
          ))
        ) : (
          <p className="text-sm text-muted-foreground">
            No scoring rules were recorded.
          </p>
        )}
        <p className="text-xs text-muted-foreground leading-relaxed mt-4">
          The score supports qualification. Coordinator availability and routing
          results also determine the final outcome.
        </p>
      </div>
      <div className="facts-list">
        <h3 className="text-sm font-semibold mb-4">Lead details</h3>
        {Object.entries(call.fields).map(([key, value]) => (
          <div key={key}>
            <dt>{key === 'has_insurance' ? 'Dental insurance' : label(key)}</dt>
            <dd>{display(value)}</dd>
          </div>
        ))}
      </div>
    </aside>
  );
  return (
    <>
      <Button variant="ghost" onClick={onBack} className="mb-5 -ml-2">
        <ArrowLeft /> All conversations
      </Button>
      <div className="detail-heading">
        <div>
          <div className="flex items-center gap-3">
            <h1>{call.name ?? 'Unknown caller'}</h1>
            <Badge
              className={`outcome-badge ${call.outcome === 'handoff' ? 'handoff' : ''}`}
              variant="secondary"
            >
              {label(call.outcome)}
            </Badge>
          </div>
          <p className="flex items-center gap-4 text-sm text-muted-foreground mt-3 flex-wrap">
            <span className="inline-flex items-center gap-1.5">
              <Phone size={14} /> Inbound enquiry
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock3 size={14} />
              {duration(call.duration_s)}
            </span>
            <span>{date(call.started_at)} UTC</span>
          </p>
        </div>
        <span className="text-xs text-muted-foreground inline-flex items-center gap-1">
          <CheckCheck size={14} /> {demo ? 'Synthetic call' : 'Saved call'}
        </span>
      </div>
      <div className="review-panel">
        {mobile ? (
          <>
            {transcript}
            {facts}
          </>
        ) : (
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel defaultSize="65%" minSize="40%">
              {transcript}
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize="35%" minSize="25%">
              {facts}
            </ResizablePanel>
          </ResizablePanelGroup>
        )}
      </div>
    </>
  );
}
