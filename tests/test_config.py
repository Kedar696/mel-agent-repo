"""mel.config: one place every MEL_* setting is read."""

import mel.config as config

_READ_DOTENV = config._dotenv.__wrapped__  # the real reader, taken before conftest swaps it out


def test_env_reads_process_then_dotenv_then_default(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("# comment\nMEL_X='from-file'\nMEL_EMPTY=\n", encoding="utf-8")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "_dotenv", _READ_DOTENV)
    monkeypatch.delenv("MEL_X", raising=False)
    assert config.env("MEL_X") == "from-file"
    assert config.env("MEL_EMPTY", "d") == "d" and config.env("MEL_MISSING") == ""
    monkeypatch.setenv("MEL_X", " from-env ")
    assert config.env("MEL_X") == "from-env"
    monkeypatch.setenv("MEL_X", "")
    assert config.env("MEL_X") == "from-file"  # empty counts as unset


def test_flag_and_region(monkeypatch):
    for name in ("MEL_F", "MEL_BEDROCK_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(name, raising=False)
    assert config.flag("MEL_F") is False
    monkeypatch.setenv("MEL_F", "1")
    assert config.flag("MEL_F") is True
    assert config.bedrock_region() == ""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("MEL_BEDROCK_REGION", "us-west-2")
    assert config.bedrock_region() == "us-west-2"


def test_full_pack_yields_to_mel_data_dir(monkeypatch):
    monkeypatch.delenv("MEL_DATA_DIR", raising=False)
    assert config.full_pack() == (config.PACK_DATA / "insights.jsonl").exists()
    monkeypatch.setenv("MEL_DATA_DIR", "data/mock")
    assert config.full_pack() is False
