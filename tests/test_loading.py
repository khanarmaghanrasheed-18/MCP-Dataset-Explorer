from pathlib import Path

import pandas as pd
import pytest

from mcp_server import load_dataset


@pytest.fixture
def sample_dataframe():
    return pd.DataFrame({
        "score": [10, 20, 30],
        "group": ["A", "B", "A"],
    })


@pytest.mark.parametrize("extension", ["csv", "tsv", "json", "xlsx", "parquet"])
def test_load_supported_formats(tmp_path, sample_dataframe, extension):
    path = tmp_path / f"sample.{extension}"

    if extension == "csv":
        sample_dataframe.to_csv(path, index=False)
    elif extension == "tsv":
        sample_dataframe.to_csv(path, sep="\t", index=False)
    elif extension == "json":
        sample_dataframe.to_json(path, orient="records")
    elif extension == "xlsx":
        sample_dataframe.to_excel(path, index=False)
    elif extension == "parquet":
        sample_dataframe.to_parquet(path, index=False)

    loaded = load_dataset(str(path))
    assert loaded.shape == (3, 2)
    assert loaded.columns.tolist() == ["score", "group"]


def test_load_rejects_unknown_format(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("not a supported dataset", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported dataset format"):
        load_dataset(str(path))


def test_load_legacy_excel():
    path = Path(__file__).parent / "fixtures" / "sample.xls"
    loaded = load_dataset(str(path))
    assert loaded.to_dict(orient="list") == {"score": [10, 20, 30], "group": ["A", "B", "A"]}
