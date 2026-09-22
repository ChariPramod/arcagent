import test from 'node:test';
import assert from 'node:assert/strict';
import { read, write } from './client.ts';
void test('a non-JSON outage produces a usable fallback message', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response('<html>private upstream traceback</html>', { status: 502 });
  try {
    await assert.rejects(read('operations'), /could not load/i);
  } finally {
    globalThis.fetch = original;
  }
});
void test('a stalled request is bounded and reports timeout', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (_url, init) =>
    new Promise((_resolve, reject) =>
      init?.signal?.addEventListener('abort', () =>
        reject(new DOMException('aborted', 'AbortError')),
      ),
    );
  try {
    await assert.rejects(read('operations', undefined, 5), /timed out/i);
  } finally {
    globalThis.fetch = original;
  }
});

void test('a lost write response is uncertain and never automatically retried', async () => {
  const original = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = async () => {
    attempts++;
    throw Error('network');
  };
  try {
    await assert.rejects(
      write('followups', { call_id: 1 }),
      /may have been saved/,
    );
    assert.equal(attempts, 1);
  } finally {
    globalThis.fetch = original;
  }
});
void test('conflict and validation failures have distinct recovery instructions', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () =>
      Response.json({ detail: 'conflict' }, { status: 409 });
    await assert.rejects(
      write('followups/1', { revision: 1 }, 'PATCH'),
      /record changed.*Refresh/,
    );
    globalThis.fetch = async () =>
      Response.json({ detail: [] }, { status: 422 });
    await assert.rejects(
      write('feedback', {}),
      /required fields.*not accepted/,
    );
  } finally {
    globalThis.fetch = original;
  }
});
