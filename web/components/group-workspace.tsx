'use client';
import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import {
  Building2,
  Download,
  ArrowUpRight,
  RefreshCw,
  Plug,
  CheckCircle2,
  Clock3,
  ShieldCheck,
  X,
  Plus,
  AlertTriangle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { read, write } from '@/lib/client';
import {
  STAGES,
  STAGE_NAMES,
  exampleLeads,
  exampleLocations,
  exportLeads,
  isOverdue,
  type PipelineLead,
  type PipelinePage,
  type Location,
  type Destination,
  type Delivery,
  type Pilot,
} from '@/lib/group';

type Tab = 'pipeline' | 'locations' | 'integrations' | 'pilot';
const selectClass = 'h-10 rounded-lg border bg-background px-3 text-sm w-full';
const demoDestinations: Destination[] = [
  {
    destination: 'hubspot',
    configured: true,
    detail: 'Simulated connection for this fictional workspace.',
  },
  {
    destination: 'automation',
    configured: true,
    detail: 'Simulated automation endpoint. Nothing leaves this demo.',
  },
];
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : 'The action could not be confirmed. Refresh before trying again.';
function Notice({ children }: { children: React.ReactNode }) {
  return (
    <output className="block rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      {children}
    </output>
  );
}
export function GroupWorkspace({ demo }: { demo: boolean }) {
  const reduced = useReducedMotion();
  const [tab, setTab] = useState<Tab>('pipeline');
  const [leads, setLeads] = useState<PipelineLead[]>(demo ? exampleLeads : []);
  const [locations, setLocations] = useState<Location[]>(
    demo ? exampleLocations : [],
  );
  const [destinations, setDestinations] = useState<Destination[]>(
    demo ? demoDestinations : [],
  );
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [pilot, setPilot] = useState<Pilot | null>(null);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [total, setTotal] = useState(demo ? exampleLeads.length : 0);
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(!demo);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<PipelineLead | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [deliveryPage, setDeliveryPage] = useState(0);
  const [deliveryTotal, setDeliveryTotal] = useState(0);
  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    // oxlint-disable-next-line react/react-compiler -- Synchronize remote workspace query state.
    setLoading(true);
    setErrors({});
    const scope =
      filter === 'all'
        ? ''
        : filter === 'unassigned'
          ? '&unassigned=true'
          : `&location_id=${filter}`;
    const load = <T,>(key: string, path: string, accept: (value: T) => void) =>
      read<T>(path, controller.signal)
        .then((value) => {
          if (!controller.signal.aborted) accept(value);
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted)
            setErrors((old) => ({ ...old, [key]: errorText(error) }));
        });
    void Promise.all([
      load<PipelinePage>(
        'pipeline',
        `pipeline?limit=50&offset=${offset}${scope}`,
        (value) => {
          setLeads(value.items);
          setTotal(value.total);
          setSummary(value.summary);
        },
      ),
      load<{ items: Location[] }>('locations', 'locations', (value) =>
        setLocations(value.items),
      ),
      load<{ destinations: Destination[] }>(
        'integrations',
        'integrations',
        (value) => setDestinations(value.destinations),
      ),
      load<{ items: Delivery[]; total: number }>(
        'deliveries',
        `integrations/deliveries?limit=25&offset=${deliveryPage}`,
        (value) => {
          setDeliveries(value.items);
          setDeliveryTotal(value.total);
        },
      ),
      load<Pilot>('pilot', 'pilot', setPilot),
    ]).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [demo, filter, offset, refresh, deliveryPage]);
  const scoped = demo
    ? leads.filter(
        (lead) =>
          filter === 'all' ||
          (filter === 'unassigned'
            ? lead.location_id === null
            : lead.location_id === Number(filter)),
      )
    : leads;
  const visible = scoped.filter((lead) =>
    `${lead.name ?? ''} ${lead.assignee ?? ''} ${lead.call_id}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const counts = demo
    ? Object.fromEntries(
        STAGES.map((stage) => [
          stage,
          scoped.filter((lead) => lead.stage === stage).length,
        ]),
      )
    : summary;
  const refreshData = () => {
    setSelected(null);
    setMessage('');
    setRefresh((value) => value + 1);
  };
  function download() {
    const url = URL.createObjectURL(
      new Blob([exportLeads(visible)], { type: 'text/csv;charset=utf-8' }),
    );
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = demo
      ? 'arcagent-fictional-leads.csv'
      : 'arcagent-displayed-leads.csv';
    anchor.click();
    URL.revokeObjectURL(url);
  }
  async function saveLead(lead: PipelineLead) {
    if (
      lead.location_id !== null &&
      !locations.some((item) => item.id === lead.location_id && item.active)
    )
      throw Error(
        'Choose an active location, or leave the enquiry unassigned.',
      );
    if (
      lead.name !== selected?.name &&
      (!lead.name?.trim() || lead.name.trim().length > 128)
    )
      throw Error('Enter a contact name between 1 and 128 characters.');
    if (
      lead.callback_number !== selected?.callback_number &&
      !/^\+[1-9]\d{7,14}$/.test(lead.callback_number ?? '')
    )
      throw Error(
        'Use an international callback number, for example +12025550123.',
      );
    const payload = {
      revision: lead.revision,
      ...(lead.name !== selected?.name ? { contact_name: lead.name } : {}),
      ...(lead.callback_number !== selected?.callback_number
        ? { callback_number: lead.callback_number }
        : {}),
      stage: lead.stage,
      assignee: lead.assignee,
      next_action_at: lead.next_action_at,
      notes: lead.notes,
      location_id: lead.location_id,
    };
    const updated = demo
      ? {
          ...lead,
          revision: lead.revision + 1,
          location_name:
            locations.find((location) => location.id === lead.location_id)
              ?.name ?? null,
        }
      : await write<PipelineLead>(`pipeline/${lead.call_id}`, payload, 'PATCH');
    setLeads((old) =>
      old.map((item) => (item.call_id === updated.call_id ? updated : item)),
    );
    setSelected(null);
    setMessage(
      demo
        ? 'Demo enquiry updated. No real record changed.'
        : 'Enquiry updated.',
    );
    if (!demo) setRefresh((value) => value + 1);
  }
  async function queueLead(
    lead: PipelineLead,
    destination: string,
    requestId: string,
  ) {
    if (
      !lead.location_id ||
      !locations.some((item) => item.id === lead.location_id && item.active)
    )
      throw Error(
        'Assign an active location and save before queuing a CRM hand-off.',
      );
    const entry = demo
      ? {
          id: Date.now(),
          contact_name: lead.name ?? '',
          contact_phone: lead.callback_number ?? '',
          call_id: lead.call_id,
          location_id: lead.location_id,
          location_name: lead.location_name ?? '',
          destination,
          status: 'queued',
          attempt_count: 0,
          error_code: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }
      : await write<Delivery>('integrations/deliveries', {
          call_id: lead.call_id,
          destination,
          client_request_id: requestId,
        });
    setDeliveries((old) =>
      old.some(
        (item) =>
          item.id === entry.id ||
          (demo &&
            item.call_id === entry.call_id &&
            item.destination === entry.destination),
      )
        ? old
        : [entry, ...old],
    );
    setSelected(null);
    setTab('integrations');
    setMessage(
      demo
        ? 'Demo hand-off queued. Nothing was sent.'
        : 'Contact queued. Review the delivery before sending.',
    );
    if (!demo) setRefresh((value) => value + 1);
  }
  async function sendDelivery(entry: Delivery) {
    setBusy(true);
    setMessage('');
    try {
      const updated = demo
        ? {
            ...entry,
            status: 'delivered',
            attempt_count: 1,
            updated_at: new Date().toISOString(),
          }
        : await write<Delivery>(`integrations/deliveries/${entry.id}/send`, {
            confirm_delivery: true,
            expected_attempt_count: entry.attempt_count,
          });
      setDeliveries((old) =>
        old.map((item) => (item.id === entry.id ? updated : item)),
      );
      setMessage(
        demo
          ? 'Simulated acknowledgement only. No external request was made.'
          : 'Delivery attempt recorded. Review its status; acknowledgement does not prove downstream work completed.',
      );
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="px-5 py-8 md:px-10 max-w-[1600px] mx-auto space-y-7">
      <div className="flex flex-wrap justify-between gap-5 items-start">
        <div>
          <p className="eyebrow">One group. Every enquiry.</p>
          <h1 className="text-3xl md:text-4xl tracking-tight mt-3">
            Turn conversations into care.
          </h1>
          <p className="text-muted-foreground mt-3 max-w-2xl">
            Give every enquiry a location, a next step, and someone responsible.
            Keep the call outcome separate from the business outcome.
          </p>
        </div>
        <Button variant="outline" onClick={refreshData} disabled={loading}>
          <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          Refresh
        </Button>
      </div>
      {demo && (
        <Notice>
          Interactive fictional workspace. Try assigning a location, moving an
          enquiry, and simulating a CRM hand-off. Changes last only while this
          workspace stays open; nothing is sent.
        </Notice>
      )}
      {message && <Notice>{message}</Notice>}
      <nav
        aria-label="Group workspace"
        className="flex gap-2 overflow-x-auto border-b pb-3"
      >
        {(
          [
            ['pipeline', 'Lead pipeline', ArrowUpRight],
            ['locations', 'Locations', Building2],
            ['integrations', 'CRM & automations', Plug],
            ['pilot', 'Pilot launch', ShieldCheck],
          ] as const
        ).map(([key, title, Icon]) => (
          <Button
            key={key}
            variant={tab === key ? 'default' : 'ghost'}
            onClick={() => setTab(key)}
            aria-current={tab === key ? 'page' : undefined}
          >
            <Icon size={16} />
            {title}
          </Button>
        ))}
      </nav>
      {tab === 'pipeline' && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {STAGES.map((stage) => (
              <div key={stage} className="rounded-2xl border bg-card p-5">
                <p className="text-xs text-muted-foreground">
                  {STAGE_NAMES[stage]}
                </p>
                <p className="text-3xl mt-3 tabular-nums">
                  {errors.pipeline ? '—' : (counts[stage] ?? 0)}
                </p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 items-center">
            <div className="w-full sm:w-56">
              <label className="sr-only" htmlFor="location-filter">
                Filter location
              </label>
              <select
                id="location-filter"
                className={selectClass}
                value={filter}
                onChange={(event) => {
                  setFilter(event.target.value);
                  setOffset(0);
                }}
              >
                <option value="all">All locations</option>
                <option value="unassigned">Unassigned inbox</option>
                {locations.map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.name}
                    {!location.active ? ' (inactive)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <Input
              className="sm:max-w-xs"
              aria-label="Search displayed enquiries"
              placeholder="Search this page…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Button
              className="sm:ml-auto"
              variant="outline"
              disabled={loading || !!errors.pipeline || !visible.length}
              onClick={download}
            >
              <Download size={15} />
              Export displayed leads
            </Button>
          </div>
          {errors.pipeline ? (
            <Notice>{errors.pipeline}</Notice>
          ) : loading ? (
            <output className="block py-12 text-muted-foreground">
              Loading your group pipeline…
            </output>
          ) : (
            <div className="flex gap-4 overflow-x-auto pb-4 snap-x">
              {STAGES.map((stage) => (
                <section
                  key={stage}
                  className="min-w-[245px] flex-1 rounded-2xl bg-muted/40 p-3 snap-start"
                >
                  <h2 className="text-sm font-medium px-2 py-3 flex justify-between gap-2">
                    {STAGE_NAMES[stage]}
                    <span className="text-muted-foreground">
                      {visible.filter((lead) => lead.stage === stage).length}
                    </span>
                  </h2>
                  <div className="space-y-3">
                    {visible
                      .filter((lead) => lead.stage === stage)
                      .map((lead) => (
                        <motion.button
                          type="button"
                          key={lead.call_id}
                          initial={reduced ? false : { opacity: 0, y: 5 }}
                          animate={{ opacity: 1, y: 0 }}
                          onClick={() => setSelected(lead)}
                          className="w-full text-left rounded-xl border bg-card p-4 shadow-sm hover:border-primary/50 focus-visible:outline-2 focus-visible:outline-primary"
                        >
                          <div className="flex justify-between gap-2">
                            <span className="font-medium">
                              {lead.name ?? 'Unnamed enquiry'}
                            </span>
                            <ArrowUpRight
                              size={15}
                              className="text-muted-foreground shrink-0"
                            />
                          </div>
                          <p className="text-xs text-muted-foreground mt-2">
                            Call #{lead.call_id}
                          </p>
                          <div className="mt-5 flex flex-wrap gap-2">
                            <Badge variant="outline">
                              {lead.location_name ?? 'Needs a location'}
                            </Badge>
                            {isOverdue(lead) && (
                              <Badge variant="destructive">
                                Follow-up overdue
                              </Badge>
                            )}
                          </div>
                          <p className="text-xs mt-4 text-muted-foreground">
                            {lead.assignee
                              ? `Owner: ${lead.assignee}`
                              : 'No owner assigned'}
                          </p>
                          {lead.next_action_at && (
                            <p className="text-xs mt-2 flex gap-1 items-center">
                              <Clock3 size={12} />
                              {new Date(lead.next_action_at).toLocaleString()}
                            </p>
                          )}
                        </motion.button>
                      ))}
                    {!visible.some((lead) => lead.stage === stage) && (
                      <p className="text-xs text-muted-foreground px-2 py-9 text-center">
                        No enquiries on this page
                      </p>
                    )}
                  </div>
                </section>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-3 justify-between items-center text-xs text-muted-foreground">
            <p>
              Showing {visible.length} of {demo ? scoped.length : total}{' '}
              matching enquiries. Search and export apply to this page. Stage
              totals cover the selected location.
            </p>
            {!demo && (
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={loading || offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 50))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={loading || offset + 50 >= total}
                  onClick={() => setOffset(offset + 50)}
                >
                  Next
                </Button>
              </div>
            )}
          </div>
        </>
      )}
      {tab === 'locations' && (
        <LocationManager
          demo={demo}
          locations={locations}
          error={errors.locations}
          onSave={(location) => {
            setLocations((old) =>
              old.some((item) => item.id === location.id)
                ? old.map((item) => (item.id === location.id ? location : item))
                : [...old, location],
            );
            if (!demo) setRefresh((value) => value + 1);
          }}
        />
      )}
      {tab === 'integrations' && (
        <div className="space-y-6">
          <div>
            <h2 className="text-2xl">Connect the next step.</h2>
            <p className="text-muted-foreground mt-2">
              Queue a contact from the pipeline, review its location, then
              explicitly send it. Clinical notes and transcripts are excluded.
            </p>
          </div>
          {errors.integrations && <Notice>{errors.integrations}</Notice>}
          <div className="grid md:grid-cols-2 gap-4">
            {destinations.map((destination) => (
              <article
                key={destination.destination}
                className="rounded-2xl border p-6 bg-card"
              >
                <div className="flex justify-between items-center">
                  <h3 className="text-xl">
                    {destination.destination === 'hubspot'
                      ? 'HubSpot'
                      : 'Zapier · Make · n8n'}
                  </h3>
                  <Badge
                    variant={destination.configured ? 'secondary' : 'outline'}
                  >
                    {demo
                      ? 'Demo connection'
                      : destination.configured
                        ? 'Configured'
                        : 'Setup needed'}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground mt-4">
                  {destination.detail}
                </p>
                <p className="text-xs mt-5 text-muted-foreground">
                  {destination.destination === 'hubspot'
                    ? 'Contact creation with delivery tracking. An uncertain result requires review before another attempt.'
                    : 'Receives a contact event with a location snapshot. Acknowledgement is not proof that the downstream CRM action completed.'}
                </p>
              </article>
            ))}
          </div>
          <h3 className="text-lg">Delivery history</h3>
          {errors.deliveries ? (
            <Notice>{errors.deliveries}</Notice>
          ) : deliveries.length ? (
            <div className="divide-y rounded-2xl border overflow-hidden">
              {deliveries.map((entry) => (
                <div
                  key={entry.id}
                  className="p-5 bg-card flex flex-wrap items-center justify-between gap-4"
                >
                  <div>
                    <p className="font-medium">
                      Call #{entry.call_id} →{' '}
                      {entry.destination === 'hubspot'
                        ? 'HubSpot'
                        : 'Automation'}
                    </p>
                    <p className="text-xs text-muted-foreground mt-2">
                      {entry.contact_name} · {entry.contact_phone}
                      <br />
                      {entry.location_name} · {entry.attempt_count} attempt(s)
                    </p>
                    {entry.error_code && (
                      <p className="text-xs text-destructive mt-2">
                        {entry.error_code}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge
                      variant={
                        entry.status === 'uncertain' ? 'destructive' : 'outline'
                      }
                    >
                      {demo ? 'Demo: ' : ''}
                      {entry.status}
                    </Badge>
                    {entry.status === 'queued' && (
                      <Button
                        size="sm"
                        disabled={
                          busy ||
                          (!demo &&
                            !destinations.find(
                              (item) => item.destination === entry.destination,
                            )?.configured)
                        }
                        onClick={() => {
                          if (
                            demo ||
                            window.confirm(
                              `Send ${entry.contact_name} (${entry.contact_phone}), the queued contact for call #${entry.call_id} at ${entry.location_name} to ${entry.destination}? This shares contact details externally.`,
                            )
                          )
                            void sendDelivery(entry);
                        }}
                      >
                        {demo ? 'Simulate receipt' : 'Send queued contact'}
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-2xl border border-dashed p-10 text-center text-muted-foreground">
              <Plug className="mx-auto mb-3" />
              <p>No CRM hand-offs yet.</p>
              <p className="text-sm mt-2">
                Assign a location to an enquiry, then queue it from the
                pipeline.
              </p>
            </div>
          )}
          {!demo && (
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={loading || deliveryPage === 0}
                onClick={() => setDeliveryPage(Math.max(0, deliveryPage - 25))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={loading || deliveryPage + 25 >= deliveryTotal}
                onClick={() => setDeliveryPage(deliveryPage + 25)}
              >
                Next
              </Button>
            </div>
          )}
          <Notice>
            Queued is not delivered. A lost response may mean the receiver
            accepted the contact; uncertain deliveries are never blindly resent.
            Location changes do not rewrite an existing delivery snapshot.
          </Notice>
        </div>
      )}
      {tab === 'pilot' && (
        <PilotLaunch
          demo={demo}
          pilot={pilot}
          error={errors.pilot}
          locations={locations}
          leads={leads}
        />
      )}
      {selected && (
        <LeadEditor
          key={selected.call_id}
          lead={selected}
          locations={locations}
          destinations={destinations}
          demo={demo}
          onClose={() => setSelected(null)}
          onSave={saveLead}
          onQueue={queueLead}
        />
      )}
    </div>
  );
}
function LeadEditor({
  lead,
  locations,
  destinations,
  demo,
  onClose,
  onSave,
  onQueue,
}: {
  lead: PipelineLead;
  locations: Location[];
  destinations: Destination[];
  demo: boolean;
  onClose: () => void;
  onSave: (lead: PipelineLead) => Promise<void>;
  onQueue: (
    lead: PipelineLead,
    destination: string,
    id: string,
  ) => Promise<void>;
}) {
  const [draft, setDraft] = useState(lead);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [destination, setDestination] = useState('hubspot');
  const requestIds = useRef<Record<string, string>>({});
  const locked = /refresh|may have been saved/i.test(error);
  const dirty = JSON.stringify(draft) !== JSON.stringify(lead);
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (failure) {
      setError(errorText(failure));
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
        className="max-h-[90dvh] overflow-y-auto sm:max-w-lg p-6 md:p-8"
      >
        <div className="flex justify-between items-start gap-3">
          <div>
            <p className="eyebrow">Enquiry #{lead.call_id}</p>
            <DialogTitle className="text-2xl mt-3">
              {lead.name ?? 'Unnamed enquiry'}
            </DialogTitle>
            <p className="text-sm text-muted-foreground mt-2">
              {lead.callback_number ?? 'No callback number recorded'}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close enquiry"
            onClick={onClose}
            disabled={busy}
          >
            <X size={19} />
          </Button>
        </div>
        <form
          className="space-y-5 mt-8"
          onSubmit={(event) => {
            event.preventDefault();
            void act(() => onSave(draft));
          }}
        >
          <div className="space-y-2">
            <label htmlFor="lead-contact-name" className="text-sm">
              Contact name
            </label>
            <Input
              id="lead-contact-name"
              value={draft.name ?? ''}
              maxLength={128}
              onChange={(event) =>
                setDraft({ ...draft, name: event.target.value })
              }
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="lead-contact-phone" className="text-sm">
              Callback number
            </label>
            <Input
              id="lead-contact-phone"
              type="tel"
              value={draft.callback_number ?? ''}
              onChange={(event) =>
                setDraft({ ...draft, callback_number: event.target.value })
              }
              placeholder="+12025550123"
            />
            <p className="text-xs text-muted-foreground">
              For CRM delivery, include + and the country code. Confirm the
              number with the caller.
            </p>
          </div>
          <label className="block text-sm">
            Location
            <select
              className={`${selectClass} mt-2`}
              value={draft.location_id ?? ''}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  location_id: event.target.value
                    ? Number(event.target.value)
                    : null,
                })
              }
            >
              <option value="">Unassigned</option>
              {locations
                .filter((item) => item.active || item.id === draft.location_id)
                .map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.active}>
                    {item.name}
                    {!item.active ? ' (inactive)' : ''}
                  </option>
                ))}
            </select>
          </label>
          <label className="block text-sm">
            Business stage
            <select
              className={`${selectClass} mt-2`}
              value={draft.stage}
              onChange={(event) =>
                setDraft({ ...draft, stage: event.target.value })
              }
            >
              {STAGES.map((stage) => (
                <option key={stage} value={stage}>
                  {STAGE_NAMES[stage]}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="lead-owner" className="block text-sm">
            Staff owner
            <Input
              id="lead-owner"
              className="mt-2"
              value={draft.assignee ?? ''}
              maxLength={128}
              placeholder="Name or team"
              onChange={(event) =>
                setDraft({ ...draft, assignee: event.target.value || null })
              }
            />
          </label>
          <label htmlFor="lead-next-action" className="block text-sm">
            Next action (your local time)
            <Input
              id="lead-next-action"
              className="mt-2"
              type="datetime-local"
              value={
                draft.next_action_at
                  ? new Date(
                      Date.parse(draft.next_action_at) -
                        new Date(draft.next_action_at).getTimezoneOffset() *
                          60000,
                    )
                      .toISOString()
                      .slice(0, 16)
                  : ''
              }
              onChange={(event) =>
                setDraft({
                  ...draft,
                  next_action_at: event.target.value
                    ? new Date(event.target.value).toISOString()
                    : null,
                })
              }
            />
          </label>
          <label className="block text-sm">
            Staff notes
            <textarea
              className="mt-2 w-full rounded-lg border bg-background p-3 min-h-28"
              maxLength={2000}
              value={draft.notes}
              onChange={(event) =>
                setDraft({ ...draft, notes: event.target.value })
              }
            />
          </label>
          {error && <Notice>{error}</Notice>}
          <Button type="submit" disabled={busy || locked}>
            {busy ? 'Saving…' : demo ? 'Update demo enquiry' : 'Save enquiry'}
          </Button>
        </form>
        <div className="mt-8 pt-6 border-t space-y-4">
          <h3 className="font-medium">CRM hand-off</h3>
          <p className="text-sm text-muted-foreground">
            Queues only contact details and a fixed location reference. Save
            your changes first. This does not book an appointment or send a
            patient message.
          </p>
          <select
            aria-label="CRM destination"
            className={selectClass}
            value={destination}
            onChange={(event) => setDestination(event.target.value)}
          >
            {destinations.map((item) => (
              <option key={item.destination} value={item.destination}>
                {item.destination === 'hubspot'
                  ? 'HubSpot'
                  : 'Automation webhook'}
                {!item.configured ? ' (not configured)' : ''}
              </option>
            ))}
          </select>
          <Button
            variant="outline"
            disabled={
              busy ||
              locked ||
              dirty ||
              !lead.location_id ||
              !lead.callback_number ||
              !destinations.find((item) => item.destination === destination)
                ?.configured
            }
            onClick={() => {
              requestIds.current[destination] ??= crypto.randomUUID();
              void act(() =>
                onQueue(lead, destination, requestIds.current[destination]),
              );
            }}
          >
            <Plug size={15} />
            {demo ? 'Simulate CRM queue' : 'Queue contact for CRM'}
          </Button>
          {dirty && (
            <p className="text-xs text-muted-foreground">
              Save or discard the unsaved edits before queuing.
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
function LocationManager({
  demo,
  locations,
  error,
  onSave,
}: {
  demo: boolean;
  locations: Location[];
  error?: string;
  onSave: (location: Location) => void;
}) {
  const [editing, setEditing] = useState<Location | null>(null);
  const [name, setName] = useState('');
  const [zone, setZone] = useState('America/Los_Angeles');
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  async function save() {
    setBusy(true);
    setProblem('');
    try {
      if (!name.trim()) throw Error('Enter a location name.');
      try {
        new Intl.DateTimeFormat('en', { timeZone: zone }).format();
      } catch {
        throw Error('Use a valid IANA time zone, such as America/Los_Angeles.');
      }
      const payload = {
        name: name.trim(),
        timezone: zone,
        active,
        ...(editing ? { revision: editing.revision } : {}),
      };
      const value = demo
        ? {
            id: editing?.id ?? Date.now(),
            name,
            timezone: zone,
            active,
            revision: (editing?.revision ?? 0) + 1,
            updated_at: new Date().toISOString(),
          }
        : await write<Location>(
            editing ? `locations/${editing.id}` : 'locations',
            payload,
            editing ? 'PATCH' : 'POST',
          );
      onSave(value);
      setEditing(null);
      setName('');
    } catch (failure) {
      setProblem(errorText(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="grid lg:grid-cols-[1.3fr_1fr] gap-8">
      <div>
        <h2 className="text-2xl">A place for every enquiry.</h2>
        <p className="text-muted-foreground mt-3 mb-6">
          Group staff share this workspace. Locations organize work; they do not
          create separate access permissions.
        </p>
        {error && <Notice>{error}</Notice>}
        <div className="space-y-3">
          {locations.map((location) => (
            <article
              key={location.id}
              className="rounded-2xl border p-5 flex justify-between items-center gap-4 bg-card"
            >
              <div>
                <h3 className="font-medium flex items-center gap-2">
                  <Building2 size={17} />
                  {location.name}
                </h3>
                <p className="text-sm text-muted-foreground mt-2">
                  {location.timezone} ·{' '}
                  {location.active ? 'Active' : 'Inactive'}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditing(location);
                  setName(location.name);
                  setZone(location.timezone);
                  setActive(location.active);
                  setProblem('');
                }}
              >
                Edit
              </Button>
            </article>
          ))}
          {!locations.length && !error && (
            <p className="rounded-xl border border-dashed p-8 text-muted-foreground">
              Add your first clinic location to begin assigning enquiries.
            </p>
          )}
        </div>
      </div>
      <form
        className="rounded-2xl border p-6 bg-card h-fit space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <h3 className="text-lg">
          {editing ? 'Edit location' : 'Add a clinic location'}
        </h3>
        <label htmlFor="location-name" className="block text-sm">
          Location name
          <Input
            id="location-name"
            className="mt-2"
            required
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label htmlFor="location-zone" className="block text-sm">
          Time zone
          <Input
            id="location-zone"
            className="mt-2"
            required
            value={zone}
            onChange={(event) => setZone(event.target.value)}
            placeholder="America/Los_Angeles"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(event) => setActive(event.target.checked)}
          />
          Active for new assignments
        </label>
        {problem && <Notice>{problem}</Notice>}
        <div className="flex gap-2">
          <Button
            disabled={busy || /refresh|may have been saved/i.test(problem)}
            type="submit"
          >
            <Plus size={15} />
            {busy ? 'Saving…' : editing ? 'Save location' : 'Add location'}
          </Button>
          {editing && (
            <Button
              variant="ghost"
              type="button"
              onClick={() => {
                setEditing(null);
                setName('');
                setActive(true);
                setProblem('');
              }}
            >
              Cancel
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Enquiries arrive unassigned until staff choose a location.
          Number-based automatic routing is not enabled by adding a location.
        </p>
      </form>
    </div>
  );
}
function PilotLaunch({
  demo,
  pilot,
  error,
  locations,
  leads,
}: {
  demo: boolean;
  pilot: Pilot | null;
  error?: string;
  locations: Location[];
  leads: PipelineLead[];
}) {
  const checks = demo
    ? [
        {
          id: 'locations',
          label: 'Clinic locations',
          status: locations.some((item) => item.active) ? 'ready' : 'blocked',
          detail: 'Fictional locations for exploring the group workflow.',
        },
        {
          id: 'assignments',
          label: 'Enquiry ownership',
          status: leads.some((item) => !item.location_id) ? 'blocked' : 'ready',
          detail: 'Assign the unassigned demo enquiry to a location.',
        },
        {
          id: 'crm',
          label: 'CRM hand-off',
          status: 'unknown',
          detail:
            'Demo connections simulate a queue. A real account must be configured and tested.',
        },
        {
          id: 'voice',
          label: 'Observed phone trial',
          status: 'unknown',
          detail:
            'A coordinator must confirm the real call and transfer outcome.',
        },
      ]
    : (pilot?.checks ?? []);
  return (
    <div className="max-w-4xl space-y-6">
      <div className="rounded-2xl border bg-card p-7">
        <p className="eyebrow">Controlled rollout</p>
        <h2 className="text-3xl mt-3">Earn the next location.</h2>
        <p className="text-muted-foreground mt-3">
          Start with a controlled trial at one location, verify the call and CRM
          outcome with staff, then expand across the group. Configuration checks
          are not proof of production readiness.
        </p>
        <div className="flex flex-wrap gap-2 mt-5">
          <Badge variant="outline">One dental group</Badge>
          <Badge variant="outline">Shared staff access</Badge>
          <Badge variant="outline">Human-observed acceptance</Badge>
        </div>
      </div>
      {error && <Notice>{error}</Notice>}
      <div className="divide-y border rounded-2xl overflow-hidden">
        {checks.map((check) => (
          <article key={check.id} className="flex gap-4 p-5 bg-card">
            {check.status === 'ready' ? (
              <CheckCircle2 className="text-primary shrink-0" size={20} />
            ) : (
              <AlertTriangle className="text-amber-600 shrink-0" size={20} />
            )}
            <div>
              <div className="flex items-center flex-wrap gap-3">
                <h3 className="font-medium">{check.label}</h3>
                <Badge variant="outline">
                  {check.status === 'unknown'
                    ? 'Needs verification'
                    : check.status}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground mt-2">
                {check.detail}
              </p>
            </div>
          </article>
        ))}
      </div>
      {!demo && !pilot && !error && <p>Loading launch checks…</p>}
      <Notice>
        A booked consultation or converted enquiry is a staff-recorded business
        outcome. It is not proof of payment, a calendar reservation, or a
        human-answered phone transfer.
      </Notice>
    </div>
  );
}
