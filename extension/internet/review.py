"""Candidate review helpers for the internet asset discovery UI."""

from dataclasses import dataclass

from .models import AssetCandidate, AssetFormat, LinkInspectionResult


@dataclass(frozen=True, slots=True)
class CandidateReview:
    can_import: bool
    status_label: str
    reasons: tuple[str, ...]


def review_asset_candidate(
    candidate: AssetCandidate,
    inspection: LinkInspectionResult | None = None,
    *,
    license_acknowledged: bool = False,
) -> CandidateReview:
    reasons = list(candidate.warnings)
    if not candidate.direct_url:
        reasons.append("A direct download URL is required before import.")
        return CandidateReview(
            can_import=False,
            status_label="Needs manual download",
            reasons=tuple(dict.fromkeys(reasons)),
        )
    if candidate.asset_format is AssetFormat.UNKNOWN:
        reasons.append("The candidate format is unsupported or unknown.")
        return CandidateReview(
            can_import=False,
            status_label="Wrong format",
            reasons=tuple(dict.fromkeys(reasons)),
        )
    if inspection is not None and not inspection.allowed:
        reasons.extend(inspection.warnings)
        return CandidateReview(
            can_import=False,
            status_label="Blocked by policy",
            reasons=tuple(dict.fromkeys(reasons)),
        )
    if candidate.requires_license_acknowledgement and not license_acknowledged:
        reasons.append("The candidate license is unknown and must be acknowledged.")
        return CandidateReview(
            can_import=False,
            status_label="License unknown",
            reasons=tuple(dict.fromkeys(reasons)),
        )
    if inspection is None:
        reasons.append("Inspect the direct URL before import.")
        return CandidateReview(
            can_import=False,
            status_label="Ready to inspect",
            reasons=tuple(dict.fromkeys(reasons)),
        )
    return CandidateReview(
        can_import=True,
        status_label="Ready to import",
        reasons=tuple(dict.fromkeys(reasons)),
    )
