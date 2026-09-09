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
