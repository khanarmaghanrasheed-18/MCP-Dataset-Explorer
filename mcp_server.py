import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("DatasetExplorer")


# =============================================================================
# DATA LOADING
# =============================================================================

def load_dataset(path: str) -> pd.DataFrame:
    """Load a supported tabular dataset into a Pandas DataFrame."""

    file_path = Path(path).expanduser()

    if not file_path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    extension = file_path.suffix.lower()

    if extension == ".csv":
        return pd.read_csv(file_path)

    if extension == ".tsv":
        return pd.read_csv(file_path, sep="\t")

    if extension in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)

    if extension == ".json":
        return pd.read_json(file_path)

    if extension == ".parquet":
        return pd.read_parquet(file_path)

    supported_extensions = ".csv, .tsv, .xlsx, .xls, .json, .parquet"
    raise ValueError(
        f"Unsupported dataset format '{extension}'. "
        f"Supported formats: {supported_extensions}."
    )


# =============================================================================
# DATASET INFORMATION TOOLS
# =============================================================================


@mcp.tool(
    name="get_dataset_overview",
    description=(
        "Returns dataset features, missing-value counts, "
        "categorical columns, numerical columns, and data types."
    ),
)
def get_dataset_overview(path: str) -> dict[str, Any]:
    df = load_dataset(path)

    return {
        "features": df.columns.tolist(), "missing_values": df.isnull().sum().to_dict(),
        "categorical_columns": df.select_dtypes(
            include=["object", "category"]
        ).columns.tolist(),
        "numerical_columns": df.select_dtypes(include="number").columns.tolist(),
        "data_types": df.dtypes.astype(str).to_dict(),
    }


@mcp.tool(
    name="dataset_shape",
    description="Returns the number of rows and columns in a dataset.",
)
def get_dataset_shape(path: str) -> dict[str, int]:
    df = load_dataset(path)
    rows, columns = df.shape

    return {"rows": int(rows), "columns": int(columns)}


# =============================================================================
# DESCRIPTIVE STATISTICS TOOLS
# =============================================================================

@mcp.tool(
    name="dataset_statistical_summary",
    description="Returns the mean and median of every numerical feature.",
)
def get_dataset_statistical_summary(path: str) -> dict[str, Any]:
    df = load_dataset(path)

    numerical_df = df.select_dtypes(include="number")

    if numerical_df.empty:
        return {
            "message": "The dataset contains no numerical columns.", "mean": {}, "median": {},
        }

    return {
        "mean": numerical_df.mean().to_dict(), "median": numerical_df.median().to_dict(),
    }


@mcp.tool(
    name="inspect_Column",
    description="Gives a detailed summary of a specific column/feature.",
)
def inspect_column(path: str, col_name: str) -> dict[str, Any]:
    df = load_dataset(path)

    if col_name not in df.columns:
        return {
            "error": f"Column '{col_name}' was not found.",
            "available_columns": df.columns.tolist(),
        }

    series = df[col_name]

    if pd.api.types.is_numeric_dtype(series):
        return {
            "Feature": col_name, "Data Type": str(series.dtype),
            "Missing Values": int(series.isnull().sum()), "Unique Values": int(series.nunique()),
            "Minimum": float(series.min()), "Maximum": float(series.max()),
            "Mean": float(series.mean()),
        }
    elif pd.api.types.is_string_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype):
        return {
            "Feature": col_name, "Data Type": str(series.dtype),
            "Missing Values": int(series.isnull().sum()), "Unique Values": int(series.nunique()),
            "Most Common Values": series.value_counts().head(10).to_dict(),
        }


