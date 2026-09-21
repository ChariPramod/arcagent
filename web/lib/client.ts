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
