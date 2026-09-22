import test from 'node:test';
import assert from 'node:assert/strict';
import {
  authConfig,
  seal,
  unseal,
  safeReturnPath,
  actorId,
  sessionUser,
  login,
  callback,
  logout,
  SESSION_COOKIE,
} from './native-auth.ts';
const env = {
  ARCAGENT_AUTH_ORIGIN: 'https://app.example',
  ARCAGENT_AUTH_SECRET: 'A'.repeat(43),
  ARCAGENT_OIDC_ISSUER: 'https://issuer.example',
  ARCAGENT_OIDC_CLIENT_ID: 'client',
  ARCAGENT_OIDC_CLIENT_SECRET: 'secret',
};
const config = authConfig(env)!;
test('native auth fails closed on missing or malformed configuration', () => {
  assert.equal(authConfig({}), null);
  for (const patch of [
    { ARCAGENT_AUTH_SECRET: 'short' },
    { ARCAGENT_AUTH_ORIGIN: 'https://app.example/path' },
    { ARCAGENT_OIDC_ISSUER: 'http://issuer.example' },
    { ARCAGENT_AUTH_ORIGIN: 'https://user:pass@app.example' },
  ])
    assert.equal(authConfig({ ...env, ...patch }), null);
});
test('encrypted cookies enforce integrity, purpose and expiry', async () => {
  const token = await seal(config, 'session', { sub: 'actor' }, 60);
  assert.equal((await unseal(config, 'session', token))?.sub, 'actor');
  assert.equal(await unseal(config, 'transaction', token), null);
  assert.equal(
    await unseal(config, 'session', token.slice(0, -8) + 'xxxxxxxx'),
    null,
  );
  assert.equal(
    await unseal(
      config,
      'session',
      await seal(config, 'session', { sub: 'actor' }, -1),
    ),
    null,
  );
});
test('actor identity is issuer-bound and safe for backend audit', async () => {
  const id = await actorId('https://issuer.example', 'subject');
  assert.match(id, /^oidc:[a-f0-9]{64}$/);
  assert.notEqual(id, await actorId('https://other.example', 'subject'));
});
test('return paths cannot redirect outside workspace or into auth loops', () => {
  for (const path of [
    '//evil.test',
    '/\\evil.test',
    'https://evil.test',
    '/auth/login',
    '/auth/callback',
    '/signin-with-chatgpt',
    '/api/console/calls',
  ])
    assert.equal(safeReturnPath(path), '/workspace');
  assert.equal(
    safeReturnPath('/workspace?view=calls'),
    '/workspace?view=calls',
  );
});
test('forged identity headers and wrong-issuer sessions grant no native identity', async () => {
  assert.equal(
    await sessionUser(
      config,
      new Headers({ 'oai-authenticated-user-id': 'owner' }),
    ),
    null,
  );
  const token = await seal(
    config,
    'session',
    { sub: 'oidc:actor', provider: 'https://wrong.example', name: 'Owner' },
    60,
  );
  assert.equal(
    await sessionUser(
      config,
      new Headers({ cookie: `${SESSION_COOKIE}=${token}` }),
    ),
    null,
  );
});
test('missing callback transaction fails safely and clears it', async () => {
  const result = await callback(
    new Request('https://app.example/auth/callback?code=secret'),
    config,
  );
  assert.equal(result.status, 303);
  assert.equal(
    result.headers.get('location'),
    'https://app.example/auth/error',
  );
  assert.match(result.headers.get('set-cookie')!, /Max-Age=0/);
  assert.ok(!result.headers.get('location')!.includes('secret'));
});
test('logout requires matching origin and clears only after validation', () => {
  assert.equal(
    logout(
      new Request('https://app.example/auth/logout', {
        method: 'POST',
        headers: { origin: 'https://evil.test' },
      }),
      config,
    ).status,
    403,
  );
  const result = logout(
    new Request('https://app.example/auth/logout', {
      method: 'POST',
      headers: { origin: config.origin },
    }),
    config,
  );
  assert.equal(result.status, 303);
  assert.match(result.headers.get('set-cookie')!, /Max-Age=0/);
});
test('discovery failure produces recoverable sign-in error without leaking details', async () => {
  const result = await login(
    new Request('https://app.example/auth/login'),
    config,
    async () => {
      throw new Error('private secret');
    },
  );
  assert.equal(
    result.headers.get('location'),
    'https://app.example/auth/error',
  );
  assert.equal(await result.text(), '');
});

