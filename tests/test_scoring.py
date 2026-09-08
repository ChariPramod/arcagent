"""Scoring, held to the rule table in docs/scoring.md.

Every rule has a test that fires it alone, so a wrong weight names itself. The worked
examples from the document are tested verbatim.
"""

from __future__ import annotations

import pytest

from arcagent.agent.scoring import DEFAULT_THRESHOLD, RULES, Decision, score
from arcagent.agent.state import (
    ConsideringDuration,
    CoverageAwareness,
    LeadFields,
    Objection,
    ObjectionKind,
    TreatmentInterest,
)


class TestEachRuleInIsolation:
    def test_no_signals_scores_zero(self) -> None:
        result = score(LeadFields())
        assert result.score == 0
        assert result.breakdown == {}

    @pytest.mark.parametrize(
        "interest",
        [TreatmentInterest.FULL_ARCH, TreatmentInterest.MULTIPLE_IMPLANTS],
    )
    def test_rule_1_high_value_treatment_is_thirty(self, interest: TreatmentInterest) -> None:
        result = score(LeadFields(treatment_interest=interest))
        assert result.score == 30
        assert result.breakdown == {"full_arch_or_multiple": 30}

    def test_rule_2_single_implant_is_fifteen(self) -> None:
        result = score(LeadFields(treatment_interest=TreatmentInterest.SINGLE_IMPLANT))
        assert result.score == 15
        assert result.breakdown == {"single_implant": 15}

    def test_rules_1_and_2_are_mutually_exclusive(self) -> None:
        for interest in TreatmentInterest:
            breakdown = score(LeadFields(treatment_interest=interest)).breakdown
            fired = {"full_arch_or_multiple", "single_implant"} & set(breakdown)
            assert len(fired) <= 1

    @pytest.mark.parametrize("pain", [6, 7, 10])
    def test_rule_3_pain_at_or_above_six_is_twenty(self, pain: int) -> None:
        assert score(LeadFields(pain_level=pain)).score == 20

    @pytest.mark.parametrize("pain", [0, 5])
    def test_rule_3_does_not_fire_below_six(self, pain: int) -> None:
        assert score(LeadFields(pain_level=pain)).score == 0

    def test_rule_3_ignores_an_unstated_pain_level(self) -> None:
        assert score(LeadFields(pain_level=None)).breakdown == {}

    def test_rule_4_considering_over_six_months_is_ten(self) -> None:
        fields = LeadFields(considering_duration=ConsideringDuration.OVER_6_MONTHS)
        assert score(fields).score == 10

    @pytest.mark.parametrize(
        "duration",
        [
            ConsideringDuration.UNDER_1_MONTH,
            ConsideringDuration.ONE_TO_6_MONTHS,
            ConsideringDuration.UNKNOWN,
        ],
    )
    def test_rule_4_does_not_fire_for_shorter_or_unknown(
        self, duration: ConsideringDuration
    ) -> None:
        assert score(LeadFields(considering_duration=duration)).score == 0

    def test_rule_5_insurance_is_fifteen(self) -> None:
        assert score(LeadFields(has_insurance=True)).score == 15

    def test_rule_5_does_not_fire_when_uninsured_or_unknown(self) -> None:
        assert score(LeadFields(has_insurance=False)).score == 0
        assert score(LeadFields(has_insurance=None)).score == 0

    def test_rule_6_fires_for_an_employer(self) -> None:
        assert score(LeadFields(employer_name="Acme Logistics")).score == 10

    def test_rule_6_fires_for_a_plan_alone(self) -> None:
        assert score(LeadFields(plan_type="Delta Dental PPO")).score == 10

    def test_rule_6_fires_once_even_with_both(self) -> None:
        result = score(LeadFields(employer_name="Acme", plan_type="PPO"))
        assert result.score == 10
        assert result.breakdown == {"named_employer_or_plan": 10}

    def test_rule_6_treats_whitespace_as_not_named(self) -> None:
        """The LLM returns "   " more often than it returns null."""
        assert score(LeadFields(employer_name="   ", plan_type="")).score == 0

    def test_rule_7_financing_question_is_ten(self) -> None:
        assert score(LeadFields(financing_asked=True)).score == 10

    def test_rule_8_unrecovered_price_objection_is_minus_fifteen(self) -> None:
        fields = LeadFields(objections=[Objection(ObjectionKind.PRICE)])
        assert score(fields).score == -15

    def test_rule_8_does_not_fire_once_the_objection_is_recovered(self) -> None:
        fields = LeadFields(objections=[Objection(ObjectionKind.PRICE, recovered=True)])
        assert score(fields).score == 0

    def test_rule_8_uses_the_latest_state_of_the_price_objection(self) -> None:
        """Raised, handled, raised again and left unhandled is still a penalty."""
        fields = LeadFields(
            objections=[
                Objection(ObjectionKind.PRICE, recovered=True, turn_index=2),
                Objection(ObjectionKind.PRICE, recovered=False, turn_index=8),
            ]
        )
        assert score(fields).score == -15

    def test_rule_8_ignores_other_objection_kinds(self) -> None:
        fields = LeadFields(objections=[Objection(ObjectionKind.FEAR)])
        assert score(fields).score == 0

    def test_rule_9_just_looking_and_declined_callback_is_minus_thirty(self) -> None:
        fields = LeadFields(
            objections=[Objection(ObjectionKind.JUST_LOOKING)], callback_declined=True
        )
        assert score(fields).score == -30

    def test_rule_9_needs_both_halves(self) -> None:
        browsing = LeadFields(objections=[Objection(ObjectionKind.JUST_LOOKING)])
        declined = LeadFields(callback_declined=True)
        assert score(browsing).score == 0
        assert score(declined).score == 0

    def test_every_rule_in_the_table_has_a_test_that_fires_it_alone(self) -> None:
        """Guards against a rule being added to the table with no test of its own."""
        assert {rule.name for rule in RULES} == {
            "full_arch_or_multiple",
            "single_implant",
            "pain_6_or_higher",
            "considering_over_6_months",
            "has_insurance",
            "named_employer_or_plan",
            "asked_about_financing",
            "unrecovered_price_objection",
            "just_looking_declined_callback",
        }


