from pathlib import Path

from streamlit.testing.v1 import AppTest

import db


def test_navigation_and_weekly_save_survive_new_session(database):
    db.init_db()
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    assert not app.exception
    app.sidebar.radio[0].set_value("Weekly Update").run()
    food = next(widget for widget in app.number_input if widget.label == "Food spent")
    food.set_value(48.25)
    next(button for button in app.button if button.label == "Save weekly spending").click().run()
    assert not app.exception
    assert any("Saved" in message.value for message in app.success)

    fresh = AppTest.from_file(str(app_path), default_timeout=30).run()
    for page in ["Weekly Update", "Budgets", "Insights", "Dashboard"]:
        fresh.sidebar.radio[0].set_value(page).run()
        assert not fresh.exception
    assert float(db.get_expenses()["amount"].sum()) == 48.25
    assert any("Local storage" in caption.value for caption in fresh.sidebar.caption)


def test_invalid_github_configuration_displays_safe_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDGET_TRACKER_GITHUB_TOKEN", "do-not-expose")
    monkeypatch.setenv("BUDGET_TRACKER_GITHUB_REPO", "invalid repo name")
    monkeypatch.setenv("BUDGET_TRACKER_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
    assert not app.exception
    assert app.error
    assert "do-not-expose" not in app.error[0].value
    assert not app.sidebar.radio
