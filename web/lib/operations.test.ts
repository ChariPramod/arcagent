import assert from 'node:assert/strict';
import test from 'node:test';
import {
  parseOperations,
  demoOperations,
  reportOperations,
} from './operations.ts';
import { hasTrustedSitesIdentity } from './auth-runtime.ts';
void test('native runtime does not trust incoming Sites identity headers', () => {
  assert.equal(hasTrustedSitesIdentity(), false);
});
void test('unknown metrics stay unavailable when the database is down', () => {
  const data = parseOperations(demoOperations('outage'));
  assert.equal(data.summary, null);
  assert.equal(data.readiness.ready, false);
  assert.match(reportOperations(data), /Unavailable/);
});
void test('malformed operational data never becomes a ready state', () => {
  assert.throws(() => parseOperations({ ready: true }));
  const data = demoOperations('ready');
  assert.throws(() =>
    parseOperations({
      ...data,
      summary: { recent_calls: -1, abandoned_calls: 0, incomplete_calls: 0 },
    }),
  );
  assert.throws(() =>
    parseOperations({
      ...data,
      readiness: {
        ...data.readiness,
        checks: [{ id: 'x', label: 'x', status: 'great', detail: 'x' }],
      },
    }),
  );
});
void test('report contains operational checks but not caller content', () => {
  const report = reportOperations(demoOperations('setup'));
  assert.match(report, /Configuration/);
  assert.match(report, /prompts/);
  assert.doesNotMatch(report, /callback_number|phone|patient/i);
});
