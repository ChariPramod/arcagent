'use client';
import { useEffect, useRef } from 'react';
import type { CallSummary } from './domain';
type ModelContext = {
  registerTool: (
    tool: {
      name: string;
      title: string;
      description: string;
      inputSchema: object;
      annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
      execute: (input: unknown) => unknown;
    },
    options: { signal: AbortSignal },
  ) => void | Promise<void>;
};
export function useConversationTool(
  calls: CallSummary[],
  demo: boolean,
  visible: boolean,
) {
  const current = useRef({ calls, demo, visible });
  useEffect(() => {
    current.current = { calls, demo, visible };
  }, [calls, demo, visible]);
  useEffect(() => {
    const context = (document as Document & { modelContext?: ModelContext })
      .modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    try {
      void Promise.resolve(
        context.registerTool(
          {
            name: 'read_visible_conversations',
            title: 'Read visible conversations',
            description:
              'Read summaries of the conversations on the current table page, with its search and filters applied. Returns no records when the table is not visible. Does not load additional records or change the view.',
            inputSchema: {
              type: 'object',
              properties: {},
              additionalProperties: false,
            },
            annotations: { readOnlyHint: true, untrustedContentHint: true },
            execute(input: unknown) {
              if (
                !input ||
                typeof input !== 'object' ||
                Array.isArray(input) ||
                Object.keys(input).length
              )
                throw Error('Expected an empty object.');
              const state = current.current;
              return {
                synthetic: state.demo,
                visible: state.visible,
                items: state.visible ? state.calls : [],
              };
            },
          },
          { signal: lifecycle.signal },
        ),
      ).catch(() => {
        lifecycle.abort();
      });
    } catch {
      lifecycle.abort();
    }
    return () => lifecycle.abort();
  }, []);
}