class TestThreshold:
    def _fields_scoring(self, total: int) -> LeadFields:
        """Full arch (30) plus pain (20) plus insurance (15) is 65. Trim to order."""
        if total == 65:
            return LeadFields(
                treatment_interest=TreatmentInterest.FULL_ARCH, pain_level=8, has_insurance=True
            )
        raise AssertionError("unsupported")

    def test_exactly_at_the_threshold_is_a_handoff(self) -> None:
        fields = LeadFields(treatment_interest=TreatmentInterest.FULL_ARCH, pain_level=7)
        result = score(fields, threshold=50)
        assert result.score == 50
        assert result.decision is Decision.HANDOFF

    def test_one_below_the_threshold_is_a_callback(self) -> None:
        fields = LeadFields(treatment_interest=TreatmentInterest.FULL_ARCH, pain_level=7)
        assert score(fields, threshold=51).decision is Decision.CALLBACK

    def test_the_threshold_is_recorded_on_the_result(self) -> None:
        assert score(LeadFields(), threshold=42).threshold_used == 42

    def test_the_default_threshold_is_sixty(self) -> None:
        assert DEFAULT_THRESHOLD == 60

    def test_a_sweep_moves_the_boundary_and_nothing_else(self) -> None:
        fields = self._fields_scoring(65)
        decisions = {t: score(fields, threshold=t).decision for t in (50, 60, 65, 66, 80)}
        assert decisions[50] is Decision.HANDOFF
        assert decisions[60] is Decision.HANDOFF
        assert decisions[65] is Decision.HANDOFF
        assert decisions[66] is Decision.CALLBACK
        assert decisions[80] is Decision.CALLBACK
        assert all(score(fields, threshold=t).score == 65 for t in (50, 60, 65, 66, 80))


class TestCoordinatorAvailability:
    def test_no_coordinator_never_hands_off_however_hot(self) -> None:
        fields = LeadFields(
            treatment_interest=TreatmentInterest.FULL_ARCH,
            pain_level=10,
            has_insurance=True,
            employer_name="Acme",
            financing_asked=True,
        )
        result = score(fields, coordinator_available=False)
        assert result.score == 85
        assert result.decision is Decision.CALLBACK
        assert not result.is_handoff

    def test_availability_is_recorded_on_the_result(self) -> None:
        assert score(LeadFields(), coordinator_available=False).coordinator_available is False


