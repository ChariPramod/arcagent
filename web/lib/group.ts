export const STAGES = ['new', 'contacted', 'booked', 'won', 'lost'] as const;
export const STAGE_NAMES: Record<string, string> = {
  new: 'New enquiry',
  contacted: 'In conversation',
  booked: 'Consultation booked',
  won: 'Converted',
  lost: 'Closed / lost',
};
export type Location = {
  id: number;
  name: string;
  timezone: string;
  active: boolean;
  revision: number;
  updated_at: string | null;
};
export type PipelineLead = {
  call_id: number;
  lead_id: number;
  name: string | null;
  callback_number: string | null;
  started_at: string | null;
  call_outcome: string | null;
  stage: string;
  assignee: string | null;
  next_action_at: string | null;
  notes: string;
  revision: number;
  updated_at: string | null;
  location_id: number | null;
  location_name: string | null;
};
export type PipelinePage = {
  items: PipelineLead[];
  total: number;
  limit: number;
  offset: number;
  summary: Record<string, number>;
  scope: string;
};
export type Destination = {
  destination: 'hubspot' | 'automation';
  configured: boolean;
  detail: string;
};
export type DeliveryReview = {
  id: number;
  delivery_id: number;
  provider_status: string;
  attempt_count: number;
  review_revision: number;
  resolution: 'verified_received' | 'verified_not_received' | 'needs_followup';
  evidence: string;
  created_by: string;
  created_at: string;
};
export type ActivityEvent = {
  id: number;
  entity: string;
  entity_id: number;
  revision: number;
  actor: string;
  action: string;
  changes: Record<string, string | number | boolean | null>;
  fields_changed: string[];
  created_at: string;
};
export const REVIEW_LABELS = {
  verified_received: 'Operator reports received',
  verified_not_received: 'Operator reports not received',
  needs_followup: 'Further investigation needed',
};
export function matchesContactSearch(
  lead: PipelineLead,
  query: string,
): boolean {
  const text = query.trim().toLowerCase();
  if (/^[1-9]$/.test(text)) return lead.call_id === Number(text);
  return (
    !text ||
    (lead.name ?? '').toLowerCase().includes(text) ||
    (lead.callback_number ?? '').toLowerCase().includes(text) ||
    (/^[0-9]+$/.test(text) && Number(text) === lead.call_id)
  );
}

export type Delivery = {
  review_revision: number;
  latest_review?: DeliveryReview | null;
  contact_name: string;
  contact_phone: string;
  id: number;
  call_id: number;
  location_id: number;
  location_name: string;
  destination: string;
  status: string;
  attempt_count: number;
  error_code: string | null;
  updated_at: string;
  created_at: string;
};
export type Pilot = {
  checked_at: string;
  configuration_ready: boolean;
  live_validation: string;
  scope: {
    workspace: string;
    authorization: string;
    location_isolation: boolean;
  };
  checks: { id: string; label: string; status: string; detail: string }[];
  summary: {
    active_locations: number;
    unassigned_leads: number;
    crm_deliveries_pending: number;
    crm_deliveries_uncertain: number;
  } | null;
  database: { available: boolean };
};
export type DueFilter = 'all' | 'overdue' | 'scheduled' | 'unscheduled';
export type OwnerFilter = 'all' | 'unassigned';
export function matchesWorkFilters(
  lead: PipelineLead,
  due: DueFilter,
  owner: OwnerFilter,
  now = Date.now(),
): boolean {
  if (owner === 'unassigned' && lead.assignee?.trim()) return false;
  if (due === 'all') return true;
  if (lead.stage === 'won' || lead.stage === 'lost') return false;
  if (due === 'unscheduled') return lead.next_action_at === null;
  const time = lead.next_action_at ? Date.parse(lead.next_action_at) : NaN;
  return (
    Number.isFinite(time) && (due === 'overdue' ? time < now : time >= now)
  );
}