@mcp.tool(
    name="analyze_target",
    description="Gives a detailed summary of the target column.",
)
def analyze_target(path: str, target_name: str) -> dict[str, Any]:
    df = load_dataset(path)

    if target_name not in df.columns:
        return {
            "error": f"Target '{target_name}' was not found.",
            "available_columns": df.columns.tolist(),
        }

    series = df[target_name]

    if pd.api.types.is_numeric_dtype(series):
        if series.nunique() <= 5:
            problem_type = "Likely Classification"
        elif series.nunique() > 5:
            problem_type = "Likely Regression"

        return {
            "Feature": target_name, "Unique Values": int(series.nunique()),
            "Problem Type": problem_type,
            "Reason": f"Target has {int(series.nunique())} unique values.",
            "Data Type": str(series.dtype), "Type of Data": "Numerical",
            "Missing Values": int(series.isnull().sum()), "Minimum": float(series.min()),
            "Maximum": float(series.max()), "Mean": float(series.mean()),
            "Standard Deviation": float(series.std()),
        }
    elif pd.api.types.is_string_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype):
        return {
            "Feature": target_name, "Unique Values": int(series.nunique()),
            "Problem Type": "Classification",
            "Reason": f"Target has categorical data only.",
            "Data Type": str(series.dtype), "Type of Data": "Categorical",
            "Missing Values": int(series.isnull().sum()),
            "Most Common Values": series.value_counts().head(10).to_dict(),
        }


# =============================================================================
# DATA QUALITY TOOLS
# =============================================================================

@mcp.tool(
    name="duplicate_finder",
    description="Reports duplicate rows in the dataset."
)
def find_duplicated_data(path: str) -> dict[str, Any]:
    df = load_dataset(path)

    duplicate_mask = df.duplicated()
    duplicate_count = int(duplicate_mask.sum())
    total_rows = len(df)

    return {
        "total_rows": total_rows, "duplicate_rows": duplicate_count,
        "duplicate_percentage": round(duplicate_count / total_rows * 100, 2)
        if total_rows > 0 else 0,
        "duplicate_examples": df[duplicate_mask].head(10).to_dict(orient="records"),
    }

@mcp.tool(
    name="analyze_missing_values",
    description="Reports columns with missing values in the dataset."
)
def analyze_missing_values(path: str):
    df = load_dataset(path)
    total_rows = len(df)

    missing_vals = df.isna().sum()
    affected_cols = missing_vals[missing_vals > 0]

    details = {}

    for col, count in affected_cols.items():
        series = df[col]
        count = int(count)

        percentage = round((count/total_rows) * 100, 2) if total_rows else 0
        missing_indices = df.index[series.isna()].tolist()

        if pd.api.types.is_numeric_dtype(series):
            if percentage <= 5:
                suggestion = (
                    "Consider median imputation. Mean may be suitable if "
                    "the feature is approximately symmetric and has no major outliers."
                )
            elif percentage <= 30:
                suggestion = (
                    "Investigate why values are missing. Consider median imputation, "
                    "model-based imputation, or dropping the feature depending on importance."
                )
            else:
                suggestion = (
                    "A large portion of this feature is missing. Consider dropping "
                    "the feature unless it is important and can be reliably imputed."
                )
        else:
            if percentage <= 5:
                suggestion = (
                    "Consider mode imputation or introducing an 'Unknown' category."
                )
            elif percentage <= 30:
                suggestion = (
                    "Investigate the missingness pattern. Consider an 'Unknown' "
                    "category or dropping affected rows when appropriate."
                )
            else:
                suggestion = (
                    "A large portion of this feature is missing. Consider dropping "
                    "the feature unless it provides important information."
                )

        details[col] = {
            "missing_count": count, "missing_percentage": percentage,
            "missing_row_indices": missing_indices, "suggestion": suggestion,
        }

    return {
        "total_rows": int(total_rows), "columns_with_missing_values": int(len(affected_cols)),
        "rows_with_any_missing_value": df.index[df.isna().any(axis=1)].tolist(),
        "details": details,
    }


# =============================================================================
# RELATIONSHIP AND ANALYTICS TOOLS
# =============================================================================

@mcp.tool(
    name="find_correlations",
    description=(
        "Finds strongly correlated numerical feature pairs "
        "above a specified absolute threshold."
    )
)
def find_correlations(path: str, threshold: float = 0.8) -> dict[str, Any]:
    df = load_dataset(path)

    numerical_df = df.select_dtypes(include="number")

    if numerical_df.shape[1] < 2:
        return {
            "message": "At least two numerical columns are required.",
            "strong_correlations": [],
        }

    correlation_matrix = numerical_df.corr()

    strong_correlations = []

    cols = correlation_matrix.columns

    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            if abs(correlation_matrix.iloc[i, j]) >= threshold:
                correlation = correlation_matrix.iloc[i, j]
                feature_1 = cols[i]
                feature_2 = cols[j]
                strong_correlations.append({
                    "Feature 1": feature_1, "Feature 2": feature_2,
                    "Correlation": round(float(correlation), 4),
                })

    return {"threshold": threshold, "strong_correlations": strong_correlations}


