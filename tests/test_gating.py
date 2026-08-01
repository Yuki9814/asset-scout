from asset_scout.gating import evaluate_candidate
from asset_scout.models import Candidate, GateStatus, MediaType, RightsEvidence, RiskFlags


def candidate(rights: RightsEvidence, **kwargs) -> Candidate:
    return Candidate(candidate_id="fixture:1", provider=rights.provider, remote_id="1", media_type=MediaType.IMAGE,
                     title="fixture", source_url="https://example.com/source", download_url="https://example.com/file.jpg",
                     rights=rights, **kwargs)


def test_cc_by_with_attribution_is_allowed():
    decision = evaluate_candidate(candidate(RightsEvidence(provider="wikimedia", license_id="CC-BY", commercial_use=True,
                                                           derivatives=True, attribution_required=True, attribution_text="Author")))
    assert decision.status == GateStatus.ALLOW


def test_missing_evidence_is_denied():
    decision = evaluate_candidate(candidate(RightsEvidence(provider="unknown")))
    assert decision.status == GateStatus.DENY


def test_provider_terms_and_risk_require_review():
    decision = evaluate_candidate(candidate(RightsEvidence(provider="pexels", license_id="LicenseRef-Pexels",
                                                           commercial_use=True, derivatives=True, source_terms_ack=False),
                                            risk=RiskFlags(identifiable_person=True)))
    assert decision.status == GateStatus.REVIEW
    assert any("terms" in reason for reason in decision.reasons)
    assert any("identifiable_person" in reason for reason in decision.reasons)

