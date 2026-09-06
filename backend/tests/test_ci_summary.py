"""CI summaries must not publish raw request or credential values."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location("ci_summary", ROOT / ".github/scripts/test_summary.py")
summary = module_from_spec(spec)
spec.loader.exec_module(summary)


def test_summary_redacts_literal_values_and_connection_information():
    value = "synthetic-credential-for-testing"
    message = f'AssertionError: password="{value}" at https://api.example.test/?token={value}'
    redacted = summary.redact(message)
    assert value not in redacted
    assert "api.example.test" not in redacted
    assert "AssertionError" in redacted


def test_summary_preserves_test_identifiers_without_printing_failure_payload(tmp_path, capsys):
    xml = tmp_path / "results.xml"
    xml.write_text('<testsuite><testcase classname="suite" name="case">'
                   '<failure message="assert 1 == 2">private failure payload</failure>'
                   '</testcase></testsuite>')
    assert summary.report_xml([xml]) == 1
    output = capsys.readouterr().out
    assert "suite.case" in output
    assert "assert 1 == 2" in output
    assert "private failure payload" not in output