@mcp.tool(
    name="detect_outliers",
    description="Detects Outliers in the dataset."
)
def detect_outliers(path: str):
    df = load_dataset(path)

    numerical_df = df.select_dtypes(include="number")

    outliers = {}

    for col in numerical_df.columns:
        series = df[col]

        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1

        lower_bound = q1 - (iqr * 1.5)
        upper_bound = q3 + (iqr * 1.5)

        outlier = series[(series < lower_bound) | (series > upper_bound)]

        if len(outlier) <= 0:
            continue

        outliers[col] = {
            "Count": int(len(outlier)), "Index": outlier.index.tolist(),
            "Values": outlier.tolist(), "Lower Bound": float(lower_bound),
            "Upper Bound": float(upper_bound),
            "Percentage": round(len(outlier) / len(df) * 100, 2),
            "Method": "IQR",
        }

    return outliers


# -----------------------------------------------------------------------------
# Target relationship screening
# -----------------------------------------------------------------------------

@mcp.tool(
    name="screen_target_relationships",
    description=(
        "Screens numerical-numerical relationships with Pearson correlation "
        "and numerical-categorical relationships with correlation ratio eta "
        "squared. Screens categorical-categorical relationships with "
        "Cramer's V."
    )
)
def screen_target_relationships(path: str, target: str) -> dict[str, Any]:
    df = load_dataset(path)

    if target not in df.columns:
        return {
            "error": f"Target '{target}' was not found.",
            "available_columns": df.columns.tolist(),
        }

    target_is_numerical = pd.api.types.is_numeric_dtype(df[target])
    numerical_features = []
    categorical_features = []

    for column in df.columns:
        if column == target:
            continue

        if pd.api.types.is_numeric_dtype(df[column]):
            numerical_features.append(column)
        else:
            categorical_features.append(column)

    relationships = []

    pearson_features = []

    if target_is_numerical:
        for feature in numerical_features:
            pearson_features.append(feature)

    for feature in pearson_features:
        paired_data = df[[feature, target]].dropna()
        x_values = paired_data[feature].astype(float).tolist()
        y_values = paired_data[target].astype(float).tolist()
        sample_size = len(paired_data)

        if sample_size < 2:
            relationships.append({
                "feature": feature, "feature_type": "numerical",
                "relationship_type": "numerical_to_numerical",
                "method": "Pearson correlation", "sample_size": sample_size,
                "correlation": None, "score": None,
                "reason": "At least two complete value pairs are required.",
            })
            continue

        mean_x = sum(x_values) / sample_size
        mean_y = sum(y_values) / sample_size

        cross_deviation = 0.0
        squared_deviation_x = 0.0
        squared_deviation_y = 0.0

        for x_value, y_value in zip(x_values, y_values):
            deviation_x = x_value - mean_x
            deviation_y = y_value - mean_y
            cross_deviation += deviation_x * deviation_y
            squared_deviation_x += deviation_x ** 2
            squared_deviation_y += deviation_y ** 2

        denominator = (squared_deviation_x * squared_deviation_y) ** 0.5

        if denominator == 0:
            relationships.append({
                "feature": feature, "feature_type": "numerical",
                "relationship_type": "numerical_to_numerical",
                "method": "Pearson correlation", "sample_size": sample_size,
                "correlation": None, "score": None,
                "reason": "Correlation is undefined for a constant column.",
            })
            continue

        correlation = cross_deviation / denominator
        absolute_correlation = abs(correlation)

        if absolute_correlation >= 0.7:
            strength = "strong"
        elif absolute_correlation >= 0.4:
            strength = "moderate"
        elif absolute_correlation >= 0.2:
            strength = "weak"
        else:
            strength = "very weak"

        if correlation > 0:
            direction = "positive"
        elif correlation < 0:
            direction = "negative"
        else:
            direction = "none"

        relationships.append({
            "feature": feature, "feature_type": "numerical",
            "relationship_type": "numerical_to_numerical",
            "method": "Pearson correlation", "sample_size": sample_size,
            "correlation": round(float(correlation), 4),
            "score": round(float(absolute_correlation), 4),
            "direction": direction, "strength": strength,
        })

    if target_is_numerical:
        mixed_pairs = []

        for feature in categorical_features:
            pair = (feature, target, feature, "categorical_to_numerical")
            mixed_pairs.append(pair)
    else:
        mixed_pairs = []

        for feature in numerical_features:
            pair = (target, feature, feature, "numerical_to_categorical")
            mixed_pairs.append(pair)

    for category_column, numerical_column, feature, relation_type in mixed_pairs:
        paired_data = df[[category_column, numerical_column]].dropna()
        sample_size = len(paired_data)
        category_count = int(paired_data[category_column].nunique())

        if pd.api.types.is_numeric_dtype(df[feature]):
            feature_type = "numerical"
        else:
            feature_type = "categorical"

        result = {
            "feature": feature, "feature_type": feature_type,
            "relationship_type": relation_type,
            "method": "Correlation ratio (eta squared)",
            "sample_size": sample_size, "category_column": category_column,
            "numerical_column": numerical_column,
        }

        if sample_size < 2 or category_count < 2:
            result.update({
                "eta_squared": None, "score": None,
                "reason": "At least two non-empty categories are required.",
            })
            relationships.append(result)
            continue

        numerical_values = paired_data[numerical_column].astype(float)
        overall_mean = float(numerical_values.mean())
        total_variation = float(((numerical_values - overall_mean) ** 2).sum())

        group_summaries = []
        between_group_variation = 0.0

        for category, group in paired_data.groupby(
            category_column, observed=True, sort=False
        ):
            values = group[numerical_column].astype(float)
            group_size = len(values)
            group_mean = float(values.mean())
            group_std = values.std()

            between_group_variation += group_size * (group_mean - overall_mean) ** 2
            group_summaries.append({
                "category": str(category), "count": int(group_size),
                "mean": round(group_mean, 4),
                "median": round(float(values.median()), 4),
                "standard_deviation": round(float(group_std), 4)
                if not pd.isna(group_std) else None,
            })

        if total_variation == 0:
            result.update({
                "eta_squared": None, "score": None, "groups": group_summaries,
                "reason": "The numerical column is constant, so eta squared is undefined.",
            })
            relationships.append(result)
            continue

        eta_squared = between_group_variation / total_variation

        if eta_squared >= 0.14:
            strength = "strong"
        elif eta_squared >= 0.06:
            strength = "moderate"
        elif eta_squared >= 0.01:
            strength = "weak"
        else:
            strength = "very weak"

        result.update({
            "eta_squared": round(float(eta_squared), 4),
            "score": round(float(eta_squared), 4),
            "strength": strength, "groups": group_summaries,
        })
        relationships.append(result)

    # Case 4: categorical feature -> categorical target.
    if not target_is_numerical:
        for feature in categorical_features:
            paired_data = df[[feature, target]].dropna()
            sample_size = len(paired_data)
            feature_category_count = int(paired_data[feature].nunique())
            target_category_count = int(paired_data[target].nunique())

            result = {
                "feature": feature, "feature_type": "categorical",
                "relationship_type": "categorical_to_categorical",
                "method": "Cramer's V", "sample_size": sample_size,
            }

            if (sample_size == 0 or feature_category_count < 2
                    or target_category_count < 2):
                result.update({
                    "cramers_v": None, "score": None,
                    "reason": "Both columns require at least two non-empty categories.",
                })
                relationships.append(result)
                continue

            contingency_table = pd.crosstab(paired_data[feature], paired_data[target])
            row_totals = contingency_table.sum(axis=1)
            column_totals = contingency_table.sum(axis=0)
            chi_squared = 0.0

            for row_position in range(contingency_table.shape[0]):
                for column_position in range(contingency_table.shape[1]):
                    observed = float(
                        contingency_table.iloc[row_position, column_position]
                    )
                    expected = float(
                        row_totals.iloc[row_position]
                        * column_totals.iloc[column_position]
                        / sample_size
                    )

                    if expected > 0:
                        difference = observed - expected
                        chi_squared += (difference ** 2) / expected

            smaller_dimension = min(feature_category_count - 1, target_category_count - 1)
            denominator = sample_size * smaller_dimension
            cramers_v = (chi_squared / denominator) ** 0.5

            if cramers_v >= 0.5:
                strength = "strong"
            elif cramers_v >= 0.3:
                strength = "moderate"
            elif cramers_v >= 0.1:
                strength = "weak"
            else:
                strength = "very weak"

            contingency_rows = []

            for category, row in contingency_table.iterrows():
                counts = {}

                for target_category, count in row.items():
                    counts[str(target_category)] = int(count)

                contingency_rows.append({
                    "category": str(category), "target_counts": counts,
                })

            result.update({
                "cramers_v": round(float(cramers_v), 4),
                "score": round(float(cramers_v), 4), "strength": strength,
                "contingency_table": contingency_rows,
            })
            relationships.append(result)

    relationships.sort(
        key=lambda result: (
            result.get("score") is not None,
            result.get("score") or 0,
        ),
        reverse=True,
    )

    if target_is_numerical:
        target_type = "numerical"
    else:
        target_type = "categorical"

    return {
        "target": target, "target_type": target_type,
        "methods": [
            "Pearson correlation",
            "Correlation ratio (eta squared)",
            "Cramer's V",
        ],
        "relationships": relationships,
        "note": (
            "These scores measure association and do not establish causation. "
            "Eta squared compares numerical values across categories. "
            "Cramer's V measures association between categorical columns."
        ),
    }

