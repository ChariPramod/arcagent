export async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/console/${path}`, {
    cache: 'no-store',
    signal,
  });
  const body = await response.json();
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
}
