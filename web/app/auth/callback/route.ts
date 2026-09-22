import { authConfig, callback } from '@/lib/native-auth';
import { hasTrustedSitesIdentity } from '@/lib/auth-runtime';
export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  if (hasTrustedSitesIdentity()) return new Response(null, { status: 404 });
  const config = authConfig();
  if (!config)
    return Response.json(
      { detail: 'Sign-in has not been configured.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  return callback(request, config);
}