export function isOverdue(lead: PipelineLead, now = Date.now()): boolean {
  return (
    !['won', 'lost'].includes(lead.stage) &&
    !!lead.next_action_at &&
    Date.parse(lead.next_action_at) < now
  );
}
type CsvValue = string | number | null | undefined;
function csvCell(value: CsvValue): string {
  let text = String(value ?? '');
  // oxlint-disable-next-line no-control-regex -- Neutralize formulas after control characters in CSV cells.
  if (/^[\s\u0000-\u001f]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text))
    text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
export function exportLeads(leads: PipelineLead[]): string {
  const rows: CsvValue[][] = [
    [
      'Call ID',
      'Contact',
      'Phone',
      'Location',
      'Stage',
      'Assignee',
      'Next action UTC',
    ],
  ];
  for (const lead of leads)
    rows.push([
      lead.call_id,
      lead.name,
      lead.callback_number,
      lead.location_name ?? 'Unassigned',
      STAGE_NAMES[lead.stage] ?? lead.stage,
      lead.assignee,
      lead.next_action_at,
    ]);
  return '\ufeff' + rows.map((row) => row.map(csvCell).join(',')).join('\r\n');
}
export const exampleLocations: Location[] = [
  {
    id: 1,
    name: 'Downtown Dental',
    timezone: 'America/Los_Angeles',
    active: true,
    revision: 1,
    updated_at: null,
  },
  {
    id: 2,
    name: 'Northside Dental',
    timezone: 'America/Los_Angeles',
    active: true,
    revision: 1,
    updated_at: null,
  },
  {
    id: 3,
    name: 'Lakeside Dental',
    timezone: 'America/Chicago',
    active: true,
    revision: 1,
    updated_at: null,
  },
];
export const exampleLeads: PipelineLead[] = [
  {
    call_id: 1042,
    lead_id: 1,
    name: 'Nora Ellis',
    callback_number: '+12025550123',
    started_at: null,
    call_outcome: 'handoff',
    stage: 'new',
    assignee: null,
    next_action_at: null,
    notes: 'Confirm the preferred consultation time.',
    revision: 0,
    updated_at: null,
    location_id: null,
    location_name: null,
  },
  {
    call_id: 1041,
    lead_id: 2,
    name: 'Miles Carter',
    callback_number: '+12025550146',
    started_at: null,
    call_outcome: 'callback',
    stage: 'contacted',
    assignee: 'Jamie',
    next_action_at: '2026-09-01T16:00:00Z',
    notes: 'Prefers an afternoon conversation.',
    revision: 1,
    updated_at: null,
    location_id: 1,
    location_name: 'Downtown Dental',
  },
  {
    call_id: 1040,
    lead_id: 3,
    name: 'Leah Brooks',
    callback_number: '+12025550158',
    started_at: null,
    call_outcome: 'callback',
    stage: 'booked',
    assignee: 'Taylor',
    next_action_at: '2027-12-01T16:00:00Z',
    notes: 'Consultation arranged by the coordinator.',
    revision: 2,
    updated_at: null,
    location_id: 2,
    location_name: 'Northside Dental',
  },
  {
    call_id: 1039,
    lead_id: 4,
    name: 'Avery Reed',
    callback_number: '+12025550162',
    started_at: null,
    call_outcome: 'handoff',
    stage: 'won',
    assignee: 'Jamie',
    next_action_at: null,
    notes: 'Outcome confirmed by staff.',
    revision: 3,
    updated_at: null,
    location_id: 1,
    location_name: 'Downtown Dental',
  },
  {
    call_id: 1038,
    lead_id: 5,
    name: 'Robin Hayes',
    callback_number: '+12025550175',
    started_at: null,
    call_outcome: 'abandoned',
    stage: 'lost',
    assignee: null,
    next_action_at: null,
    notes: 'No longer pursuing an appointment.',
    revision: 1,
    updated_at: null,
    location_id: 3,
    location_name: 'Lakeside Dental',
  },
];
