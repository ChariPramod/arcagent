import { demoCalls } from '@/lib/demo';
import { Console } from '@/components/console';
export const metadata = { title: 'Explore the workspace' };
export default async function Demo({
  searchParams,
}: {
  searchParams: Promise<{ view?: string; call?: string }>;
}) {
  const params = await searchParams;
  return (
    <Console
      demo
      initialView={
        params.view === 'lab'
          ? 'lab'
          : params.view === 'workflows'
            ? 'workflows'
            : params.call || params.view === 'calls'
              ? 'calls'
              : params.view === 'evaluations'
                ? 'evaluations'
                : 'operations'
      }
      initialCall={
        demoCalls.some((call) => call.id === Number(params.call))
          ? Number(params.call)
          : null
      }
    />
  );
}
