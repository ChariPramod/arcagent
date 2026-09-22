export type ConsoleConfig = {
  apiUrl: string | undefined;
  token: string | undefined;
  allowedUsers: string | undefined;
  allowLocal?: boolean;
};
const json = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });
export async function proxyConsole(
  request: Request,
  path: string[],
  userId: string | null,
  config: ConsoleConfig,
  transport: typeof fetch = fetch,
): Promise<Response> {
  if (!userId) return json({ detail: 'Sign in to open your workspace.' }, 401);
  const allowed = (config.allowedUsers ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  if (!allowed.length)
    return json(
      { detail: 'Workspace access has not been configured yet.' },
      503,
    );
  if (!allowed.includes(userId))
    return json({ detail: 'You do not have access to this workspace.' }, 403);
  if (!config.apiUrl || !config.token)
    return json({ detail: 'Your workspace is not connected yet.' }, 503);
  const route = path.join('/');
  const method = request.method.toUpperCase();
  const readable =
    /^(calls|evals)(\/\d+)?$/.test(route) ||
    /^(followups|feedback)(\/\d+\/(audit|export))?$/.test(route) ||
    /^calls\/\d+\/latency$/.test(route) ||
    ['compare', 'operations', 'lab/scenarios'].includes(route);
  const writable =
    (method === 'POST' &&
      (/^(followups|feedback)$/.test(route) ||
        /^feedback\/\d+\/review$/.test(route) ||
        route === 'lab/replay')) ||
    (method === 'PATCH' && /^followups\/\d+$/.test(route));
  if (!readable && !writable) return json({ detail: 'Not found' }, 404);
  if (method !== 'GET' && !writable)
    return json({ detail: 'Method not allowed' }, 405);
  let payload: string | undefined;
  if (method !== 'GET') {
    if (request.headers.get('origin') !== new URL(request.url).origin)
      return json(
        { detail: 'This action must come from your workspace.' },
        403,
      );
    if (
      request.headers.get('content-type')?.split(';')[0] !== 'application/json'
    )
      return json({ detail: 'JSON required' }, 415);
    // Bound streamed bodies as well as Content-Length; never buffer arbitrary uploads.
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      if (reader)
        while (true) {
          const part = await reader.read();
          if (part.done) break;
          size += part.value.byteLength;
          if (size > 16384) {
            await reader.cancel();
            return json({ detail: 'Request too large' }, 413);
          }
          chunks.push(part.value);
        }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      payload = new TextDecoder().decode(bytes);
      const parsed: unknown = JSON.parse(payload);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
        throw Error();
    } catch {
      return json({ detail: 'Invalid JSON request' }, 400);
    }
  }
  let base: URL;
  try {
    base = new URL(config.apiUrl);
  } catch {
    return json({ detail: 'Workspace connection needs attention.' }, 503);
  }
  if (
    base.username ||
    base.password ||
    (base.protocol !== 'https:' &&
      !(
        config.allowLocal &&
        base.protocol === 'http:' &&
        ['localhost', '127.0.0.1'].includes(base.hostname)
      ))
  )
    return json({ detail: 'Workspace connection needs attention.' }, 503);
  const upstream = new URL(`/api/console/${route}`, base);
  const query = new URL(request.url).searchParams;
  for (const key of ['limit', 'offset', 'before', 'after']) {
    const v = query.get(key);
    if (v !== null) {
      if (!/^\d+$/.test(v)) return json({ detail: 'Invalid request' }, 400);
      upstream.searchParams.set(key, v);
    }
  }
  const status = query.get('status');
  if (status) upstream.searchParams.set('status', status);
  const outcome = query.get('outcome');
  if (outcome) upstream.searchParams.set('outcome', outcome);
  try {
    const response = await transport(upstream, {
      method,
      body: payload,
      headers: {
        ...(method !== 'GET'
          ? { 'Content-Type': 'application/json', 'X-Arcagent-Actor': userId }
          : {}),
        Authorization: `Bearer ${config.token}`,
        Accept: 'application/json',
      },
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(10000),
    });
    if (
      response.status === 403 &&
      method === 'POST' &&
      /^feedback\/\d+\/review$/.test(route)
    )
      return json(
        { detail: 'An independent reviewer must review this candidate.' },
        403,
      );
    if (
      response.status >= 500 ||
      response.status === 401 ||
      response.status === 403
    )
      return json(
        {
          detail:
            method === 'GET'
              ? 'The workspace connection is unavailable. Please try again.'
              : 'The action may have been saved. Refresh the record before trying again.',
        },
        503,
      );
    const body = await response.json();
    return json(body, response.status);
  } catch {
    return json(
      {
        detail:
          method === 'GET'
            ? 'We could not reach your workspace. Please try again.'
            : 'The action may have been saved. Refresh the record before trying again.',
      },
      503,
    );
  }
}
