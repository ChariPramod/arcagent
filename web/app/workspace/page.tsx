import { authConfig } from '@/lib/native-auth';
import Link from 'next/link';
import { hasTrustedSitesIdentity } from '@/lib/auth-runtime';
import { requireChatGPTUser } from '@/app/chatgpt-auth';
import { Console } from '@/components/console';
export const dynamic = 'force-dynamic';
export const metadata = { title: 'Workspace' };
async function ProtectedWorkspace() {
  if (!hasTrustedSitesIdentity() && !authConfig())
    return (
      <main className="mx-auto max-w-xl p-8 pt-24">
        <p className="eyebrow">Workspace access</p>
        <h1 className="text-3xl mt-4 mb-4">
          Connect a trusted sign-in provider.
        </h1>
        <p className="text-muted-foreground mb-6">
          This Next.js runtime has no configured identity integration. Live
          records stay locked. Explore the fictional workspace while your
          deployment is configured.
        </p>
        <Link className="underline" href="/demo?view=operations">
          Explore operations demo
        </Link>
      </main>
    );
  const user = await requireChatGPTUser('/workspace');
  const allowed = (process.env.ARCAGENT_ALLOWED_USER_IDS ?? '')
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean);
  if (!allowed.includes(user.userId))
    return (
      <main className="mx-auto max-w-xl p-8 pt-24">
        <p className="eyebrow">Access pending</p>
        <h1 className="text-3xl mt-4 mb-4">You are signed in.</h1>
        <p className="text-muted-foreground mb-6">
          Your account needs workspace access before you can view call records.
          Share this account ID with the workspace owner.
        </p>
        <code className="block break-all rounded-xl border p-4 text-sm">
          {user.userId}
        </code>
        {!hasTrustedSitesIdentity() && (
          <form action="/auth/logout" method="post">
            <button className="underline mt-6">Sign out</button>
          </form>
        )}
      </main>
    );
  return <Console demo={false} userName={user.displayName} />;
}
export default function Workspace() {
  return <ProtectedWorkspace />;
}
