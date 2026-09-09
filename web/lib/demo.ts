import type { CallDetail, EvalDetail, Comparison, Turn } from './domain';
// Fictional examples for product exploration. Never mixed with the database or reported as measured results.
const turn = (
  id: number,
  speaker: string,
  text: string,
  node: string,
): Turn => ({
  id,
  speaker,
  text,
  node,
  started_at: null,
  interrupted: false,
  latency: {
    stt_final_ms: null,
    llm_ttft_ms: null,
    tts_first_byte_ms: null,
    playback_start_ms: null,
  },
});
export const demoCalls: CallDetail[] = [
  {
    id: 1042,
    name: 'Nora Ellis',
    started_at: '2026-09-08T10:42:00Z',
    duration_s: 184,
    outcome: 'handoff',
    language: 'en',
    treatment_interest: 'full_arch',
    score: 65,
    threshold: 60,
    decision: 'handoff',
    fields: {
      treatment_interest: 'full_arch',
      pain_level: 8,
      has_insurance: true,
      considering_duration: 'one_to_6_months',
      preferred_time: 'Afternoons',
      callback_number: '2025550123',
      employer_name: null,
      objections: [],
    },
    score_breakdown: {
      full_arch_or_multiple: 30,
      pain_6_or_higher: 20,
      has_insurance: 15,
    },
    turns: [
      turn(
        1,
        'agent',
        'Thanks for calling. This call may be recorded, and you are speaking with an automated assistant. How can I help you today?',
        'greet_and_disclose',
      ),
      turn(
        2,
        'caller',
        'I’ve been thinking about implants. I’m missing most of my upper teeth.',
        'confirm_treatment_interest',
      ),
      turn(
        3,
        'agent',
        'I can help you take the next step with a full arch consultation. Are you experiencing any pain at the moment?',
        'assess_situation',
      ),
      turn(
        4,
        'caller',
        'Quite a bit. About eight out of ten. I’ve been considering this for a couple of months.',
        'assess_situation',
      ),
      turn(
        5,
        'agent',
        'Thank you for sharing that. Do you currently have dental insurance?',
        'extract_insurance_signal',
      ),
      turn(
        6,
        'caller',
        'Yes, I have dental insurance. I don’t know the plan details.',
        'extract_insurance_signal',
      ),
      turn(
        7,
        'agent',
        'A coordinator can talk through that with you. What’s your name and the best number to reach you?',
        'capture_contact',
      ),
      turn(
        8,
        'caller',
        'Nora Ellis. My number is 2025550123. Afternoons work best for me.',
        'capture_contact',
      ),
      turn(
        9,
        'agent',
        'Thank you, Nora. I’m connecting you with a treatment coordinator now.',
        'warm_transfer',
      ),
    ],
  },
  {
    id: 1041,
    name: 'Ava Morgan',
    started_at: '2026-09-08T10:26:00Z',
    duration_s: 142,
    outcome: 'callback_booked',
    language: 'en',
    treatment_interest: 'single_implant',
    score: 30,
    threshold: 60,
    decision: 'callback',
    fields: {
      treatment_interest: 'single_implant',
      pain_level: 2,
      has_insurance: true,
      preferred_time: 'Tomorrow morning',
      callback_number: '2025550146',
      objections: [],
    },
    score_breakdown: { single_implant: 15, has_insurance: 15 },
    turns: [
      turn(
        1,
        'agent',
        'You are speaking with an automated assistant. How can I help?',
        'greet_and_disclose',
      ),
      turn(
        2,
        'caller',
        'I’m looking into replacing one tooth. There’s a little pain, maybe a two.',
        'assess_situation',
      ),
      turn(
        3,
        'agent',
        'Do you have dental insurance?',
        'extract_insurance_signal',
      ),
      turn(
        4,
        'caller',
        'Yes. I’d like to talk with someone tomorrow morning. I’m Ava Morgan, 2025550146.',
        'capture_contact',
      ),
      turn(
        5,
        'agent',
        'A coordinator will call you back. You’ll receive a text with the time.',
        'book_callback_and_sms',
      ),
    ],
  },
  {
    id: 1040,
    name: 'Theo Bennett',
    started_at: '2026-09-08T09:58:00Z',
    duration_s: 213,
    outcome: 'callback_booked',
    language: 'en',
    treatment_interest: 'single_implant',
    score: 0,
    threshold: 60,
    decision: 'callback',
    fields: {
      treatment_interest: 'single_implant',
      pain_level: 0,
      has_insurance: false,
      preferred_time: 'Friday afternoon',
      callback_number: '2025550178',
      objections: [{ kind: 'price', recovered: false }],
    },
    score_breakdown: { single_implant: 15, unrecovered_price_objection: -15 },
    turns: [
      turn(
        1,
        'agent',
        'You are speaking with an automated assistant. How can I help?',
        'greet_and_disclose',
      ),
      turn(
        2,
        'caller',
        'I’m interested in one implant, but I’m worried about the cost.',
        'confirm_treatment_interest',
      ),
      turn(
        3,
        'agent',
        'I understand. A coordinator can discuss the options at a consultation.',
        'handle_objection',
      ),
      turn(
        4,
        'caller',
        'I’m still concerned. I’m not in pain, and I don’t have insurance. Could someone call Friday? Theo Bennett, 2025550178.',
        'capture_contact',
      ),
      turn(
        5,
        'agent',
        'Thank you, Theo. A coordinator will call you back.',
        'book_callback_and_sms',
      ),
    ],
  },
  {
    id: 1039,
    name: null,
    started_at: '2026-09-08T09:31:00Z',
    duration_s: 19,
    outcome: 'wrong_number',
    language: 'en',
    treatment_interest: null,
    score: null,
    threshold: null,
    decision: null,
    fields: {},
    score_breakdown: {},
    turns: [
      turn(
        1,
        'agent',
        'Thanks for calling. You are speaking with an automated assistant. How can I help?',
        'greet_and_disclose',
      ),
      turn(2, 'caller', 'Sorry, I have the wrong number.', 'end_call'),
      turn(3, 'agent', 'No problem. Have a good day.', 'end_call'),
    ],
  },
];
const scenarios = [
  'full_arch_insured',
  'multiple_implants_pain',
  'price_first',
  'price_then_callback',
];
export const demoEvals: EvalDetail[] = [1, 2].map((id) => ({
  id,
  name: id === 1 ? 'Conversation baseline' : 'Insurance prompt iteration',
  created_at: `2026-09-08T${id === 1 ? '09' : '11'}:00:00Z`,
  prompt_version: id === 1 ? 'demo-v1' : 'demo-v2',
  threshold: 60,
  tier: 'text',
  git_sha: 'illustrative',
  suite: 'synthetic_demo',
  results: 4,
  scenarios: 4,
  pass_rate: id === 1 ? 0.5 : 0.75,
  field_accuracy: id === 1 ? 0.75 : 0.875,
  handoff_recall: id === 1 ? 1 : 0.5,
  flaky: [],
  items: scenarios.map((scenario, i) => ({
    id: id * 10 + i,
    scenario_id: scenario,
    group: i < 2 ? 'hot_buyers' : 'price_objectors',
    repeat: 0,
    passed: id === 1 ? i < 2 : i !== 1,
    field_accuracy: (id === 1 ? i < 2 : i !== 1) ? 1 : 0.5,
    expected: {
      treatment_interest: i < 2 ? 'full_arch' : 'single_implant',
      has_insurance: i < 2,
    },
    actual: {
      treatment_interest: i < 2 ? 'full_arch' : 'single_implant',
      has_insurance: (id === 1 ? i < 2 : i !== 1) ? i < 2 : null,
    },
    transcript: [
      {
        speaker: 'caller',
        text:
          i < 2
            ? 'I’m interested in a full arch. I have insurance.'
            : 'I’m interested in one implant, but I’m worried about the cost.',
      },
      {
        speaker: 'agent',
        text: 'A coordinator can help you explore the next step.',
      },
    ],
    notes: null,
  })),
}));
export function demoComparison(before: number, after: number): Comparison {
  const a = demoEvals.find((r) => r.id === before)!;
  const b = demoEvals.find((r) => r.id === after)!;
  const delta = (b.handoff_recall ?? 0) - (a.handoff_recall ?? 0);
  return {
    status: delta < 0 ? 'regression' : 'clear',
    reason: null,
    metrics: [
      {
        group: 'overall',
        name: 'pass_rate',
        before: a.pass_rate!,
        after: b.pass_rate!,
        delta: b.pass_rate! - a.pass_rate!,
        guarded: false,
      },
      {
        group: 'hot_buyers',
        name: 'handoff_recall',
        before: a.handoff_recall!,
        after: b.handoff_recall!,
        delta,
        guarded: true,
      },
    ],
    regressions:
      delta < 0 ? [{ group: 'hot_buyers', name: 'handoff_recall', delta }] : [],
  };
}
