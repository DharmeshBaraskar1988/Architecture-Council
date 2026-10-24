from app.consensus.engine import Evidence, Outcome, decide, stage_agreement
from app.schemas import Stance, Verdict, Vote


def V(agent, stance, conf):
    return Vote(agent=agent, subject="x", stance=Stance(stance), confidence=conf, convinced_by="test")


def test_plan_example_evolutionary_74_selected_with_condition():
    votes = [V("tara", "adopt", 5), V("ada", "adopt", 4), V("kabir", "adopt", 4), V("rex", "reject", 4)]
    ev = [Evidence("for", "prd_fact"), Evidence("for", "case_study"),
          Evidence("against", "case_study", answered=True)]
    d = decide("evolutionary_architecture", votes, ev)
    assert round(d.vote_support) == 76 and round(d.evidence_balance) == 71
    assert round(d.agreement) == 74 and d.outcome == Outcome.selected_with_condition


def test_plan_example_microservices_21_rejected():
    votes = [V("tara", "reject", 5), V("ada", "reject", 4), V("kabir", "reject", 4), V("rex", "adopt", 3)]
    ev = [Evidence("for", "case_study"), Evidence("against", "prd_fact"), Evidence("against", "official_docs")]
    d = decide("microservices_first", votes, ev)
    assert round(d.agreement) == 21 and d.outcome == Outcome.rejected


def test_plan_example_twelve_factor_88_selected():
    votes = [V("tara", "adopt", 4), V("ada", "adopt", 4), V("kabir", "adopt", 4), V("rex", "adopt_with_condition", 3)]
    ev = [Evidence("for", "prd_fact"), Evidence("for", "official_docs"), Evidence("against", "case_study", relevance=0.5, answered=True)]
    d = decide("twelve_factor", votes, ev)
    assert round(d.agreement) == 88 and d.outcome == Outcome.selected


def test_binding_parked_not_applicable():
    assert decide("pci", [], [], binding=True).outcome == Outcome.selected
    assert decide("multi_region", [], [], key_fact_assumed=True).outcome == Outcome.parked
    assert decide("aws_waf", [], [], not_applicable=True).outcome == Outcome.not_applicable


def test_unanswered_strong_objection_caps_outcome():
    votes = [V("a", "adopt", 5), V("b", "adopt", 5), V("c", "adopt", 5), V("d", "reject", 1)]
    ev = [Evidence("for", "prd_fact"), Evidence("for", "official_docs"), Evidence("for", "prd_fact"),
          Evidence("against", "prd_fact", answered=False, label="sale-day peaks")]
    d = decide("x", votes, ev)
    assert d.agreement >= 75 and d.outcome == Outcome.reviewer_decides


def test_unverified_counts_zero_and_contradicted_removed():
    votes = [V("a", "adopt", 3)]
    d = decide("x", votes, [Evidence("for", "prd_fact"), Evidence("against", "official_docs", verdict=Verdict.unverified),
                            Evidence("against", "case_study", verdict=Verdict.contradicted, label="bad source")])
    assert d.evidence_balance == 100.0
    assert any("Removed contradicted" in r for r in d.reasons)


def test_untested_consensus_flag_and_stage_agreement():
    d1 = decide("a", [V("a", "adopt", 4)], [Evidence("for", "prd_fact")], challenged=False)
    assert d1.flags and d1.agreement == 100.0
    d2 = decide("b", [V("a", "reject", 4)], [Evidence("against", "prd_fact")])
    assert stage_agreement([d1, d2], {"a": 3, "b": 1}) == 75.0
