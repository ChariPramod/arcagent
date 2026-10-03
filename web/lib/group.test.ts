import test from 'node:test';
import assert from 'node:assert/strict';
import { exportLeads, isOverdue, type PipelineLead } from './group.ts';
const lead: PipelineLead = {
  call_id: 1,
  lead_id: 1,
  name: '=HYPERLINK("bad")',
  callback_number: '+15555550123',
  started_at: null,
  call_outcome: null,
  stage: 'new',
  assignee: null,
  next_action_at: '2026-01-01T00:00:00Z',
  notes: 'Private clinical detail',
  revision: 0,
  updated_at: null,
  location_id: null,
  location_name: null,
};
void test('lead export neutralizes spreadsheet formulas and omits clinical notes', () => {
  const csv = exportLeads([lead]);
  assert.ok(csv.includes('"\'=HYPERLINK(""bad"")"'));
  assert.ok(csv.includes('"\'+15555550123"'));
  assert.ok(!csv.includes('Private clinical'));
  assert.ok(csv.includes('Unassigned'));
});
void test('follow-up due state excludes closed outcomes and missing or invalid dates', () => {
  const now = Date.parse('2026-01-02T00:00:00Z');
  assert.equal(isOverdue(lead, now), true);
  for (const patch of [
    { stage: 'won' },
    { stage: 'lost' },
    { next_action_at: null },
    { next_action_at: 'invalid' },
  ])
    assert.equal(isOverdue({ ...lead, ...patch }, now), false);
});

void test('work filters identify overdue, scheduled, unowned and unscheduled open enquiries', async () => {
  const { matchesWorkFilters } = await import('./group.ts');
  const now = Date.parse('2026-10-02T12:00:00Z');
  const due = { ...lead, next_action_at: '2026-10-01T12:00:00Z' };
  assert.equal(matchesWorkFilters(due, 'overdue', 'unassigned', now), true);
  assert.equal(
    matchesWorkFilters({ ...due, stage: 'won' }, 'overdue', 'all', now),
    false,
  );
  assert.equal(
    matchesWorkFilters(
      { ...due, assignee: ' Jamie ' },
      'overdue',
      'unassigned',
      now,
    ),
    false,
  );
  assert.equal(
    matchesWorkFilters(
      { ...due, next_action_at: '2026-10-02T12:00:00Z' },
      'scheduled',
      'all',
      now,
    ),
    true,
  );
  assert.equal(
    matchesWorkFilters(
      { ...due, next_action_at: null },
      'unscheduled',
      'all',
      now,
    ),
    true,
  );
  assert.equal(
    matchesWorkFilters(
      { ...due, next_action_at: null, stage: 'lost' },
      'unscheduled',
      'all',
      now,
    ),
    false,
  );
  assert.equal(
    matchesWorkFilters(
      { ...due, next_action_at: 'invalid' },
      'scheduled',
      'all',
      now,
    ),
    false,
  );
});

void test('demo contact search matches names, phone numbers and exact single-digit IDs', async () => {
  const { matchesContactSearch } = await import('./group.ts');
  assert.equal(
    matchesContactSearch({ ...lead, name: 'Synthetic Ellis' }, 'ELLIS'),
    true,
  );
  assert.equal(matchesContactSearch(lead, '+155'), true);
  assert.equal(matchesContactSearch(lead, '1'), true);
  assert.equal(matchesContactSearch({ ...lead, call_id: 123 }, '1'), false);
  assert.equal(
    matchesContactSearch({ ...lead, name: 'Contact A' }, '%'),
    false,
  );
});
