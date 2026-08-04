"""Local policy for internet asset discovery and download inspection."""

import ipaddress
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from .models import AssetFormat

DEFAULT_ALLOWED_ASSET_EXTENSIONS = (".obj", ".fbx", ".gltf", ".glb")
PRIVATE_HOST_NAMES = frozenset({"localhost", "localhost.localdomain"})


class InternetPolicyError(RuntimeError):
    """Raised when an internet asset violates local policy."""


@dataclass(frozen=True, slots=True)
class InternetDownloadPolicy:
    max_asset_size_mb: int = 50
    allowed_extensions: tuple[str, ...] = DEFAULT_ALLOWED_ASSET_EXTENSIONS
    timeout_seconds: float = 30.0
    max_redirects: int = 3
    reject_private_hosts: bool = True

    def __post_init__(self) -> None:
        if self.max_asset_size_mb < 1:
            raise ValueError("max_asset_size_mb must be positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative.")
        normalized = tuple(
            dict.fromkeys(_normalize_extension(extension) for extension in self.allowed_extensions)
        )
        if not normalized:
            raise ValueError("At least one allowed extension is required.")
        object.__setattr__(self, "allowed_extensions", normalized)

    @property
    def max_asset_size_bytes(self) -> int:
        return self.max_asset_size_mb * 1024 * 1024


def validate_asset_url(url: str, *, policy: InternetDownloadPolicy) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        raise InternetPolicyError("Asset URLs must use HTTPS.")
    if not parsed.hostname:
        raise InternetPolicyError("Asset URLs require a host name.")
    if parsed.username or parsed.password:
        raise InternetPolicyError("Asset URLs cannot contain credentials.")
    if policy.reject_private_hosts and _private_or_local_host(parsed.hostname):
        raise InternetPolicyError("Asset URLs cannot target local or private network hosts.")

    extension = PurePosixPath(unquote(parsed.path)).suffix.lower()
    if extension not in policy.allowed_extensions:
        allowed = ", ".join(policy.allowed_extensions)
        raise InternetPolicyError(f"Asset URL must end with one of: {allowed}.")
    return extension


def asset_format_from_extension(extension: str) -> AssetFormat:
    normalized = _normalize_extension(extension).lstrip(".")
    try:
        return AssetFormat(normalized)
    except ValueError:
        return AssetFormat.UNKNOWN


def _normalize_extension(extension: str) -> str:
    normalized = extension.strip().lower()
    if not normalized:
        raise ValueError("Allowed extensions cannot be empty.")
    return normalized if normalized.startswith(".") else f".{normalized}"


def _private_or_local_host(host: str) -> bool:
    normalized = host.strip("[]").rstrip(".").lower()
    if normalized in PRIVATE_HOST_NAMES or normalized.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