import { generateKeyPair, exportJWK, SignJWT } from 'jose';
async function identityFixture(mode = 'valid') {
  const { privateKey, publicKey } = await generateKeyPair('RS256');
  const jwk = {
    ...(await exportJWK(publicKey)),
    kid: 'test-key',
    alg: 'RS256',
    use: 'sig',
  };
  let nonce = '',
    challenge = '',
    redeemed = false;
  let tokenRequests = 0;
  const transport: typeof fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith('/.well-known/openid-configuration'))
      return Response.json({
        issuer: config.issuer,
        authorization_endpoint: config.issuer + '/authorize',
        token_endpoint: config.issuer + '/token',
        jwks_uri: config.issuer + '/jwks',
        response_types_supported: ['code'],
        subject_types_supported: ['public'],
        id_token_signing_alg_values_supported: ['RS256'],
        code_challenge_methods_supported: ['S256'],
      });
    if (url.endsWith('/jwks')) return Response.json({ keys: [jwk] });
    if (url.endsWith('/token')) {
      tokenRequests++;
      const body = new URLSearchParams(String(init?.body));
      const verifier = body.get('code_verifier')!;
      const hash = await crypto.subtle.digest(
        'SHA-256',
        new TextEncoder().encode(verifier),
      );
      assert.equal(Buffer.from(hash).toString('base64url'), challenge);
      assert.equal(body.get('redirect_uri'), config.origin + '/auth/callback');
      if (redeemed)
        return Response.json({ error: 'invalid_grant' }, { status: 400 });
      redeemed = true;
      const signingKey =
        mode === 'signature'
          ? (await generateKeyPair('RS256')).privateKey
          : privateKey;
      const jwt = await new SignJWT({
        nonce: mode === 'nonce' ? 'wrong' : nonce,
        name: 'Test Owner',
      })
        .setProtectedHeader({ alg: 'RS256', kid: 'test-key' })
        .setIssuer(mode === 'issuer' ? 'https://evil.test' : config.issuer)
        .setAudience(mode === 'audience' ? 'other-client' : config.clientId)
        .setSubject('owner-subject')
        .setIssuedAt()
        .setExpirationTime(
          mode === 'expired' ? Math.floor(Date.now() / 1000) - 120 : '5m',
        )
        .sign(signingKey);
      return Response.json({
        access_token: 'never-store-me',
        token_type: 'Bearer',
        id_token: jwt,
      });
    }
    throw new Error('Unexpected identity request');
  };
  const start = await login(
    new Request(
      config.origin +
        '/auth/login?return_to=' +
        encodeURIComponent('/workspace?view=calls'),
    ),
    config,
    transport,
  );
  const authorize = new URL(start.headers.get('location')!);
  assert.equal(authorize.origin, config.issuer);
  nonce = authorize.searchParams.get('nonce')!;
  challenge = authorize.searchParams.get('code_challenge')!;
  const cookie = start.headers.get('set-cookie')!.split(';')[0];
  const state = authorize.searchParams.get('state')!;
  const request = (stateValue = state) =>
    new Request(
      config.origin + '/auth/callback?code=one-use-code&state=' + stateValue,
      { headers: { cookie } },
    );
  return { transport, request, tokenRequests: () => tokenRequests };
}
test('full OIDC login verifies signed ID token, PKCE, session and one-use code', async () => {
  const fixture = await identityFixture();
  const response = await callback(fixture.request(), config, fixture.transport);
  assert.equal(
    response.headers.get('location'),
    config.origin + '/workspace?view=calls',
  );
  const cookies = response.headers.getSetCookie();
  const sessionCookie = cookies.find((value) =>
    value.startsWith(SESSION_COOKIE + '='),
  )!;
  assert.match(sessionCookie, /HttpOnly; Secure; SameSite=Lax/);
  assert.ok(!sessionCookie.includes('never-store-me'));
  const user = await sessionUser(
    config,
    new Headers({ cookie: sessionCookie.split(';')[0] }),
  );
  assert.equal(user?.userId, await actorId(config.issuer, 'owner-subject'));
  assert.equal(user?.displayName, 'Test Owner');
  assert.equal(
    await sessionUser(
      { ...config, clientId: 'another-client' },
      new Headers({ cookie: sessionCookie.split(';')[0] }),
    ),
    null,
  );
  const replay = await callback(fixture.request(), config, fixture.transport);
  assert.equal(replay.headers.get('location'), config.origin + '/auth/error');
});
for (const mode of ['nonce', 'issuer', 'audience', 'signature', 'expired'])
  test(`OIDC rejects invalid ${mode} and never creates session`, async () => {
    const fixture = await identityFixture(mode);
    const response = await callback(
      fixture.request(),
      config,
      fixture.transport,
    );
    assert.equal(
      response.headers.get('location'),
      config.origin + '/auth/error',
    );
    assert.ok(
      !response.headers
        .getSetCookie()
        .some((value) => value.startsWith(SESSION_COOKIE + '=')),
    );
  });
test('state mismatch stops before token exchange', async () => {
  const fixture = await identityFixture();
  const response = await callback(
    fixture.request('wrong'),
    config,
    fixture.transport,
  );
  assert.equal(response.headers.get('location'), config.origin + '/auth/error');
  assert.equal(fixture.tokenRequests(), 0);
});
