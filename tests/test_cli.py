from typer.testing import CliRunner

from asset_scout.cli import app


def test_doctor_json(tmp_path):
    result = CliRunner().invoke(app, ["--json", "--root", str(tmp_path), "doctor"])
    assert result.exit_code == 0, result.output
    assert '"version": "0.2.0"' in result.output
    assert '"project_initialized": false' in result.output
