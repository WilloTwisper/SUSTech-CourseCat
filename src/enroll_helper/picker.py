from __future__ import annotations

from pathlib import Path

from .tui import HAS_PTK, print_note
from .tis.models import Course

CMDS = ("l", "ls", "list", "d", "del", "delete", "q", "quit", "exit", "w",
        "write", "r", "refresh")
HELP = ("指令: 序号(如 1 3 2)=加入队列 | 关键字=搜索 | r=刷新当前列表余量 | "
        "d N=移除第N项 | l=查看队列 | q=保存退出")


def filter_catalog(catalog: dict[str, Course], kw: str = "",
                   type_code: str | None = None) -> list[Course]:
    hits = [c for n, c in catalog.items()
            if (not kw or kw in n) and (type_code is None or c.type_code == type_code)]
    return sorted(hits, key=lambda c: c.name)


def render_rows(rows: list[Course], start: int = 1) -> str:
    lines = []
    for i, c in enumerate(rows, start):
        lines.append(f"  {i:>3}. [{c.type_name or c.type_code}] {c.name}  {c.seats_text()}")
    return "\n".join(lines)


def parse_command(line: str) -> tuple[str, list[int]]:
    toks = line.split()
    if not toks:
        return ("noop", [])
    head = toks[0].lower()
    if head in ("l", "ls", "list"):
        return ("list", [])
    if head in ("q", "quit", "exit", "w", "write"):
        return ("save", [])
    if head in ("d", "del", "delete"):
        nums = []
        for t in toks[1:]:
            try:
                nums.append(int(t))
            except ValueError:
                pass
        return ("delete", nums)
    if head in ("r", "refresh"):
        return ("refresh", [])
    try:
        return ("add", [int(t) for t in toks])
    except ValueError:
        return ("noop", [])


def write_queue(path: str, queue: list[Course]) -> None:
    lines = ["# 每行一门，按优先级排序（由 enroll-helper pick 生成）"]
    lines += [c.name for c in queue]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _process(line: str, queue: list[Course], state: dict,
             catalog: dict[str, Course], print_fn) -> str:
    """Shared handler. Returns 'continue' or 'break'."""
    line = line.strip()
    if not line:
        return "continue"
    cmd, nums = parse_command(line)
    if cmd == "save":
        return "break"
    if cmd == "list":
        print_fn("当前队列:")
        print_fn(render_rows(queue) if queue else "  （空）")
        return "continue"
    if cmd == "delete":
        for n in sorted(nums, reverse=True):
            if 1 <= n <= len(queue):
                removed = queue.pop(n - 1)
                print_fn(f"  已移除 {removed.name}")
        return "continue"
    if cmd == "refresh":
        refresher = state.get("refresh")
        if refresher is None:
            print_fn("  余量刷新不可用（本次缺少会话）")
            return "continue"
        print_fn("  刷新余量中…（每类一次查询，带限频保护）")
        try:
            state["rows"] = list(refresher(state["rows"]))
        except Exception as e:
            print_fn(f"  刷新失败: {type(e).__name__}: {e}")
            return "continue"
        rows = state["rows"]
        print_fn(render_rows(rows) if rows else "  （无）")
        return "continue"
    if cmd == "add":
        rows = state["rows"]
        for n in nums:
            if 1 <= n <= len(rows):
                c = rows[n - 1]
                if c in queue:
                    print_fn(f"  已在队列: {c.name}")
                else:
                    queue.append(c)
                    print_fn(f"  + {c.name} {c.seats_text()}")
        return "continue"
    if line in catalog:
        c = catalog[line]
        if c in queue:
            print_fn(f"  已在队列: {c.name}")
        else:
            queue.append(c)
            print_fn(f"  + {c.name} {c.seats_text()}")
        return "continue"
    rows = filter_catalog(catalog, line)
    state["rows"] = rows
    show = rows[:20]
    print_fn(f"匹配 {len(rows)} 门" + ("（显示前20）" if len(rows) > 20 else "") + ":")
    print_fn(render_rows(show) if show else "  （无）")
    return "continue"


def run_picker(catalog: dict[str, Course], path: str = "courses.txt",
               input_fn=input, print_fn=print, refresher=None) -> list[Course]:
    queue: list[Course] = []
    state = {"rows": filter_catalog(catalog, "")[:20], "refresh": refresher}
    if input_fn is not input or not HAS_PTK:
        return _run_legacy(catalog, path, queue, state, input_fn, print_fn)
    return _run_ptk(catalog, path, queue, state, print_fn)


def _run_legacy(catalog, path, queue, state, input_fn, print_fn) -> list[Course]:
    print_fn(f"共 {len(catalog)} 门课。{HELP}")
    print_fn(render_rows(state["rows"]))
    while True:
        try:
            line = input_fn("pick> ").strip()
        except (EOFError, KeyboardInterrupt):
            line = "q"
        if _process(line, queue, state, catalog, print_fn) == "break":
            break
    write_queue(path, queue)
    print_fn(f"[+] 已保存 {len(queue)} 门到 {path}")
    return queue


def _run_ptk(catalog, path, queue, state, print_fn) -> list[Course]:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML

    class CourseCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor.strip()
            if not text or text[0].isdigit():
                return
            head = text.split()[0].lower()
            if head in CMDS:
                return
            for c in filter_catalog(catalog, text)[:12]:
                yield Completion(c.name, start_position=-len(text),
                                 display_meta=f"{c.type_name} {c.seats_text()}")

    def toolbar():
        preview = "、".join(c.name for c in queue[:5])
        more = f" 等{len(queue)}门" if len(queue) > 5 else ""
        return HTML(f" <b>队列 {len(queue)}</b>: {preview}{more}"
                    f" | 输关键字出候选→Enter加入 | q 保存退出")

    session = PromptSession(message="pick> ", completer=CourseCompleter(),
                            complete_while_typing=True, bottom_toolbar=toolbar)
    print_fn(f"共 {len(catalog)} 门课。边打字边出候选（方向键选择），{HELP}")
    while True:
        try:
            line = session.prompt()
        except KeyboardInterrupt:
            if queue:
                print_note("Ctrl+C：保存当前队列并退出（再按一次放弃）")
                break
            print_note("队列为空，继续选或 q 退出")
            continue
        except EOFError:
            break
        if _process(line, queue, state, catalog, print_fn) == "break":
            break
    if queue:
        write_queue(path, queue)
        print_fn(f"[+] 已保存 {len(queue)} 门到 {path}")
    return queue
