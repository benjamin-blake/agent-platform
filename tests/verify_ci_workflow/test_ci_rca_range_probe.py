from scripts.checks.ci_guards.validate_ci_workflow_guards import _allowed_log_redirect


def test_signed_redirect_policy_never_needs_to_render_query() -> None:
    assert _allowed_log_redirect("https://results-receiver.actions.githubusercontent.com/path?sig=SECRET")
    assert _allowed_log_redirect("https://productionresults.blob.core.windows.net/path?sig=SECRET")
    assert not _allowed_log_redirect("http://results-receiver.actions.githubusercontent.com/path?sig=SECRET")
    assert not _allowed_log_redirect("https://actions.githubusercontent.com.evil.test/path?sig=SECRET")
