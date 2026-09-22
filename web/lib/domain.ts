export type CallSummary = {
  id: number;
  name: string | null;
  started_at: string | null;
  duration_s: number | null;
  outcome: string | null;
  language: string;
  treatment_interest: string | null;
  score: number | null;
  threshold: number | null;
};
export type Turn = {
  id: number;
  speaker: string;
  text: string;
  started_at: string | null;
  node: string | null;
  interrupted: boolean;
  latency: Record<string, number | null>;
};
export type TransferEvidence = {
  request_status: string;
  outcome: string | null;
  connection_confirmed: boolean;
  human_identity_verified: false;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  latest_progress: {
    status: string;
    sequence: number;
    received_at: string;
  } | null;
  timing_basis: 'server_observed';
};
export function transferDescription(transfer: TransferEvidence): string {
  if (transfer.connection_confirmed && transfer.outcome === 'completed')
    return 'Call bridge confirmed';
  if (transfer.outcome)
    return `Transfer ${label(transfer.outcome).toLowerCase()}`;
  if (transfer.request_status === 'uncertain')
    return 'Transfer result uncertain';
  return 'Awaiting connection evidence';
}
export type CallDetail = CallSummary & {
  transfer?: TransferEvidence | null;
  fields: Record<string, unknown>;
  score_breakdown: Record<string, number>;
  decision: string | null;
  turns: Turn[];
};
export type EvalRun = {
  id: number;
  name: string;
  created_at: string | null;
  prompt_version: string;
  threshold: number;
  tier: string;
  git_sha: string;
  suite: string;
  results: number;
  scenarios: number;
  pass_rate: number | null;
  field_accuracy: number | null;
  handoff_recall: number | null;
  flaky: string[];
};
export type EvalResult = {
  id: number;
  scenario_id: string;
  group: string;
  repeat: number;
  passed: boolean;
  field_accuracy: number | null;
  expected: Record<string, unknown>;
  actual: Record<string, unknown>;
  transcript: { speaker: string; text: string }[] | null;
  notes: string | null;
};
export type EvalDetail = EvalRun & { items: EvalResult[] };
export type Comparison = {
  status: 'invalid' | 'regression' | 'clear';
  reason: string | null;
  metrics: {
    group: string;
    name: string;
    before: number;
    after: number;
    delta: number;
    guarded: boolean;
  }[];
  regressions: { group: string; name: string; delta: number }[];
};
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
export const outcomeLabels: Record<string, string> = {
  handoff: 'Handed off',
  callback_booked: 'Callback booked',
  abandoned: 'Ended early',
  wrong_number: 'Wrong number',
  not_a_lead: 'Not a lead',
  language_fallback: 'Language fallback',
};
export const ruleLabels: Record<string, string> = {
  full_arch_or_multiple: 'Full arch or multiple implants',
  single_implant: 'Single implant',
  pain_6_or_higher: 'Pain level of six or higher',
  considering_over_6_months: 'Considering for over six months',
  has_insurance: 'Has dental insurance',
  named_employer_or_plan: 'Employer or plan named',
  asked_about_financing: 'Asked about financing',
  unrecovered_price_objection: 'Unresolved price objection',
  just_looking_declined_callback: 'Browsing and declined callback',
};
export function label(value: string | null | undefined): string {
  if (!value) return 'Not recorded';
  return (
    outcomeLabels[value] ??
    value.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase())
  );
}
export function percent(value: number | null): string {
  return value === null ? 'Not measured' : `${Math.round(value * 100)}%`;
}
export function duration(value: number | null): string {
  if (value === null) return 'Not recorded';
  const seconds = Math.round(value);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
export function date(value: string | null): string {
  return value
    ? new Intl.DateTimeFormat('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'UTC',
      }).format(new Date(value))
    : 'Not recorded';
}
export function display(value: unknown): string {
  if (value === null || value === undefined || value === '')
    return 'Not recorded';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value))
    return value.length
      ? value
          .map((v) =>
            v && typeof v === 'object' && 'kind' in v
              ? display(v.kind)
              : display(v),
          )
          .join(', ')
      : 'None recorded';
  if (typeof value === 'object') return JSON.stringify(value);
  return typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'bigint'
    ? label(String(value))
    : 'Not recorded';
}
export function filterCalls(
  calls: CallSummary[],
  query: string,
  outcome: string,
  day: string,
): CallSummary[] {
  const needle = query.trim().toLowerCase();
  return calls.filter(
    (call) =>
      (!needle ||
        `${call.name ?? ''} ${call.treatment_interest ?? ''} ${call.id}`
          .toLowerCase()
          .includes(needle)) &&
      (outcome === 'all' || call.outcome === outcome) &&
      (!day || call.started_at?.slice(0, 10) === day),
  );
}
