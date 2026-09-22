import Link from 'next/link';
export const metadata = { title: 'Sign-in needs another try' };
export default function AuthError() {
  return (
    <main className="mx-auto max-w-xl p-8 pt-24">
      <p className="eyebrow">Workspace access</p>
      <h1 className="text-3xl mt-4 mb-4">Sign-in could not be completed.</h1>
      <p className="text-muted-foreground mb-6">
        Your sign-in may have expired or the identity provider may be
        unavailable. Please try again. If this continues, ask the workspace
        owner to check the sign-in configuration.
      </p>
      <Link className="underline mr-6" href="/auth/login" prefetch={false}>
        Try signing in again
      </Link>
      <Link className="underline" href="/demo">
        Explore the demo
      </Link>
    </main>
  );
}
