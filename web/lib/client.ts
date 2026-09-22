export async function read<T>(
  path: string,
  signal?: AbortSignal,
  timeoutMs = 10000,
): Promise<T> {
  signal?.throwIfAborted();
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener('abort', cancel, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetch(`/api/console/${path}`, {
      cache: 'no-store',
      signal: controller.signal,
    });
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new Error('We could not load your workspace. Please try again.');
    }
    if (!response.ok)
      throw new Error(
        body !== null &&
          typeof body === 'object' &&
          'detail' in body &&
          typeof body.detail === 'string'
          ? body.detail
          : 'We could not load your workspace. Please try again.',
      );
    return body as T;
  } catch (error) {
    if (timedOut)
      throw new Error('The workspace request timed out. Please try again.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
  }
}

/** Writes are never retried automatically: a lost response can follow a commit. */
export async function write<T>(
  path: string,
  body: unknown,
  method: 'POST' | 'PATCH' = 'POST',
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/console/${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    throw new Error(
      'The action may have been saved. Refresh before trying again.',
    );
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      'The action may have been saved. Refresh before trying again.',
    );
  }
  if (!response.ok) {
    if (response.status === 409)
      throw new Error('This record changed. Refresh it before trying again.');
    if (response.status === 422)
      throw new Error(
        'Check the required fields and text limits. Your changes were not accepted.',
      );
    throw new Error(
      data &&
        typeof data === 'object' &&
        'detail' in data &&
        typeof data.detail === 'string'
        ? data.detail
        : 'The action could not be confirmed. Refresh before trying again.',
    );
  }
  return data as T;
}