class TestWorkedExamplesFromTheDocument:
    def test_full_arch_in_pain_insured_and_named_employer_is_seventy_five(self) -> None:
        fields = LeadFields(
            treatment_interest=TreatmentInterest.FULL_ARCH,
            pain_level=8,
            has_insurance=True,
            employer_name="Acme Logistics",
        )
        result = score(fields)
        assert result.score == 75
        assert result.decision is Decision.HANDOFF
        assert result.breakdown == {
            "full_arch_or_multiple": 30,
            "pain_6_or_higher": 20,
            "has_insurance": 15,
            "named_employer_or_plan": 10,
        }

    def test_single_implant_insured_asking_about_financing_is_forty(self) -> None:
        fields = LeadFields(
            treatment_interest=TreatmentInterest.SINGLE_IMPLANT,
            has_insurance=True,
            financing_asked=True,
        )
        result = score(fields)
        assert result.score == 40
        assert result.decision is Decision.CALLBACK

    def test_a_stuck_price_objection_pulls_a_strong_lead_under(self) -> None:
        fields = LeadFields(
            treatment_interest=TreatmentInterest.FULL_ARCH,
            has_insurance=True,
            employer_name="Acme",
            objections=[Objection(ObjectionKind.PRICE)],
        )
        result = score(fields)
        assert result.score == 40
        assert result.decision is Decision.CALLBACK

    def test_a_browser_stays_cold_even_wanting_a_full_arch(self) -> None:
        fields = LeadFields(
            treatment_interest=TreatmentInterest.FULL_ARCH,
            pain_level=7,
            has_insurance=True,
            objections=[Objection(ObjectionKind.JUST_LOOKING)],
            callback_declined=True,
        )
        result = score(fields)
        assert result.score == 35
        assert result.decision is Decision.CALLBACK

    def test_sixty_five_hands_off_with_a_coordinator_and_not_without(self) -> None:
        fields = LeadFields(
            treatment_interest=TreatmentInterest.FULL_ARCH, pain_level=6, has_insurance=True
        )
        assert score(fields).score == 65
        assert score(fields).decision is Decision.HANDOFF
        assert score(fields, coordinator_available=False).decision is Decision.CALLBACK


class TestPurity:
    def test_scoring_does_not_mutate_the_fields_it_is_given(self) -> None:
        fields = LeadFields(
            treatment_interest=TreatmentInterest.FULL_ARCH,
            objections=[Objection(ObjectionKind.PRICE)],
        )
        before = fields.as_lead_row()
        score(fields)
        assert fields.as_lead_row() == before

    def test_the_same_fields_always_score_the_same(self) -> None:
        fields = LeadFields(treatment_interest=TreatmentInterest.FULL_ARCH, pain_level=9)
        assert len({score(fields).score for _ in range(50)}) == 1

    def test_the_breakdown_lists_only_rules_that_fired(self) -> None:
        result = score(LeadFields(treatment_interest=TreatmentInterest.FULL_ARCH))
        assert result.breakdown == {"full_arch_or_multiple": 30}
        assert sum(result.breakdown.values()) == result.score


class TestLeadRow:
    def test_enums_become_strings_for_the_database(self) -> None:
        row = LeadFields(
            treatment_interest=TreatmentInterest.FULL_ARCH,
            considering_duration=ConsideringDuration.OVER_6_MONTHS,
            coverage_awareness=CoverageAwareness.KNOWS_NOT_COVERED,
        ).as_lead_row()
        assert row["treatment_interest"] == "full_arch"
        assert row["considering_duration"] == "over_6_months"
        assert row["coverage_awareness"] == "knows_not_covered"

    def test_objections_serialise_as_json_ready_dicts(self) -> None:
        row = LeadFields(
            objections=[Objection(ObjectionKind.PRICE, recovered=True, turn_index=4)]
        ).as_lead_row()
        assert row["objections"] == [{"kind": "price", "recovered": True, "turn_index": 4}]

    def test_the_row_carries_no_field_the_leads_table_lacks(self) -> None:
        from arcagent.persistence.models import Lead

        columns = {c.name for c in Lead.__table__.columns}
        assert set(LeadFields().as_lead_row()) <= columns
