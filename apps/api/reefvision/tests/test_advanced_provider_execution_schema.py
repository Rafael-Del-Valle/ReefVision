from reefvision.schemas.advanced_provider_execution import AdvancedProviderExecutionRequest
from reefvision.services.advanced_provider_execution import _string_list


def test_advanced_execution_request_keeps_downloads_opt_in() -> None:
    request = AdvancedProviderExecutionRequest(task="caption")
    assert request.allow_model_download is False


def test_open_vocabulary_prompt_parser_accepts_csv_or_list() -> None:
    assert _string_list("coral polyp, branch", name="prompts") == ["coral polyp", "branch"]
    assert _string_list(["polyp", "branch"], name="prompts") == ["polyp", "branch"]
