import { requireChatGPTUser } from '@/app/chatgpt-auth';
import { Console } from '@/components/console';
export const dynamic = 'force-dynamic';
export const metadata = { title: 'Workspace' };
async function ProtectedWorkspace() {
  const user = await requireChatGPTUser('/workspace');
  return <Console demo={false} userName={user.displayName} />;
}
export default function Workspace() {
  return <ProtectedWorkspace />;
}
