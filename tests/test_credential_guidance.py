import pytest

from protein_design_agent.agent.credential_guidance import (
    secure_api_key_commands,
)


def test_posix_api_key_command_uses_hidden_prompt() -> None:
    commands = secure_api_key_commands(
        "TEST_API_KEY",
        platform_name="linux",
    )

    assert len(commands) == 1
    assert "read -rsp" in commands[0]
    assert "export TEST_API_KEY" in commands[0]
    assert "你的真实 API Key" not in commands[0]


def test_powershell_api_key_commands_use_secure_string() -> None:
    commands = secure_api_key_commands(
        "TEST_API_KEY",
        platform_name="win32",
    )
    rendered = "\n".join(commands)

    assert len(commands) == 3
    assert "Read-Host" in rendered
    assert "-AsSecureString" in rendered
    assert "$env:TEST_API_KEY" in rendered
    assert "Remove-Variable" in rendered
    assert "read -rsp" not in rendered


@pytest.mark.parametrize(
    "name",
    [
        "",
        "BAD-NAME",
        "NAME; Write-Host secret",
    ],
)
def test_api_key_environment_name_is_validated(
    name: str,
) -> None:
    with pytest.raises(ValueError):
        secure_api_key_commands(
            name,
            platform_name="linux",
        )
