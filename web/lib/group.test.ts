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
