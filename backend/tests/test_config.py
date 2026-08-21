"""Step 2 验收：配置测试。

用 Settings(_env_file=None) 隔离真实 .env，只从 monkeypatch 的环境变量构造，
保证测试不受本地密钥影响、也不污染真实配置。
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, settings

REQUIRED = {
    "LLM_MODEL_ID": "test-model",
    "LLM_API_KEY": "sk-test",
    "LLM_BASE_URL": "https://api.example.com",
    "AMAP_API_KEY": "amap-test-key",
}


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    env = {**REQUIRED, **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_settings_load_and_type_coercion(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量字符串自动转 int（类型化）。"""
    s = _make_settings(monkeypatch, LLM_TIMEOUT="90", PORT="9999")
    assert s.llm_timeout == 90
    assert s.port == 9999


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _make_settings(monkeypatch)
    assert s.llm_timeout == 60
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.log_level == "INFO"


def test_missing_required_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """核心验收：缺 AMAP_API_KEY 时构造即抛 ValidationError（启动即校验）。"""
    for key, value in REQUIRED.items():
        if key != "AMAP_API_KEY":
            monkeypatch.setenv(key, value)
    monkeypatch.delenv("AMAP_API_KEY", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    assert "amap_api_key" in str(exc_info.value).lower()


def test_empty_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """空字符串密钥同样拒绝（min_length=1）。"""
    with pytest.raises(ValidationError):
        _make_settings(monkeypatch, LLM_API_KEY="")


def test_invalid_port_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _make_settings(monkeypatch, PORT="70000")


def test_cors_origins_list(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _make_settings(monkeypatch, CORS_ORIGINS="http://a.com, http://b.com ,")
    assert s.get_cors_origins_list() == ["http://a.com", "http://b.com"]


@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / ".env").exists(),
    reason="本地无 .env 文件（CI 环境）",
)
def test_real_env_file_satisfies_contract() -> None:
    """守护测试：真实 .env 必须满足所有必填项，否则模块导入即失败。"""
    assert settings.llm_model_id
    assert settings.llm_api_key
    assert settings.llm_base_url
    assert settings.amap_api_key
    assert settings.get_cors_origins_list()
