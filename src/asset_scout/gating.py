from __future__ import annotations

from .models import Candidate, GateDecision, GateStatus, UsageProfile

POLICY_VERSION = "commercial-edited-video.v1"


def evaluate_candidate(candidate: Candidate, profile: UsageProfile = UsageProfile.COMMERCIAL_EDITED_VIDEO) -> GateDecision:
    rights = candidate.rights
    reasons: list[str] = []
    hard_deny = False
    review = False

    if not rights.license_id:
        hard_deny = True
        reasons.append("missing license identifier")
    if rights.commercial_use is False and profile == UsageProfile.COMMERCIAL_EDITED_VIDEO:
        hard_deny = True
        reasons.append("license does not permit commercial use")
    if rights.derivatives is False:
        hard_deny = True
        reasons.append("license does not permit derivatives")
    if rights.commercial_use is None:
        review = True
        reasons.append("commercial-use permission is not machine-verifiable")
    if rights.derivatives is None:
        review = True
        reasons.append("derivative permission is not machine-verifiable")
    if rights.attribution_required and not rights.attribution_text:
        review = True
        reasons.append("attribution is required but no attribution text was captured")
    if rights.share_alike:
        review = True
        reasons.append("share-alike obligation requires project-level review")
    if not rights.verified_source:
        review = True
        reasons.append("aggregator result requires verification against the original source")
    if rights.provider in {"pexels", "pixabay"} and not rights.source_terms_ack:
        review = True
        reasons.append(f"{rights.provider} terms have not been explicitly acknowledged")

    risk_fields = {
        "identifiable_person": candidate.risk.identifiable_person,
        "minor": candidate.risk.minor,
        "logo_or_trademark": candidate.risk.logo_or_trademark,
        "watermark": candidate.risk.watermark,
        "sensitive_context": candidate.risk.sensitive_context,
        "editorial_only": candidate.risk.editorial_only,
    }
    for label, present in risk_fields.items():
        if present:
            review = True
            reasons.append(f"risk flag requires human review: {label}")
    if candidate.risk.model_release is False or candidate.risk.property_release is False:
        review = True
        reasons.append("release status is incompatible or unknown for the intended edit")

    if hard_deny:
        status = GateStatus.DENY
    elif review:
        status = GateStatus.REVIEW
    else:
        status = GateStatus.ALLOW
    return GateDecision(status=status, reasons=reasons, policy_version=POLICY_VERSION)


def approved_for_download(candidate: Candidate) -> bool:
    return candidate.gate is not None and candidate.gate.status == GateStatus.ALLOW