# =============================================================================
# MCP RESOURCE AND PROMPT DEFINITIONS
# =============================================================================

@mcp.resource("dataset://guide")
def dataset_guide() -> str:
    return """
# Dataset Explorer MCP Server

This server provides exploratory analysis tools for tabular datasets.

Supported formats:
- CSV
- TSV
- Excel (.xlsx and .xls; the first sheet is loaded)
- JSON
- Parquet

Available capabilities:
- Inspect dataset dimensions and column types
- Generate numerical statistical summaries
- Inspect individual columns
- Analyze a potential target variable
- Detect duplicate rows
- Analyze missing values
- Find strongly correlated numerical features
- Detect numerical outliers using the IQR method
- Screen numerical and categorical features against a target

Important limitations:
- Excel analysis currently loads the first worksheet.
- Outlier detection uses the IQR method.
- Numerical relationships use Pearson correlation.
- Mixed relationships use correlation ratio eta squared.
- Categorical relationships use Cramer's V.
- Target classification/regression detection is heuristic.
- The server provides analysis, not automatic model training.
- Recommendations should be interpreted in the context of the dataset.
"""

@mcp.prompt()
def explore_dataset(path: str, target_name: str = "") -> str:
    target_instruction = (
        f"Analyze '{target_name}' as the target variable."
        if target_name
        else
        "No target variable was specified. Do not assume one."
    )

    return f"""
        You are exploring the tabular dataset located at:

        {path}

        Perform a structured exploratory analysis using the available
        Dataset Explorer MCP tools.

        Follow this workflow:

        1. Inspect the dataset overview and dimensions.
        2. Examine numerical summary statistics.
        3. Check for missing values.
        4. Check for duplicate observations.
        5. Identify strongly correlated numerical features.
        6. Detect numerical outliers.
        7. {target_instruction}

        After gathering the results, summarize:

        - dataset structure
        - important data-quality issues
        - notable correlations
        - notable outliers
        - target characteristics, if provided
        - issues that should be investigated before model training

        Do not invent information that was not returned by the tools.
        Do not automatically remove, impute, or modify data.
    """


# =============================================================================
# SERVER ENTRY POINT
# =============================================================================

def main() -> None:
    """Start the local MCP server; stdout belongs exclusively to the protocol."""
    parser = argparse.ArgumentParser(description="Analyze local datasets through MCP stdio.")
    parser.add_argument("--version", action="version", version="%(prog)s 0.2.1")
    parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
