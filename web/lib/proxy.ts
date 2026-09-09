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
  if (!/^(calls|evals)(\/\d+)?$/.test(route) && route !== 'compare')
    return json({ detail: 'Not found' }, 404);
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
  const outcome = query.get('outcome');
  if (outcome) upstream.searchParams.set('outcome', outcome);
  try {
    const response = await transport(upstream, {
      headers: {
        Authorization: `Bearer ${config.token}`,
        Accept: 'application/json',
      },
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(10000),
    });
    if (
      response.status >= 500 ||
      response.status === 401 ||
      response.status === 403
    )
      return json(
        {
          detail: 'The workspace connection is unavailable. Please try again.',
        },
        503,
      );
    const body = await response.json();
    return json(body, response.status);
  } catch {
    return json(
      { detail: 'We could not reach your workspace. Please try again.' },
      503,
    );
  }
}
