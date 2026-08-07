from pathlib import Path
from typing import Any

import pandas as pd
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("DatasetExplorer")


def load_dataset(path: str) -> pd.DataFrame:
    """Internal helper for loading a CSV file."""

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    if file_path.suffix.lower() != ".csv":
        raise ValueError("Only CSV files are currently supported.")

    return pd.read_csv(file_path)


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
        "features": df.columns.tolist(),
        "missing_values": df.isnull().sum().to_dict(),
        "categorical_columns": (
            df.select_dtypes(include=["object", "category"]).columns.tolist()
        ),
        "numerical_columns": (
            df.select_dtypes(include="number").columns.tolist()
        ),
        "data_types": df.dtypes.astype(str).to_dict(),
    }


@mcp.tool(
    name="dataset_shape",
    description="Returns the number of rows and columns in a CSV dataset.",
)
def get_dataset_shape(path: str) -> dict[str, int]:
    df = load_dataset(path)
    rows, columns = df.shape

    return {
        "rows": int(rows),
        "columns": int(columns),
    }


@mcp.tool(
    name="dataset_statistical_summary",
    description="Returns the mean and median of every numerical feature.",
)
def get_dataset_statistical_summary(path: str) -> dict[str, Any]:
    df = load_dataset(path)

    numerical_df = df.select_dtypes(include="number")

    if numerical_df.empty:
        return {
            "message": "The dataset contains no numerical columns.",
            "mean": {},
            "median": {},
        }

    return {
        "mean": numerical_df.mean().to_dict(),
        "median": numerical_df.median().to_dict(),
    }


@mcp.tool(
    name="Inspect_Column",
    description="Gives a detailed summary of a specific column/feature.",
)
def inspect_column(path: str, col_name: str) -> dict[str, Any]:
    df = load_dataset(path)

    if col_name not in df.columns:
        return {
            "error": f"Column '{col_name}' was not found.",
            "available_columns": df.columns.tolist()
        }

    series = df[col_name]

    if pd.api.types.is_numeric_dtype(series):
        return {
            "Feature": col_name,
            "Data Type": str(series.dtype),
            "Missing Values": int(series.isnull().sum()),
            "Unique Values": int(series.nunique()),
            "Minimum": float(series.min()),
            "Maximum": float(series.max()),
            "Mean": float(series.mean()),
        }
    elif series.dtype in ["object", "category"]:
        return {
            "Feature": col_name,
            "Data Type": str(series.dtype),
            "Missing Values": int(series.isnull().sum()),
            "Unique Values": int(series.nunique()),     
            "Most Common Values": series.value_counts().head(10).to_dict()
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
            "available_columns": df.columns.tolist()
        }

    series = df[target_name]

    if pd.api.types.is_numeric_dtype(series):
        if series.nunique() <= 5:
            problem_type = "Likely Classification"
        elif series.nunique() > 5:
            problem_type = "Likely Regression"

        return {
            "Feature": target_name,
            "Unique Values": int(series.nunique()),
            "Problem Type": problem_type,
            "Reason": f"Target has {int(series.nunique())} unique values.",
            "Data Type": str(series.dtype),
            "Type of Data": "Numerical",
            "Missing Values": int(series.isnull().sum()),
            "Minimum": float(series.min()),
            "Maximum": float(series.max()),
            "Mean": float(series.mean()),
            "Standard Deviation": float(series.std())
        }
    elif pd.api.types.is_object_dtype(series):
        return {
            "Feature": target_name,
            "Unique Values": int(series.nunique()),
            "Problem Type": "Classification",
            "Reason": f"Target has categorical data only.",
            "Data Type": str(series.dtype),
            "Type of Data": "Categorical",
            "Missing Values": int(series.isnull().sum()),
            "Most Common Values": series.value_counts().head(10).to_dict()
        }


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
        "total_rows": total_rows,
        "duplicate_rows": duplicate_count,
        "duplicate_percentage": round(
            duplicate_count / total_rows * 100, 2
        ) if total_rows > 0 else 0,
        "duplicate_examples": (
            df[duplicate_mask]
            .head(10)
            .to_dict(orient="records")
        )
    }

@mcp.tool(
    name="analyze_missing_values",
    description="Reports columns with missing values in the dataset."
)
def analyze_missing_values(path: str):
    df = load_dataset(path)
    total_rows = len(df)

    missing_vals = df.isna().sum()
    affected_cols = missing_vals[missing_vals>0]

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
            "missing_count": count,
            "missing_percentage": percentage,
            "missing_row_indices": missing_indices,
            "suggestion": suggestion,
        }

    return {
        "total_rows": int(total_rows),
        "columns_with_missing_values": int(len(affected_cols)),
        "rows_with_any_missing_value": (
            df.index[df.isna().any(axis=1)].tolist()
        ),
        "details": details,
    }


@mcp.tool(
    name="find_correlations",
    description=(
        "Finds strongly correlated numerical feature pairs "
        "above a specified absolute threshold."
    )
)
def find_correlations(path: str,threshold: float = 0.8) -> dict[str, Any]:
    df = load_dataset(path)

    numerical_df = df.select_dtypes(include="number")

    if numerical_df.shape[1] < 2:
        return {
            "message": "At least two numerical columns are required.",
            "strong_correlations": []
        }

    correlation_matrix = numerical_df.corr()

    strong_correlations = []

    cols = correlation_matrix.columns

    for i in range(len(cols)):
        for j in range(i+1, len(cols)):
            if abs(correlation_matrix.iloc[i, j]) >= threshold:
                correlation = correlation_matrix.iloc[i, j]
                feature_1 = cols[i]
                feature_2 = cols[j]
                strong_correlations.append(
                    {
                    "Feature 1": feature_1,
                    "Feature 2": feature_2,
                    "Correlation": correlation
                    }
                )

    return {
        "threshold": threshold,
        "strong_correlations": strong_correlations
    }


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
            "Count" : int(len(outlier)),
            "Index": outlier.index.tolist(),
            "Values": outlier.tolist(),
            "Lower Bound": float(lower_bound),
            "Upper Bound": float(upper_bound),
            "Percentage": round(len(outlier) / len(df) * 100,2),
            "Method": "IQR"
        }

    return outliers


@mcp.resource("dataset://guide")
def dataset_guide() -> str:
    return """
# Dataset Explorer MCP Server

This server provides exploratory analysis tools for CSV datasets.

Available capabilities:
- Inspect dataset dimensions and column types
- Generate numerical statistical summaries
- Inspect individual columns
- Analyze a potential target variable
- Detect duplicate rows
- Analyze missing values
- Find strongly correlated numerical features
- Detect numerical outliers using the IQR method

Important limitations:
- Only CSV files are currently supported.
- Outlier detection uses the IQR method.
- Correlation analysis uses Pandas Pearson correlation.
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
        You are exploring the CSV dataset located at:

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



if __name__ == "__main__":
    mcp.run(transport="stdio")