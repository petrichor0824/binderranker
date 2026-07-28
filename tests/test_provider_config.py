import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from protein_design_agent.agent.provider_factory import (
    build_request_parser_provider,
    resolve_provider_profile,
)
from protein_design_agent.agent.providers.openai_compatible import (
    OpenAICompatibleProvider,
)
from protein_design_agent.schemas.provider_config import (
    load_model_provider_config,
)


def write_config(
    tmp_path: Path,
    content: str,
) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(
        content,
        encoding="utf-8",
    )
    return path


def valid_config_text() -> str:
    return """
schema_version: "0.1"
active_profile: test_cloud

profiles:
  test_cloud:
    kind: openai_compatible
    base_url: https://api.example.com/v1
    model: test-model
    api_key_env: TEST_MODEL_API_KEY
    require_api_key: true
    timeout_seconds: 60
    max_output_tokens: 4096
    max_tokens_field: "max_tokens"
    temperature: 0.0

  test_local:
    kind: openai_compatible
    base_url: http://127.0.0.1:8000/v1
    model: local-model
    api_key_env: null
    require_api_key: false
"""


def test_valid_model_config_loads(
    tmp_path: Path,
) -> None:
    path = write_config(
        tmp_path,
        valid_config_text(),
    )

    config = load_model_provider_config(path)

    assert config.active_profile == "test_cloud"
    assert set(config.profiles) == {
        "test_cloud",
        "test_local",
    }

    assert config.profiles[
        "test_cloud"
    ].api_key_env == "TEST_MODEL_API_KEY"


def test_active_profile_must_exist(
    tmp_path: Path,
) -> None:
    text = valid_config_text().replace(
        "active_profile: test_cloud",
        "active_profile: missing_profile",
    )

    path = write_config(tmp_path, text)

    with pytest.raises(
        ValidationError,
        match="active_profile 不存在",
    ):
        load_model_provider_config(path)


def test_unknown_configuration_field_is_rejected(
    tmp_path: Path,
) -> None:
    text = valid_config_text().replace(
        "model: test-model",
        (
            "model: test-model\n"
            "    invented_option: true"
        ),
        1,
    )

    path = write_config(tmp_path, text)

    with pytest.raises(
        ValidationError,
        match="invented_option",
    ):
        load_model_provider_config(path)


def test_invalid_api_key_environment_name_is_rejected(
    tmp_path: Path,
) -> None:
    text = valid_config_text().replace(
        "api_key_env: TEST_MODEL_API_KEY",
        "api_key_env: invalid-key-name",
    )

    path = write_config(tmp_path, text)

    with pytest.raises(
        ValidationError,
        match="合法的环境变量名称",
    ):
        load_model_provider_config(path)


def test_factory_builds_selected_provider(
    tmp_path: Path,
) -> None:
    path = write_config(
        tmp_path,
        valid_config_text(),
    )
    config = load_model_provider_config(path)

    provider = build_request_parser_provider(
        config,
        profile_name="test_local",
        environ={},
    )

    assert isinstance(
        provider,
        OpenAICompatibleProvider,
    )
    assert provider.name == "test_local"

    name, profile = resolve_provider_profile(
        config,
        profile_name="test_local",
    )

    assert name == "test_local"
    assert profile.require_api_key is False


def test_real_secret_is_not_part_of_config(
    tmp_path: Path,
) -> None:
    path = write_config(
        tmp_path,
        valid_config_text(),
    )
    config = load_model_provider_config(path)

    secret = "private-secret-value"

    serialized = json.dumps(
        config.model_dump(mode="json")
    )

    assert secret not in serialized
    assert "TEST_MODEL_API_KEY" in serialized
