from app.cli import main


def test_validate_and_gate(tmp_path):
    assert main(["validate"]) == 0
    assert main(["gate", "--out", str(tmp_path / "g.json")]) == 0
