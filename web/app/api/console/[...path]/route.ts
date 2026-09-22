import { getChatGPTUser } from '@/app/chatgpt-auth';
import { proxyConsole } from '@/lib/proxy';
export const dynamic = 'force-dynamic';
export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const user = await getChatGPTUser();
  return proxyConsole(
    request,
    (await context.params).path,
    user?.userId ?? null,
    {
      apiUrl: process.env.ARCAGENT_API_URL,
      token: process.env.ARCAGENT_API_TOKEN,
      allowedUsers: process.env.ARCAGENT_ALLOWED_USER_IDS,
      allowLocal: process.env.NODE_ENV !== 'production',
    },
  );
}

export const POST = GET;
export const PATCH = GET;
