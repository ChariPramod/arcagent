'use client';
import Link from 'next/link';
import { useConversationTool } from '@/lib/use-conversation-tool';
import { lazy, Suspense, useEffect, useState } from 'react';
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  FlaskConical,
  Headphones,
  Inbox,
  LogOut,
  Phone,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { Brand } from '@/components/brand';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Empty, EmptyDescription, EmptyTitle } from '@/components/ui/empty';
import {
  SidebarProvider,
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarFooter,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarInset,
  SidebarTrigger,
  useSidebar,
} from '@/components/ui/sidebar';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Choice } from '@/components/choice';
import { CallReview } from '@/components/call-detail';
import { Operations } from '@/components/operations';
const Workflows = lazy(() =>
  import('@/components/workflows').then((module) => ({
    default: module.Workflows,
  })),
);
const FailureLab = lazy(() =>
  import('@/components/failure-lab').then((module) => ({
    default: module.FailureLab,
  })),
);
import { Metric } from '@/components/metric';
const Evaluations = lazy(() =>
  import('@/components/evaluations').then((module) => ({
    default: module.Evaluations,
  })),
);
import { demoCalls } from '@/lib/demo';
import { read } from '@/lib/client';
import {
  date,
  duration,
  filterCalls,
  label,
  outcomeLabels,
} from '@/lib/domain';
import type { CallDetail, CallSummary, Page } from '@/lib/domain';
type View = 'operations' | 'calls' | 'evaluations' | 'workflows' | 'lab';
export function Console({
  demo,
  userName = 'Demo workspace',
  initialView = 'operations',
  initialCall = null,
}: {
  demo: boolean;
  userName?: string;
  initialView?: View;
  initialCall?: number | null;
}) {
  const [view, setView] = useState<View>(initialView);
  const [calls, setCalls] = useState<CallSummary[]>(demo ? demoCalls : []);
  const [total, setTotal] = useState(demo ? demoCalls.length : 0);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<number | null>(initialCall);
  const [detail, setDetail] = useState<CallDetail | null>(
    demo ? (demoCalls.find((c) => c.id === initialCall) ?? null) : null,
  );
  const [query, setQuery] = useState('');
  const [outcome, setOutcome] = useState('all');
  const [day, setDay] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(!demo);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (demo || view !== 'calls') return;
    let active = true;
    // oxlint-disable-next-line react/react-compiler -- Reset stale request state before fetching.
    setLoading(true);
    setError('');
    read<Page<CallSummary>>(`calls?limit=50&offset=${offset}`)
      .then((data) => {
        if (active) {
          setCalls(data.items);
          setTotal(data.total);
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
  }, [demo, offset, refresh, view]);
  useEffect(() => {
    if (selected === null) {
      // oxlint-disable-next-line react/react-compiler -- Synchronize the selected record before async loading.
      setDetail(null);
      return;
    }
    if (demo) {
      setDetail(demoCalls.find((c) => c.id === selected) ?? null);
      return;
    }
    let active = true;
    setDetail(null);
    setError('');
    read<CallDetail>(`calls/${selected}`)
      .then((data) => {
        if (active) setDetail(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [selected, demo, refresh]);
  const filtered = filterCalls(calls, query, outcome, day);
  useConversationTool(
    filtered,
    demo,
    view === 'calls' && selected === null && !loading && !error,
  );
  function navigate(next: View) {
    setView(next);
    setSelected(null);
    setError('');
  }
  return (
    <SidebarProvider
      style={{ '--sidebar-width': '14rem' } as React.CSSProperties}
    >
      <SideNav
        demo={demo}
        view={view}
        navigate={navigate}
        userName={userName}
      />
      <SidebarInset className="console-body">
        <header className="console-topbar">
          <div className="flex items-center gap-3">
            <SidebarTrigger />
            <span className="text-sm text-muted-foreground">
              Workspace <span className="mx-2 text-border">/</span>
              <span className="text-foreground">
                {view === 'operations'
                  ? 'Operations'
                  : view === 'calls'
                    ? 'Conversations'
                    : view === 'workflows'
                      ? 'Follow-up & feedback'
                      : view === 'lab'
                        ? 'Failure lab'
                        : 'Evaluations'}
              </span>
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground hidden sm:inline">
              {demo ? 'A closer look at ArcAgent' : 'Your team’s workspace'}
            </span>
            <span className="user-avatar">
              {demo ? 'D' : userName.charAt(0).toUpperCase()}
            </span>
          </div>
        </header>
        {demo && (
          <div className="demo-notice">
            <span>
              <span className="sample-dot" /> Demo workspace{' '}
              <span className="hidden sm:inline">
                · Fictional calls and illustrative evals. No live patient data.
              </span>
            </span>
            <Link href="/workspace">
              Open your workspace <ArrowUpRight size={13} />
            </Link>
          </div>
        )}
        <main className="workspace-content" id="main">
          {view === 'operations' ? (
            <Operations
              demo={demo}
              onReviewCall={(id) => {
                setView('calls');
                setSelected(id);
                setError('');
              }}
            />
          ) : view === 'workflows' ? (
            <Suspense fallback={<Skeleton className="h-96" />}>
              <Workflows
                demo={demo}
                onReviewCall={(id) => {
                  setView('calls');
                  setSelected(id);
                  setError('');
                }}
              />
            </Suspense>
          ) : view === 'lab' ? (
            <Suspense fallback={<Skeleton className="h-96" />}>
              <FailureLab demo={demo} />
            </Suspense>
          ) : view === 'evaluations' ? (
            <Suspense fallback={<Skeleton className="h-96" />}>
              <Evaluations demo={demo} />
            </Suspense>
          ) : (
            <>
              {error && (
                <div role="alert" className="error-panel">
                  <div>
                    <p className="font-medium">{error}</p>
                    <p className="text-sm mt-2">
                      {demo
                        ? 'Choose another conversation.'
                        : 'Your live records have not been replaced with demo data.'}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      onClick={() => setRefresh(refresh + 1)}
                    >
                      Try again
                    </Button>
                    {selected !== null && (
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setSelected(null);
                          setError('');
                        }}
                      >
                        Go back
                      </Button>
                    )}
                  </div>
                </div>
              )}
              {selected !== null ? (
                detail ? (
                  <CallReview
                    call={detail}
                    demo={demo}
                    onBack={() => {
                      setSelected(null);
                      setError('');
                    }}
                  />
                ) : !error ? (
                  <Skeleton className="h-[600px] rounded-xl" />
                ) : null
              ) : (
                <>
                  <div className="workspace-heading">
                    <div>
                      <p className="eyebrow text-primary">
                        The first hello matters
                      </p>
                      <h1>
                        Every conversation.
                        <br />
                        <span className="serif italic">All the context.</span>
                      </h1>
                      <p className="text-muted-foreground text-sm mt-4">
                        Review the details, understand the decision, and pick up
                        where the caller left off.
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      className="h-10 bg-white"
                      onClick={() => {
                        setRefresh(refresh + 1);
                        setQuery('');
                        setOutcome('all');
                        setDay('');
                      }}
                    >
                      <RefreshCw size={15} />
                      Refresh view
                    </Button>
                  </div>
                  {loading ? (
                    <div className="metric-grid">
                      {[0, 1, 2, 3].map((n) => (
                        <Skeleton key={n} className="h-32 rounded-xl" />
                      ))}
                    </div>
                  ) : (
                    <div className="metric-grid">
                      <Metric
                        name="Calls in view"
                        value={String(filtered.length)}
                        note={
                          demo
                            ? 'Synthetic examples'
                            : `From ${total} recorded calls`
                        }
                      />
                      <Metric
                        name="Handed off"
                        value={String(
                          filtered.filter((c) => c.outcome === 'handoff')
                            .length,
                        )}
                        note="Connected with a coordinator"
                      />
                      <Metric
                        name="Callbacks booked"
                        value={String(
                          filtered.filter(
                            (c) => c.outcome === 'callback_booked',
                          ).length,
                        )}
                        note="A next step, arranged"
                      />
                      <Metric
                        name="Other outcomes"
                        value={String(
                          filtered.filter(
                            (c) =>
                              !['handoff', 'callback_booked'].includes(
                                c.outcome ?? '',
                              ),
                          ).length,
                        )}
                        note="Other or pending dispositions"
                      />
                    </div>
                  )}
                  <section className="table-panel">
                    <div className="table-heading">
                      <div>
                        <h2>Conversations</h2>
                        <p>
                          {demo
                            ? 'Explore a fictional caller’s journey.'
                            : 'Select a call to review its transcript and qualification.'}
                        </p>
                      </div>
                      {calls[0] && (
                        <Button
                          variant="ghost"
                          className="text-primary"
                          onClick={() => setSelected(calls[0].id)}
                        >
                          Review latest <ArrowRight size={15} />
                        </Button>
                      )}
                    </div>
                    <div className="table-filters">
                      <div className="search-field">
                        <Search size={16} />
                        <Input
                          aria-label="Search conversations on this page"
                          placeholder="Search caller or treatment…"
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                        />
                      </div>
                      <Choice
                        label="Filter by outcome"
                        value={outcome}
                        onChange={setOutcome}
                        options={[
                          { value: 'all', label: 'All outcomes' },
                          ...Object.entries(outcomeLabels).map(
                            ([value, text]) => ({ value, label: text }),
                          ),
                        ]}
                      />
                      <Input
                        type="date"
                        aria-label="Filter by date, UTC"
                        value={day}
                        onChange={(e) => setDay(e.target.value)}
                        className="date-input h-10"
                      />
                      {(query || outcome !== 'all' || day) && (
                        <Button
                          variant="ghost"
                          onClick={() => {
                            setQuery('');
                            setOutcome('all');
                            setDay('');
                          }}
                        >
                          Clear
                        </Button>
                      )}
                    </div>
                    {loading ? (
                      <div className="p-6 space-y-4">
                        {[0, 1, 2].map((n) => (
                          <Skeleton key={n} className="h-16" />
                        ))}
                      </div>
                    ) : filtered.length ? (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Caller</TableHead>
                            <TableHead>Treatment interest</TableHead>
                            <TableHead>Outcome</TableHead>
                            <TableHead>Score</TableHead>
                            <TableHead>Duration</TableHead>
                            <TableHead>Received · UTC</TableHead>
                            <TableHead>
                              <span className="sr-only">Open call</span>
                            </TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {filtered.map((call) => (
                            <TableRow key={call.id}>
                              <TableCell>
                                <div className="flex items-center gap-3">
                                  <span className="caller-avatar">
                                    {call.name ? (
                                      call.name
                                        .split(' ')
                                        .map((s) => s[0])
                                        .slice(0, 2)
                                        .join('')
                                    ) : (
                                      <Phone size={16} />
                                    )}
                                  </span>
                                  <div>
                                    <Button
                                      variant="link"
                                      className="h-auto p-0 text-foreground"
                                      onClick={() => setSelected(call.id)}
                                    >
                                      {call.name ?? 'Unknown caller'}
                                    </Button>
                                    <span className="block text-xs text-muted-foreground mt-1">
                                      Call #{call.id}
                                    </span>
                                  </div>
                                </div>
                              </TableCell>
                              <TableCell>
                                {label(call.treatment_interest)}
                              </TableCell>
                              <TableCell>
                                <Badge
                                  className={`outcome-badge ${call.outcome === 'handoff' ? 'handoff' : ''}`}
                                  variant="secondary"
                                >
                                  {call.outcome === 'handoff' && (
                                    <span className="sample-dot" />
                                  )}
                                  {label(call.outcome)}
                                </Badge>
                              </TableCell>
                              <TableCell>
                                <span className="font-medium">
                                  {call.score ?? 'N/A'}
                                </span>
                                {call.threshold !== null && (
                                  <span className="text-xs text-muted-foreground">
                                    {' '}
                                    / {call.threshold}
                                  </span>
                                )}
                              </TableCell>
                              <TableCell className="text-muted-foreground">
                                {duration(call.duration_s)}
                              </TableCell>
                              <TableCell className="text-muted-foreground whitespace-nowrap">
                                {date(call.started_at)}
                              </TableCell>
                              <TableCell>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  aria-label={`Review call ${call.id}`}
                                  onClick={() => setSelected(call.id)}
                                >
                                  <ArrowUpRight size={17} />
                                </Button>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    ) : (
                      <Empty className="py-20">
                        <Inbox className="text-muted-foreground mb-3" />
                        <EmptyTitle>
                          {calls.length
                            ? 'No matching conversations'
                            : 'Your conversations will appear here'}
                        </EmptyTitle>
                        <EmptyDescription>
                          {calls.length
                            ? 'Try another search, outcome, or date.'
                            : 'Once calls are recorded, you can review their transcripts, details, and outcomes here.'}
                        </EmptyDescription>
                      </Empty>
                    )}
                    <div className="table-footer">
                      <span>
                        {filtered.length} shown · {total}{' '}
                        {demo ? 'demo calls' : 'recorded calls'}
                        {!demo && ' · Search filters this page'}
                      </span>
                      <div className="flex gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={offset === 0 || demo || loading}
                          onClick={() => setOffset(Math.max(0, offset - 50))}
                        >
                          <ArrowLeft size={14} />
                          Previous
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={offset + 50 >= total || demo || loading}
                          onClick={() => setOffset(offset + 50)}
                        >
                          Next
                          <ArrowRight size={14} />
                        </Button>
                      </div>
                    </div>
                  </section>
                  <div className="workspace-note">
                    <ShieldCheck size={16} />
                    <p>
                      Every qualification score follows a defined rule table.
                      Open a call to see the facts behind it.
                    </p>
                  </div>
                </>
              )}
            </>
          )}
        </main>
        <footer className="console-footer">
          <span>ArcAgent · Thoughtful conversations, clear next steps.</span>
          <span>{demo ? 'Synthetic demonstration' : 'Private workspace'}</span>
        </footer>
      </SidebarInset>
    </SidebarProvider>
  );
}
function SideNav({
  demo,
  view,
  navigate,
  userName,
}: {
  demo: boolean;
  view: View;
  navigate: (view: View) => void;
  userName: string;
}) {
  const { setOpenMobile } = useSidebar();
  function go(v: View) {
    navigate(v);
    setOpenMobile(false);
  }
  return (
    <Sidebar className="border-r border-sidebar-border" collapsible="offcanvas">
      <SidebarHeader className="px-6 pt-7 pb-8">
        <Brand />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="px-4">
          <SidebarGroupLabel className="eyebrow mb-3">
            Your workspace
          </SidebarGroupLabel>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                className="h-11 px-3"
                isActive={view === 'operations'}
                onClick={() => go('operations')}
              >
                <Activity size={17} />
                <span>Operations</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                className="h-11 px-3"
                isActive={view === 'calls'}
                onClick={() => go('calls')}
              >
                <Headphones size={17} />
                <span>Conversations</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                className="h-11 px-3"
                isActive={view === 'evaluations'}
                onClick={() => go('evaluations')}
              >
                <FlaskConical size={17} />
                <span>Evaluations</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                className="h-11 px-3"
                isActive={view === 'workflows'}
                onClick={() => go('workflows')}
              >
                <Activity size={17} />
                <span>Follow-up & feedback</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                className="h-11 px-3"
                isActive={view === 'lab'}
                onClick={() => go('lab')}
              >
                <FlaskConical size={17} />
                <span>Failure lab</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
        <div className="sidebar-note">
          <span className="mini-mark">a.</span>
          <h3>
            Good context.
            <br />
            Better next steps.
          </h3>
          <p>
            See what was said.
            <br />
            Understand what happened.
          </p>
          <Link href="/" className="inline-flex items-center gap-2 mt-4">
            About ArcAgent
            <ArrowUpRight size={13} />
          </Link>
        </div>
      </SidebarContent>
      <SidebarFooter className="border-t p-5">
        <div className="flex items-center gap-3">
          <span className="user-avatar">
            {demo ? 'D' : userName.charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0">
            <p className="text-sm truncate max-w-32">
              {demo ? 'Demo workspace' : userName}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {demo ? 'Explore at your own pace' : 'Signed in with ChatGPT'}
            </p>
          </div>
        </div>
        {!demo && (
          <Link
            href="/signout-with-chatgpt?return_to=/"
            target="_top"
            className="text-xs text-muted-foreground inline-flex gap-2 mt-3"
          >
            <LogOut size={13} />
            Sign out
          </Link>
        )}
      </SidebarFooter>
    </Sidebar>
  );
}
