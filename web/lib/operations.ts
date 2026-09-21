export type Check = {
  id: string;
  label: string;
  status: 'ready' | 'blocked' | 'unknown';
  detail: string;
};
export type OperationsData = {
  checked_at: string;
  readiness: {
    ready: boolean;
    prompt_version: string;
    issues: { name: string; reason: string }[];
    checks: Check[];
  };
  database: { available: boolean };
  summary: {
    recent_calls: number;
    abandoned_calls: number;
    incomplete_calls: number;
  } | null;
  recent_failures: {
    id: number;
    started_at: string | null;
    outcome: string | null;
  }[];
};
function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
const count = (value: unknown) =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
export function parseOperations(value: unknown): OperationsData {
  const fail = () => {
    throw new Error(
      'The operations response could not be verified. Refresh to try again.',
    );
  };
  if (
    !object(value) ||
    typeof value.checked_at !== 'string' ||
    !Number.isFinite(Date.parse(value.checked_at))
  )
    return fail();
  const r = value.readiness,
    db = value.database,
    s = value.summary;
  if (
    !object(r) ||
    typeof r.ready !== 'boolean' ||
    typeof r.prompt_version !== 'string' ||
    !Array.isArray(r.issues) ||
    !Array.isArray(r.checks) ||
    !r.checks.length ||
    !object(db) ||
    typeof db.available !== 'boolean'
  )
    return fail();
  if (
    !r.issues.every(
      (i) =>
        object(i) && typeof i.name === 'string' && typeof i.reason === 'string',
    ) ||
    !r.checks.every(
      (c) =>
        object(c) &&
        typeof c.id === 'string' &&
        typeof c.label === 'string' &&
        typeof c.detail === 'string' &&
        ['ready', 'blocked', 'unknown'].includes(String(c.status)),
    )
  )
    return fail();
  if (
    s !== null &&
    (!object(s) ||
      !count(s.recent_calls) ||
      !count(s.abandoned_calls) ||
      !count(s.incomplete_calls))
  )
    return fail();
  if (!db.available && (s !== null || r.ready)) return fail();
  if (
    r.ready &&
    (r.issues.length ||
      r.checks.some((c) => object(c) && c.status === 'blocked'))
  )
    return fail();
  if (
    !Array.isArray(value.recent_failures) ||
    !value.recent_failures.every(
      (c) =>
        object(c) &&
        count(c.id) &&
        (c.started_at === null || typeof c.started_at === 'string') &&
        (c.outcome === null || typeof c.outcome === 'string'),
    )
  )
    return fail();
  return value as OperationsData;
}
export function demoOperations(
  mode: 'setup' | 'ready' | 'outage',
): OperationsData {
  const blocked = mode === 'setup',
    outage = mode === 'outage';
  return {
    checked_at: '2026-09-21T10:30:00Z',
    database: { available: !outage },
    summary: outage
      ? null
      : { recent_calls: 24, abandoned_calls: 3, incomplete_calls: 1 },
    recent_failures: outage
      ? []
      : [
          {
            id: 1042,
            started_at: '2026-09-21T10:12:00Z',
            outcome: 'abandoned',
          },
          { id: 1040, started_at: '2026-09-21T09:47:00Z', outcome: null },
        ],
    readiness: {
      ready: !blocked && !outage,
      prompt_version: blocked ? 'v1' : 'v2',
      issues: blocked
        ? [
            { name: 'system', reason: 'placeholder' },
            { name: 'greeting', reason: 'placeholder' },
          ]
        : [],
      checks: [
        {
          id: 'prompts',
          label: 'Conversation prompts',
          status: blocked ? 'blocked' : 'ready',
          detail: blocked
            ? 'Draft prompts still contain owner placeholders.'
            : 'Required prompt files pass structural checks.',
        },
        {
          id: 'speech',
          label: 'Speech services',
          status: 'ready',
          detail: 'Recognition and synthesis credentials are configured.',
        },
        {
          id: 'model',
          label: 'Language model',
          status: 'ready',
          detail: 'Model credentials are configured.',
        },
        {
          id: 'database',
          label: 'Call records',
          status: outage ? 'blocked' : 'ready',
          detail: outage
            ? 'The database is unavailable. Call counts are unknown.'
            : 'The database responded to this check.',
        },
        {
          id: 'vendor_connectivity',
          label: 'Live call validation',
          status: 'unknown',
          detail:
            'Vendor connectivity and real-call behavior have not been probed.',
        },
      ],
    },
  };
}
export function reportOperations(data: OperationsData): string {
  return [
    'ArcAgent operations check',
    `Checked: ${data.checked_at}`,
    `Configuration: ${data.readiness.ready ? 'configured' : 'needs attention'}`,
    `Prompt version: ${data.readiness.prompt_version}`,
    `Recent calls: ${data.summary?.recent_calls ?? 'Unavailable'}`,
    ...data.readiness.checks.map((c) => `${c.id}: ${c.status} - ${c.detail}`),
    'Configuration checks do not establish live-call readiness.',
  ].join('\n');
}
export const recoveryGuides = [
  {
    id: 'prompts',
    title: 'Conversation cannot start',
    text: 'Review the prompt findings, complete a new approved prompt version, then restart the backend. Run the offline preflight before enabling a controlled call. Removing a placeholder marker alone does not validate wording.',
  },
  {
    id: 'connection',
    title: 'Workspace or database is unavailable',
    text: 'Check the backend connection, service health, and database access. Retry this read-only check after recovery. Missing counts mean unknown, not zero. Do not substitute sample records for live calls.',
  },
  {
    id: 'playback',
    title: 'A call ended before completion',
    text: 'Review the conversation and interruption markers. Missing playback acknowledgements or failed speech generation stop the session. Reproduce with an isolated audio evaluation before changing turn settings.',
  },
  {
    id: 'routing',
    title: 'Callback or handoff needs review',
    text: 'Confirm the persisted booking and provider status before retrying an action. A submitted transfer is not proof that a coordinator answered. Never automatically resend an ambiguous SMS or transfer.',
  },
];
