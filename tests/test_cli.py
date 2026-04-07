import json
from pathlib import Path

import pytest_mock
from typer.testing import CliRunner

from manascope.cli import app

runner = CliRunner()


def test_pipeline_command(mocker: pytest_mock.MockerFixture, tmp_path: Path) -> None:
    mock_run_analyze = mocker.patch("manascope.analyze.run")
    mock_run_review = mocker.patch("manascope.review.run")

    # Setup mock returns
    mock_run_analyze.return_value = {"mana": {"raw": 100}}
    mock_run_review.return_value = {"stats": {"in_deck": 10}}

    # Create a dummy decklist
    decklist_file = tmp_path / "dummy.txt"
    decklist_file.write_text("1 Commander\n")

    # Run the command
    result = runner.invoke(app, ["pipeline", "--decklist", str(decklist_file)])

    assert result.exit_code == 0

    # Parse the output
    output_data = json.loads(result.stdout)
    assert "analyze" in output_data
    assert "review" in output_data
    assert output_data["analyze"]["mana"]["raw"] == 100
    assert output_data["review"]["stats"]["in_deck"] == 10


def test_analyze_json_flag(mocker: pytest_mock.MockerFixture, tmp_path: Path) -> None:
    mock_run_analyze = mocker.patch("manascope.analyze.run")
    decklist_file = tmp_path / "dummy.txt"
    decklist_file.write_text("1 Commander\n")

    result = runner.invoke(app, ["analyze", "--decklist", str(decklist_file), "--json"])
    assert result.exit_code == 0
    mock_run_analyze.assert_called_once()
    assert mock_run_analyze.call_args[1]["json_flag"] is True


def test_review_json_flag(mocker: pytest_mock.MockerFixture, tmp_path: Path) -> None:
    mock_run_review = mocker.patch("manascope.review.run")
    decklist_file = tmp_path / "dummy.txt"
    decklist_file.write_text("1 Commander\n")

    result = runner.invoke(app, ["review", "--decklist", str(decklist_file), "--json"])
    assert result.exit_code == 0
    mock_run_review.assert_called_once()
    assert mock_run_review.call_args[1]["json_flag"] is True


def test_edhrec_json_flag(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("manascope.edhrec.open_cache")
    mocker.patch("manascope.edhrec.fetch_commander", return_value={"header": "Test Commander"})
    mocker.patch("manascope.edhrec.num_decks", return_value=100)

    mock_td = mocker.Mock()
    mock_td._asdict.return_value = {"Creature": 10}
    mocker.patch("manascope.edhrec.type_distribution", return_value=mock_td)
    mocker.patch("manascope.edhrec.mana_curve", return_value={"1": 5})
    mocker.patch("manascope.edhrec.high_synergy_cards", return_value=[])
    mocker.patch("manascope.edhrec.combos", return_value=[])
    mocker.patch("manascope.edhrec.tags", return_value=[])

    result = runner.invoke(app, ["edhrec", "Test", "Commander", "--json"])
    assert result.exit_code == 0
    output_data = json.loads(result.stdout)
    assert output_data["name"] == "Test Commander"
    assert output_data["num_decks"] == 100
