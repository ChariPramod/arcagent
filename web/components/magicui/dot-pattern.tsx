'use client';
// Adapted from Magic UI DotPattern (MIT); see THIRD_PARTY_NOTICES.md.
// Native SVG repetition keeps the decoration static and independent of layout measurement.
import { useId } from 'react';
import { cn } from '@/lib/utils';
export function DotPattern({ className }: { className?: string }) {
  const id = useId();
  return (
    <svg
      aria-hidden="true"
      className={cn(
        'pointer-events-none absolute inset-0 h-full w-full',
        className,
      )}
    >
      <defs>
        <pattern id={id} width="20" height="20" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="1" fill="currentColor" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}
