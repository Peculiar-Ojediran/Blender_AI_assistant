PROVIDER_OPENAI = "OPENAI"
PROVIDER_NVIDIA = "NVIDIA"

PROVIDER_ITEMS = (
    (PROVIDER_OPENAI, "OpenAI", "Use OpenAI Responses API"),
    (PROVIDER_NVIDIA, "NVIDIA NIM", "Use NVIDIA NIM OpenAI-compatible chat completions"),
)


def provider_label(provider_choice: str) -> str:
    if provider_choice == PROVIDER_NVIDIA:
        return "NVIDIA NIM"
    return "OpenAI"


def provider_api_key_name(provider_choice: str) -> str:
    if provider_choice == PROVIDER_NVIDIA:
        return "NVIDIA_API_KEY"
    return "OPENAI_API_KEY"
