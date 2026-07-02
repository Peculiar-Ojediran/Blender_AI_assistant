from dataclasses import dataclass

PROVIDER_OPENAI = "OPENAI"
PROVIDER_NVIDIA = "NVIDIA"


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    identifier: str
    label: str
    description: str
    api_key_name: str


PROVIDER_METADATA = {
    PROVIDER_OPENAI: ProviderMetadata(
        PROVIDER_OPENAI,
        "OpenAI",
        "Use OpenAI Responses API",
        "OPENAI_API_KEY",
    ),
    PROVIDER_NVIDIA: ProviderMetadata(
        PROVIDER_NVIDIA,
        "NVIDIA NIM",
        "Use NVIDIA NIM OpenAI-compatible chat completions",
        "NVIDIA_API_KEY",
    ),
}

PROVIDER_ITEMS = tuple(
    (metadata.identifier, metadata.label, metadata.description)
    for metadata in PROVIDER_METADATA.values()
)


def provider_metadata(provider_choice: str) -> ProviderMetadata:
    return PROVIDER_METADATA.get(provider_choice, PROVIDER_METADATA[PROVIDER_OPENAI])


def provider_label(provider_choice: str) -> str:
    return provider_metadata(provider_choice).label


def provider_api_key_name(provider_choice: str) -> str:
    return provider_metadata(provider_choice).api_key_name
