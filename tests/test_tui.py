from enroll_helper.cli import apply_cli_overrides, load_settings, make_args
from enroll_helper.tui_app import move_item


def test_make_args_pipeline():
    args = make_args(interval_ms=500)
    s = apply_cli_overrides(load_settings(None, args), args)
    assert s.interval_ms == 500
    assert s.non_interactive is True
    assert s.courses_file == "courses.txt"
    assert s.submit_target == "rwtjzyx"


def test_make_args_overrides():
    args = make_args(retry_full=True, cascade=True, submit_target="rwtjzgwc",
                     at_time="10:00", use_ntp=True)
    s = apply_cli_overrides(load_settings(None, args), args)
    assert s.retry_full is True
    assert s.cascade_on_full is True
    assert s.submit_target == "rwtjzgwc"
    assert s.use_ntp is True


def test_move_item():
    items = ["a", "b", "c"]
    assert move_item(items, 1, -1) == 0
    assert items == ["b", "a", "c"]
    assert move_item(items, 0, -1) == 0
    assert items == ["b", "a", "c"]
    assert move_item(items, 2, 1) == 2
    assert move_item([], 0, 1) == 0


async def test_tui_mounts():
    from textual.widgets import Button, DataTable, Tabs

    from enroll_helper.tui_app import EnrollApp

    app = EnrollApp()
    async with app.run_test() as pilot:
        assert app.theme == "tis"
        app.action_toggle_mode()
        assert app.theme == "tis-dark"
        app.action_toggle_mode()
        assert app.theme == "tis"
        from enroll_helper.tui_app import TIS_THEME
        assert TIS_THEME.primary == "#8f000b"
        assert TIS_THEME.dark is False
        assert app.query_one("#queue-table", DataTable) is not None
        assert app.query_one("#mode-tabs", Tabs).active == "mode-now"
        assert app.query_one("#tis-topbar") is not None
        assert app.query_one("#tis-footer") is not None

async def test_search_modal_mouse(tmp_path, monkeypatch):
    from textual.widgets import ListView, RichLog

    from enroll_helper.tis.models import Course
    from enroll_helper.tui_app import CourseSearchScreen, EnrollApp

    monkeypatch.chdir(tmp_path)
    app = EnrollApp()
    app._catalog = {"高数": Course("i1", "高数", "bxxk", "通识必修", 100, 90)}
    async with app.run_test() as pilot:
        await pilot.click("#add-btn")
        await pilot.pause()
        assert isinstance(app.screen, CourseSearchScreen)
        lv = app.screen.query_one("#search-list", ListView)
        assert len(lv) == 1
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CourseSearchScreen)
        await pilot.click("#start-btn")
        await pilot.pause(0.6)
        texts = [s.text for s in app.query_one("#log", RichLog).lines]
        assert any("队列为空" in t for t in texts)


async def test_search_modal_category_filter(tmp_path, monkeypatch):
    from textual.widgets import ListView, Tab, Tabs

    from enroll_helper.tis.models import Course
    from enroll_helper.tui_app import CourseSearchScreen, EnrollApp

    monkeypatch.chdir(tmp_path)
    app = EnrollApp()
    app._catalog = {
        "高数": Course("i1", "高数", "bxxk", "通识必修", 100, 90),
        "大英": Course("i2", "大英", "xxxk", "通识选修", 50, 50),
    }
    async with app.run_test(size=(120, 32)) as pilot:
        await pilot.click("#add-btn")
        await pilot.pause(0.5)
        assert isinstance(app.screen, CourseSearchScreen)
        modal = app.screen
        assert len(modal.query_one("#search-list", ListView)) == 2
        btn = next(b for b in modal.query(Tab) if b.id == "cat-xxxk")
        await pilot.click(btn)
        await pilot.pause(0.5)
        assert modal._selected_code() == "xxxk"
        assert len(modal.query_one("#search-list", ListView)) == 1
        from textual.widgets._tabs import Underline

        bar_style = modal.query_one(Underline).get_component_rich_style(
            "underline--bar")
        assert bar_style.bgcolor is not None
        assert tuple(bar_style.bgcolor.triplet) == (45, 140, 240)


async def test_search_modal_click_adds(tmp_path, monkeypatch):
    from textual.widgets import ListView

    from enroll_helper.tis.models import Course
    from enroll_helper.tui_app import CourseSearchScreen, EnrollApp

    monkeypatch.chdir(tmp_path)
    app = EnrollApp()
    app._catalog = {
        "高数": Course("i1", "高数", "bxxk", "通识必修", 100, 90),
        "大英": Course("i2", "大英", "xxxk", "通识选修", 50, 50),
    }
    async with app.run_test(size=(120, 32)) as pilot:
        await pilot.click("#add-btn")
        await pilot.pause(0.5)
        assert isinstance(app.screen, CourseSearchScreen)
        lv = app.screen.query_one("#search-list", ListView)
        assert len(lv) == 2
        await pilot.click(lv.children[0])
        await pilot.pause(0.5)
        assert not isinstance(app.screen, CourseSearchScreen)
        assert [c.name for c in app._queue] == ["大英"]


async def test_search_modal_enter_adds(tmp_path, monkeypatch):
    from enroll_helper.tis.models import Course
    from enroll_helper.tui_app import CourseSearchScreen, EnrollApp

    monkeypatch.chdir(tmp_path)
    app = EnrollApp()
    app._catalog = {
        "高数": Course("i1", "高数", "bxxk", "通识必修", 100, 90),
        "大英": Course("i2", "大英", "xxxk", "通识选修", 50, 50),
    }
    async with app.run_test(size=(120, 32)) as pilot:
        await pilot.click("#add-btn")
        await pilot.pause(0.5)
        assert isinstance(app.screen, CourseSearchScreen)
        await pilot.press("down")
        await pilot.pause(0.3)
        assert isinstance(app.screen, CourseSearchScreen)
        assert app._queue == []
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert not isinstance(app.screen, CourseSearchScreen)
        assert [c.name for c in app._queue] == ["大英"]
