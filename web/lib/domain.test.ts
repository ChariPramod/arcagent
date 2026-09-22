import test from 'node:test';
import assert from 'node:assert/strict';
import { duration, percent, filterCalls, type CallSummary } from './domain.ts';
const calls: CallSummary[] = [
  {
    id: 1,
    name: 'Nora Ellis',
    started_at: '2026-09-08T09:00:00Z',
    duration_s: null,
    outcome: 'handoff',
    language: 'en',
    treatment_interest: 'full_arch',
    score: 65,
    threshold: 60,
  },
  {
    id: 2,
    name: null,
    started_at: null,
    duration_s: 0,
    outcome: null,
    language: 'en',
    treatment_interest: null,
    score: null,
    threshold: null,
  },
];
void test('missing measurements stay distinct from zero', () => {
  assert.equal(percent(null), 'Not measured');
  assert.equal(percent(0), '0%');
  assert.equal(duration(null), 'Not recorded');
  assert.equal(duration(0), '0:00');
  assert.equal(duration(59.9), '1:00');
});
void test('combined filters support case, whitespace, ids, and missing fields', () => {
  assert.deepEqual(filterCalls(calls, ' NORA ', 'handoff', '2026-09-08'), [
    calls[0],
  ]);
  assert.deepEqual(filterCalls(calls, '2', 'all', ''), [calls[1]]);
  assert.deepEqual(filterCalls(calls, '', 'callback_booked', ''), []);
  assert.deepEqual(filterCalls(calls, '', 'all', '2026-09-07'), []);
});

import { transferDescription, type TransferEvidence } from './domain.ts';
void test('transfer copy requires positive bridge evidence and preserves uncertainty', () => {
  const transfer: TransferEvidence = {
    request_status: 'accepted',
    outcome: null,
    connection_confirmed: false,
    human_identity_verified: false,
    created_at: '',
    updated_at: '',
    resolved_at: null,
    latest_progress: null,
    timing_basis: 'server_observed',
  };
  assert.equal(transferDescription(transfer), 'Awaiting connection evidence');
  assert.equal(
    transferDescription({ ...transfer, request_status: 'uncertain' }),
    'Transfer result uncertain',
  );
  assert.equal(
    transferDescription({
      ...transfer,
      outcome: 'completed',
      connection_confirmed: true,
    }),
    'Call bridge confirmed',
  );
  assert.notEqual(
    transferDescription({ ...transfer, outcome: 'completed' }),
    'Call bridge confirmed',
  );
});
