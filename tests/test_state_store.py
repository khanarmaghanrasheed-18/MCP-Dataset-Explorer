from state_store import StateStore


def test_session_state_and_tool_cache(tmp_path):
    store = StateStore(tmp_path / "state.db")
    schema = {"rows": 3, "columns": 2, "column_details": []}
    dataset = store.create_dataset(
        "sample.csv", str(tmp_path / "sample.csv"), ".csv", "abc", 3, 2, schema
    )
    session = store.create_session(dataset)

    assert session["state"]["status"] == "new"
    assert session["state"]["dataset_summary"] == schema

    state = session["state"]
    state["goal"] = "Understand the target"
    store.save_state(session["id"], state)
    assert store.get_session(session["id"])["state"]["goal"] == "Understand the target"

    arguments = {"target": "price"}
    result = {"score": 0.8}
    cache_key = store.cache_key("abc", "screen_target_relationships", arguments)
    store.save_cached_result(cache_key, dataset["id"], "screen_target_relationships", arguments,
                             result)

    assert store.get_cached_result(cache_key) == result
