from pathlib import Path

import protein_design_agent.agent.model_readiness as module
from protein_design_agent.agent.model_readiness import (
    assess_model_readiness,
    assess_model_setup,
    finalize_model_readiness,
    format_model_readiness,
    resolve_model_config_path,
)


def write_config(path: Path) -> None:
    path.write_text(
        """
schema_version: "0.1"
active_profile: test_profile
profiles:
  test_profile:
    kind: openai_compatible
    base_url: https://example.invalid
    model: test-model
    api_key_env: TEST_MODEL_API_KEY
    require_api_key: true
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_offline_does_not_require_config(
    tmp_path: Path,
) -> None:
    report = assess_model_readiness(
        allow_network=False,
        config_path=tmp_path / "missing.yaml",
        profile_name=None,
        environment={},
    )

    assert report.status == "OFFLINE"
    assert report.provider is None


def test_missing_config_is_not_configured() -> None:
    report = assess_model_readiness(
        allow_network=True,
        config_path=None,
        profile_name=None,
        environment={},
    )

    assert report.status == "NOT_CONFIGURED"
    assert report.provider is None


def test_missing_api_key_is_reported(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    report = assess_model_readiness(
        allow_network=True,
        config_path=config,
        profile_name=None,
        environment={},
    )

    assert report.status == (
        "MISSING_CREDENTIAL"
    )
    assert report.api_key_env == (
        "TEST_MODEL_API_KEY"
    )
    assert report.provider is None


def test_ready_initializes_without_network(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    secret = "do-not-display-this-value"

    report = assess_model_readiness(
        allow_network=True,
        config_path=config,
        profile_name=None,
        environment={
            "TEST_MODEL_API_KEY": secret,
        },
    )

    rendered = format_model_readiness(report)

    assert report.status == "READY"
    assert report.provider is not None
    assert report.profile_name == (
        "test_profile"
    )
    assert report.model_name == "test-model"

    assert secret not in rendered
    assert "尚未发送网络请求" in rendered


def test_unknown_profile_is_not_configured(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    report = assess_model_readiness(
        allow_network=True,
        config_path=config,
        profile_name="missing_profile",
        environment={
            "TEST_MODEL_API_KEY": "secret",
        },
    )

    assert report.status == "NOT_CONFIGURED"
    assert report.provider is None


def test_provider_initialization_error_is_reported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    monkeypatch.setattr(
        module,
        "build_request_parser_provider",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(
                RuntimeError(
                    "provider initialization failed"
                )
            )
        ),
    )

    report = assess_model_readiness(
        allow_network=True,
        config_path=config,
        profile_name=None,
        environment={
            "TEST_MODEL_API_KEY": "secret",
        },
    )

    assert report.status == "ERROR"
    assert report.provider is None

def test_default_workspace_model_config_is_discovered(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / ".protein-design-agent"

    result = resolve_model_config_path(
        explicit_path=None,
        workspace_root=workspace,
    )

    assert result == (
        workspace
        / "configs"
        / "models"
        / "deepseek.local.yaml"
    ).resolve()


def test_explicit_model_config_has_priority(
    tmp_path: Path,
) -> None:
    explicit = tmp_path / "custom.yaml"
    workspace = tmp_path / "workspace"

    result = resolve_model_config_path(
        explicit_path=explicit,
        workspace_root=workspace,
    )

    assert result == explicit.resolve()


def test_external_bundle_does_not_guess_config() -> None:
    result = resolve_model_config_path(
        explicit_path=None,
        workspace_root=None,
    )

    assert result is None


def test_missing_credential_has_safe_guidance(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    report = assess_model_readiness(
        allow_network=True,
        config_path=config,
        profile_name=None,
        environment={},
    )

    rendered = format_model_readiness(
        report,
        workspace_root=tmp_path,
        platform_name="linux",
    )

    assert "TEST_MODEL_API_KEY" in rendered
    assert "read -rsp" in rendered
    assert "export TEST_MODEL_API_KEY" in rendered
    assert str(config.resolve()) in rendered
    assert (
        "binderranker chat --profile test_profile"
        in rendered
    )
    assert "protein-design-agent" not in rendered
    assert "--allow-network" not in rendered
    assert (
        "不需要再运行其他 API Key 设置命令"
        in rendered
    )
    assert (
        "不要修改命令中的 TEST_MODEL_API_KEY"
        in rendered
    )
    assert (
        "Agent 会询问是否允许本次 Chat 调用模型 API"
        in rendered
    )


def test_missing_credential_uses_powershell_on_windows(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    report = assess_model_readiness(
        allow_network=True,
        config_path=config,
        profile_name=None,
        environment={},
    )

    rendered = format_model_readiness(
        report,
        workspace_root=tmp_path,
        platform_name="win32",
    )

    assert "PowerShell" in rendered
    assert "Read-Host" in rendered
    assert "-AsSecureString" in rendered
    assert "$env:TEST_MODEL_API_KEY" in rendered
    assert "read -rsp" not in rendered


def test_model_setup_can_be_available_without_authorization(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    setup = assess_model_setup(
        config_path=config,
        profile_name=None,
        environment={
            "TEST_MODEL_API_KEY": "secret",
        },
    )

    assert setup.status == "AVAILABLE"
    assert setup.provider is not None
    assert setup.profile_name == "test_profile"
    assert setup.model_name == "test-model"


def test_available_setup_can_enter_offline_session(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    setup = assess_model_setup(
        config_path=config,
        profile_name=None,
        environment={
            "TEST_MODEL_API_KEY": "secret",
        },
    )

    readiness = finalize_model_readiness(
        setup,
        network_allowed=False,
    )

    assert readiness.status == "OFFLINE"
    assert readiness.network_allowed is False
    assert readiness.provider is None
    assert readiness.profile_name == "test_profile"
    assert (
        "空任务的自然语言创建需要启用模型"
        in readiness.message
    )


def test_available_setup_can_enter_ready_session(
    tmp_path: Path,
) -> None:
    config = tmp_path / "models.yaml"
    write_config(config)

    setup = assess_model_setup(
        config_path=config,
        profile_name=None,
        environment={
            "TEST_MODEL_API_KEY": "secret",
        },
    )

    readiness = finalize_model_readiness(
        setup,
        network_allowed=True,
    )

    assert readiness.status == "READY"
    assert readiness.network_allowed is True
    assert readiness.provider is setup.provider

def test_model_setup_does_not_claim_network_authorization() -> None:
    setup = assess_model_setup(
        config_path=None,
        profile_name=None,
        environment={},
    )

    assert setup.status == "NOT_CONFIGURED"
    assert "已允许联网" not in setup.message
    assert "用户未允许" not in setup.message
    assert setup.provider is None
