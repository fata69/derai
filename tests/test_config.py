"""Environment contract: the flag gates both job kinds, and max_pages remains text."""

import pytest

from derai_scheduler.config import Settings


def config(**overrides: str) -> Settings:
    return Settings.from_env(
        {"DATABASE_URL": "postgresql://derai_worker@localhost/derai", **overrides}
    )


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", " TRUE ", "\tYes\n", "On"])
def test_flag_accepts_exact_trimmed_case_insensitive_truth_values(value: str) -> None:
    assert config(SOCIAL_COLLECTION_ENABLED=value).enabled is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no", "enabled", "2", "truthy"])
def test_all_other_flag_values_disable_both_job_kinds(value: str) -> None:
    assert config(SOCIAL_COLLECTION_ENABLED=value).enabled is False


def test_runtime_defaults_match_compose_contract() -> None:
    settings = config()
    assert settings.worker_interval == 60
    assert settings.enabled is True
    assert settings.article_max_pages == "1"


def test_news_option_retains_environment_string() -> None:
    assert config(CONNECTOR_ARTICLE_MAX_PAGES="3").article_max_pages == "3"
    assert config(CONNECTOR_ARTICLE_MAX_PAGES="").article_max_pages == ""


@pytest.mark.parametrize("interval", ["0", "-1", "nan", "inf", "bad", ""])
def test_invalid_interval_is_rejected_at_startup(interval: str) -> None:
    with pytest.raises(ValueError):
        config(WORKER_INTERVAL=interval)
