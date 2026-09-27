import pandas as pd

from mcp_server import screen_target_relationships


def relationship_by_feature(result, feature):
    for relationship in result["relationships"]:
        if relationship["feature"] == feature:
            return relationship
    raise AssertionError(f"Relationship for '{feature}' was not returned.")


def test_numerical_target_uses_pearson_and_eta_squared(tmp_path):
    dataframe = pd.DataFrame({
        "target": [1, 2, 3, 8, 9, 10],
        "numeric": [2, 4, 6, 16, 18, 20],
        "category": ["low", "low", "low", "high", "high", "high"],
    })
    path = tmp_path / "mixed.csv"
    dataframe.to_csv(path, index=False)

    result = screen_target_relationships(str(path), "target")
    numeric = relationship_by_feature(result, "numeric")
    category = relationship_by_feature(result, "category")

    assert numeric["relationship_type"] == "numerical_to_numerical"
    assert numeric["correlation"] == 1.0
    assert category["relationship_type"] == "categorical_to_numerical"
    assert category["eta_squared"] > 0.8


def test_categorical_target_uses_eta_squared_and_cramers_v(tmp_path):
    dataframe = pd.DataFrame({
        "target": ["yes", "yes", "yes", "no", "no", "no"],
        "numeric": [1, 2, 3, 8, 9, 10],
        "category": ["A", "A", "A", "B", "B", "B"],
    })
    path = tmp_path / "mixed.csv"
    dataframe.to_csv(path, index=False)

    result = screen_target_relationships(str(path), "target")
    numeric = relationship_by_feature(result, "numeric")
    category = relationship_by_feature(result, "category")

    assert numeric["relationship_type"] == "numerical_to_categorical"
    assert numeric["eta_squared"] > 0.8
    assert category["relationship_type"] == "categorical_to_categorical"
    assert category["cramers_v"] == 1.0


def test_constant_numerical_column_is_reported(tmp_path):
    dataframe = pd.DataFrame({"target": [1, 2, 3], "constant": [5, 5, 5]})
    path = tmp_path / "constant.csv"
    dataframe.to_csv(path, index=False)

    result = screen_target_relationships(str(path), "target")
    relationship = relationship_by_feature(result, "constant")

    assert relationship["correlation"] is None
    assert "constant" in relationship["reason"].lower()


def test_invalid_target_returns_available_columns(tmp_path):
    dataframe = pd.DataFrame({"value": [1, 2, 3]})
    path = tmp_path / "sample.csv"
    dataframe.to_csv(path, index=False)

    result = screen_target_relationships(str(path), "missing")
    assert result["available_columns"] == ["value"]
