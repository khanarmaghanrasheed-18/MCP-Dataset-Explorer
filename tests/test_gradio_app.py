import asyncio

import app
from state_store import StateStore


def test_gradio_upload_creates_dataset_and_session(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "store", StateStore(tmp_path / "state.db"))
    monkeypatch.setattr(app, "UPLOAD_DIR", tmp_path / "uploads")
    source = tmp_path / "scores.csv"
    source.write_text("score,group\n10,A\n20,B\n", encoding="utf-8")

    session_id, summary, preview, history, state, tools = app.handle_upload(str(source))

    assert app.store.get_session(session_id)["dataset"]["filename"] == "scores.csv"
    assert "2 rows" in summary
    assert preview.shape == (2, 2)
    assert history == []
    assert state["status"] == "new"
    assert tools == []


def test_gradio_question_displays_agent_result_without_calling_gemini(monkeypatch):
    async def fake_analysis(session_id, question):
        assert session_id == "session-1"
        assert question == "How many rows?"
        return {
            "answer": "There are 2 rows.",
            "state": {"status": "complete"},
            "tool_calls": [{"tool": "dataset_shape"}],
        }

    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    monkeypatch.setattr(app, "run_analysis", fake_analysis)

    textbox, history, state, tools = asyncio.run(
        app.handle_question("  How many rows?  ", "session-1", [])
    )

    assert textbox == ""
    assert history == [
        {"role": "user", "content": "How many rows?"},
        {"role": "assistant", "content": "There are 2 rows."},
    ]
    assert state["status"] == "complete"
    assert tools == [{"tool": "dataset_shape"}]
