export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className="brand" aria-label="ArcAgent home">
      <span className="brand-mark" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      {!compact && (
        <span>
          arcagent<span className="text-primary">.</span>
        </span>
      )}
    </Link>
  );
}
import Link from 'next/link';
