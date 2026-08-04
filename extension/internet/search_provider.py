"""Provider-neutral protocol for internet asset discovery."""

from typing import Protocol

from .models import AssetDiscoveryResult, AssetSearchRequest


class AssetDiscoveryProvider(Protocol):
    def search(self, request: AssetSearchRequest) -> AssetDiscoveryResult:
        """Return non-mutating asset candidates for a user search request."""
