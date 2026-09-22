'use client';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
export default function WorkspaceError({ reset }: { reset: () => void }) {
  return (
    <main className="mx-auto max-w-xl px-6 py-24">
      <p className="eyebrow text-primary">Workspace interrupted</p>
      <h1 className="text-3xl mt-4 mb-4">This view could not be displayed.</h1>
      <p className="text-muted-foreground mb-6">
        Reload the view to reconnect. If you were saving a change, check the
        saved record before submitting again.
      </p>
      <div className="flex gap-4 items-center">
        <Button onClick={reset}>Reload view</Button>
        <Link className="underline text-sm" href="/demo">
          Open fictional demo
        </Link>
      </div>
    </main>
  );
}
