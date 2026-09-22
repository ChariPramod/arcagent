import test from 'node:test';
import assert from 'node:assert/strict';
import { proxyConsole, type ConsoleConfig } from './proxy.ts';
const config: ConsoleConfig = {
  apiUrl: 'https://backend.example',
  token: 'test-server-secret',
  allowedUsers: 'owner',
};
const request = new Request(
  'https://site.example/api/console/calls?limit=50&injected=bad',
  { headers: { Cookie: 'private-cookie', Authorization: 'Bearer attacker' } },
);
const never: typeof fetch = async () => {
  throw Error('Upstream must not be contacted');
};
for (const [name, user, settings, status] of [
  ['unsigned', null, config, 401],
  ['unlisted', 'visitor', config, 403],
  ['unconfigured', 'owner', { ...config, allowedUsers: '' }, 503],
  ['missing token', 'owner', { ...config, token: '' }, 503],
  [
    'insecure url',
    'owner',
    { ...config, apiUrl: 'http://backend.example' },
    503,
  ],
] as const) {
  void test(name, async () => {
    const response = await proxyConsole(
      request,
      ['calls'],
      user,
      settings,
      never,
    );
    assert.equal(response.status, status);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  });
}
void test('only allowlisted routes and integer queries reach upstream', async () => {
  assert.equal(
    (await proxyConsole(request, ['admin'], 'owner', config, never)).status,
    404,
  );
  assert.equal(
    (
      await proxyConsole(
        new Request('https://site.example/?offset=-1'),
        ['calls'],
        'owner',
        config,
        never,
      )
    ).status,
    400,
  );
});
void test('proxy forwards server credential without browser headers or unknown query parameters', async () => {
  let reached = false;
  const transport: typeof fetch = async (input, init) => {
    reached = true;
    assert.equal(
      input instanceof Request ? input.url : input.toString(),
      'https://backend.example/api/console/calls?limit=50',
    );
    assert.deepEqual(init?.headers, {
      Authorization: 'Bearer test-server-secret',
      Accept: 'application/json',
    });
    assert.equal(init?.redirect, 'error');
    return Response.json({ items: [] });
  };
  const response = await proxyConsole(
    request,
    ['calls'],
    'owner',
    config,
    transport,
  );
  assert.equal(reached, true);
  assert.deepEqual(await response.json(), { items: [] });
  assert.equal(response.headers.get('cache-control'), 'no-store');
});
void test('upstream failures do not expose internal errors', async () => {
  for (const status of [401, 403, 500]) {
    const response = await proxyConsole(
      request,
      ['calls'],
      'owner',
      config,
      async () => Response.json({ detail: 'internal-secret' }, { status }),
    );
    assert.equal(response.status, 503);
    assert.ok(!(await response.text()).includes('internal-secret'));
  }
});
void test('local HTTP is explicitly opt-in and restricted to loopback', async () => {
  const response = await proxyConsole(
    request,
    ['calls'],
    'owner',
    { ...config, apiUrl: 'http://localhost:8000', allowLocal: true },
    async () => Response.json({ items: [] }),
  );
  assert.equal(response.status, 200);
  assert.equal(
    (
      await proxyConsole(
        request,
        ['calls'],
        'owner',
        { ...config, apiUrl: 'http://remote.example', allowLocal: true },
        never,
      )
    ).status,
    503,
  );
});
void test('operations is a read-only allowlisted route with server credentials', async () => {
  const transport: typeof fetch = async (url, init) => {
    assert.equal(
      url instanceof Request ? url.url : url.toString(),
      'https://backend.example/api/console/operations',
    );
    assert.equal(
      new Headers(init?.headers).get('Authorization'),
      'Bearer test-server-secret',
    );
    assert.equal(init?.redirect, 'error');
    return Response.json({ database: { available: false }, summary: null });
  };
  const response = await proxyConsole(
    new Request('https://site.example/api/console/operations'),
    ['operations'],
    'owner',
    config,
    transport,
  );
  assert.equal(response.status, 200);
  assert.equal(((await response.json()) as { summary: unknown }).summary, null);
});

void test('mutations require same origin and derive actor from authenticated identity', async () => {
  const make = (origin: string) =>
    new Request('https://site.example/api/console/followups', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: origin,
        'X-Arcagent-Actor': 'forged',
      },
      body: JSON.stringify({ call_id: 1 }),
    });
  assert.equal(
    (
      await proxyConsole(
        make('https://attacker.example'),
        ['followups'],
        'owner',
        config,
        never,
      )
    ).status,
    403,
  );
  const response = await proxyConsole(
    make('https://site.example'),
    ['followups'],
    'owner',
    config,
    async (_, init) => {
      assert.equal(init?.method, 'POST');
      assert.equal(new Headers(init?.headers).get('X-Arcagent-Actor'), 'owner');
      assert.equal(init?.body, JSON.stringify({ call_id: 1 }));
      return Response.json({ id: 1, revision: 1 });
    },
  );
  assert.equal(response.status, 200);
});
void test('mutations never reach read-only routes or retry uncertain writes', async () => {
  const req = new Request('https://site.example/api/console/operations', {
    method: 'POST',
    headers: {
      Origin: 'https://site.example',
      'Content-Type': 'application/json',
    },
    body: '{}',
  });
  assert.equal(
    (await proxyConsole(req, ['operations'], 'owner', config, never)).status,
    405,
  );
  let attempts = 0;
  const res = await proxyConsole(
    req,
    ['followups'],
    'owner',
    config,
    async () => {
      attempts++;
      throw Error('network lost');
    },
  );
  assert.equal(attempts, 1);
  assert.equal(res.status, 503);
  assert.match(await res.text(), /may have been saved/);
});

void test('write boundary rejects malformed and oversized bodies and missing origin', async () => {
  for (const [body, origin, status] of [
    ['not-json', 'https://site.example', 400],
    ['x'.repeat(16385), 'https://site.example', 413],
    ['{}', '', 403],
  ] as const) {
    const req = new Request('https://site.example/api/console/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: origin },
      body,
    });
    assert.equal(
      (await proxyConsole(req, ['feedback'], 'owner', config, never)).status,
      status,
    );
  }
});
void test('independent review denial is a definite rejection, not an uncertain save', async () => {
  const req = new Request(
    'https://site.example/api/console/feedback/1/review',
    {
      method: 'POST',
      headers: {
        Origin: 'https://site.example',
        'Content-Type': 'application/json',
      },
      body: '{}',
    },
  );
  const response = await proxyConsole(
    req,
    ['feedback', '1', 'review'],
    'owner',
    config,
    async () =>
      Response.json(
        { detail: 'An independent reviewer must review this candidate' },
        { status: 403 },
      ),
  );
  assert.equal(response.status, 403);
  assert.match(await response.text(), /independent reviewer/);
});
