import * as oidc from 'openid-client';
import { EncryptJWT, jwtDecrypt, base64url } from 'jose';

export const SESSION_COOKIE = '__Host-arcagent_session';
const TRANSACTION_COOKIE = '__Host-arcagent_transaction';
export type AuthConfig = {
  origin: string;
  issuer: string;
  clientId: string;
  clientSecret: string;
  key: Uint8Array;
};
type Env = Record<string, string | undefined>;
export function authConfig(env: Env = process.env): AuthConfig | null {
  try {
    const origin = new URL(env.ARCAGENT_AUTH_ORIGIN ?? '');
    const issuer = new URL(env.ARCAGENT_OIDC_ISSUER ?? '');
    const secret = env.ARCAGENT_AUTH_SECRET ?? '';
    if (
      origin.protocol !== 'https:' ||
      origin.origin !== env.ARCAGENT_AUTH_ORIGIN ||
      origin.username ||
      origin.password ||
      issuer.protocol !== 'https:' ||
      issuer.username ||
      issuer.password ||
      issuer.search ||
      issuer.hash ||
      !/^[A-Za-z0-9_-]{43}$/.test(secret)
    )
      return null;
    const key = base64url.decode(secret);
    if (
      key.length !== 32 ||
      !env.ARCAGENT_OIDC_CLIENT_ID ||
      !env.ARCAGENT_OIDC_CLIENT_SECRET
    )
      return null;
    return {
      origin: origin.origin,
      issuer: env.ARCAGENT_OIDC_ISSUER!,
      clientId: env.ARCAGENT_OIDC_CLIENT_ID,
      clientSecret: env.ARCAGENT_OIDC_CLIENT_SECRET,
      key,
    };
  } catch {
    return null;
  }
}
export async function seal(
  config: AuthConfig,
  purpose: string,
  payload: Record<string, unknown>,
  seconds: number,
): Promise<string> {
  return new EncryptJWT(payload)
    .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
    .setIssuer(config.origin)
    .setAudience(`arcagent:${purpose}`)
    .setIssuedAt()
    .setExpirationTime(Math.floor(Date.now() / 1000) + seconds)
    .encrypt(config.key);
}
export async function unseal(
  config: AuthConfig,
  purpose: string,
  token: string,
) {
  try {
    const { payload } = await jwtDecrypt(token, config.key, {
      issuer: config.origin,
      audience: `arcagent:${purpose}`,
      keyManagementAlgorithms: ['dir'],
      contentEncryptionAlgorithms: ['A256GCM'],
      requiredClaims: ['iat', 'exp'],
    });
    return payload;
  } catch {
    return null;
  }
}
export function safeReturnPath(path: string | null): string {
  if (!path || /[\\\r\n]/.test(path)) return '/workspace';
  try {
    const url = new URL(path, 'https://app.local');
    if (
      !path.startsWith('/') ||
      url.origin !== 'https://app.local' ||
      url.pathname !== '/workspace'
    )
      return '/workspace';
    return `${url.pathname}${url.search}`;
  } catch {
    return '/workspace';
  }
}
export async function actorId(
  issuer: string,
  subject: string,
): Promise<string> {
  const bytes = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(`${issuer}\0${subject}`),
  );
  return (
    'oidc:' +
    Array.from(new Uint8Array(bytes), (byte) =>
      byte.toString(16).padStart(2, '0'),
    ).join('')
  );
}
function cookie(headers: Headers, name: string): string {
  const values = (headers.get('cookie') ?? '')
    .split(';')
    .map((value) => value.trim())
    .filter((value) => value.startsWith(`${name}=`));
  return values.length === 1 ? values[0].slice(name.length + 1) : '';
}
function setCookie(name: string, value: string, seconds: number): string {
  return `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${seconds}`;
}
export async function sessionUser(config: AuthConfig | null, headers: Headers) {
  if (!config) return null;
  const session = await unseal(
    config,
    'session',
    cookie(headers, SESSION_COOKIE),
  );
  if (
    !session ||
    session.provider !== config.issuer ||
    session.client !== config.clientId ||
    typeof session.sub !== 'string' ||
    !/^oidc:[a-f0-9]{64}$/.test(session.sub)
  )
    return null;
  const name =
    typeof session.name === 'string' ? session.name : 'Workspace member';
  return { userId: session.sub, displayName: name, email: '', fullName: null };
}
function redirect(
  config: AuthConfig,
  path: string,
  cookies: string[] = [],
): Response {
  const headers = new Headers({
    Location: new URL(path, config.origin).href,
    'Cache-Control': 'no-store',
    'Referrer-Policy': 'no-referrer',
  });
  cookies.forEach((value) => headers.append('Set-Cookie', value));
  return new Response(null, { status: 303, headers });
}
function error(config: AuthConfig) {
  return redirect(config, '/auth/error', [
    setCookie(TRANSACTION_COOKIE, '', 0),
  ]);
}
async function provider(config: AuthConfig, transport: typeof fetch) {
  // Fixed server configuration is the only discovery trust root. Never follow redirects.
  const guardedFetch: typeof fetch = (input, init) => {
    const url = new URL(
      input instanceof Request ? input.url : input.toString(),
    );
    if (url.protocol !== 'https:' || url.username || url.password)
      throw new Error('Invalid identity endpoint');
    return transport(input, {
      ...init,
      redirect: 'error',
      signal: AbortSignal.timeout(10_000),
    });
  };
  return oidc.discovery(
    new URL(config.issuer),
    config.clientId,
    config.clientSecret,
    undefined,
    {
      timeout: 10,
      [oidc.customFetch]: guardedFetch as oidc.CustomFetch,
      execute: [oidc.enableNonRepudiationChecks],
    },
  );
}
export async function login(
  request: Request,
  config: AuthConfig,
  transport: typeof fetch = fetch,
): Promise<Response> {
  try {
    const url = new URL(request.url);
    if (url.origin !== config.origin) return error(config);
    const providerConfig = await provider(config, transport);
    const state = oidc.randomState(),
      nonce = oidc.randomNonce(),
      verifier = oidc.randomPKCECodeVerifier();
    const destination = oidc.buildAuthorizationUrl(providerConfig, {
      scope: 'openid profile',
      response_type: 'code',
      redirect_uri: `${config.origin}/auth/callback`,
      state,
      nonce,
      code_challenge: await oidc.calculatePKCECodeChallenge(verifier),
      code_challenge_method: 'S256',
    });
    if (destination.protocol !== 'https:') return error(config);
    const transaction = await seal(
      config,
      'transaction',
      {
        state,
        nonce,
        verifier,
        provider: config.issuer,
        client: config.clientId,
        returnTo: safeReturnPath(url.searchParams.get('return_to')),
      },
      600,
    );
    return redirect(config, destination.href, [
      setCookie(TRANSACTION_COOKIE, transaction, 600),
    ]);
  } catch {
    return error(config);
  }
}
export async function callback(
  request: Request,
  config: AuthConfig,
  transport: typeof fetch = fetch,
): Promise<Response> {
  try {
    const url = new URL(request.url);
    if (url.origin !== config.origin || url.pathname !== '/auth/callback')
      return error(config);
    const tx = await unseal(
      config,
      'transaction',
      cookie(request.headers, TRANSACTION_COOKIE),
    );
    if (
      !tx ||
      tx.provider !== config.issuer ||
      tx.client !== config.clientId ||
      typeof tx.state !== 'string' ||
      typeof tx.nonce !== 'string' ||
      typeof tx.verifier !== 'string'
    )
      return error(config);
    const providerConfig = await provider(config, transport);
    const tokens = await oidc.authorizationCodeGrant(providerConfig, url, {
      expectedState: tx.state,
      expectedNonce: tx.nonce,
      pkceCodeVerifier: tx.verifier,
      idTokenExpected: true,
    });
    const claims = tokens.claims();
    if (!claims || typeof claims.sub !== 'string' || !claims.sub)
      return error(config);
    const session = await seal(
      config,
      'session',
      {
        sub: await actorId(config.issuer, claims.sub),
        provider: config.issuer,
        client: config.clientId,
        name:
          typeof claims.name === 'string'
            ? claims.name.slice(0, 120)
            : 'Workspace member',
      },
      900,
    );
    return redirect(
      config,
      safeReturnPath(typeof tx.returnTo === 'string' ? tx.returnTo : null),
      [
        setCookie(TRANSACTION_COOKIE, '', 0),
        setCookie(SESSION_COOKIE, session, 900),
      ],
    );
  } catch {
    return error(config);
  }
}
export function logout(request: Request, config: AuthConfig): Response {
  if (
    request.method !== 'POST' ||
    request.headers.get('origin') !== config.origin ||
    new URL(request.url).origin !== config.origin
  )
    return new Response('This action must come from your workspace.', {
      status: 403,
      headers: { 'Cache-Control': 'no-store' },
    });
  return redirect(config, '/', [
    setCookie(SESSION_COOKIE, '', 0),
    setCookie(TRANSACTION_COOKIE, '', 0),
  ]);
}
