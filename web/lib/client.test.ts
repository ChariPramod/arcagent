import test from 'node:test';
import assert from 'node:assert/strict';
import { read } from './client.ts';
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
