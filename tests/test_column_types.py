import pandas as pd

from mcp_server import analyze_target, inspect_column


def test_string_columns_are_inspected_and_classified(tmp_path):
    path = tmp_path / "strings.csv"
    pd.DataFrame({"group": ["A", "B", "A"]}).to_csv(path, index=False)
    assert inspect_column(str(path), "group")["Most Common Values"] == {"A": 2, "B": 1}
    result = analyze_target(str(path), "group")
    assert result["Problem Type"] == "Classification"
    assert result["Most Common Values"] == {"A": 2, "B": 1}
