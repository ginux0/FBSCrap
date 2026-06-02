"""
SessionLogger — writes to both console (important events) and a timestamped log file.
Every page gets: start URL, scroll-by-scroll article counts, stop reason, elapsed time.
"""
from __future__ import annotations
import traceback
from datetime import datetime
from pathlib import Path


class SessionLogger:

    def __init__(self, log_dir: Path, verbose: bool = False):
        self.verbose  = verbose
        log_dir.mkdir(parents=True, exist_ok=True)
        ts            = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = log_dir / f"fbscrap_{ts}.log"
        self._fh      = open(self.log_path, "w", encoding="utf-8", buffering=1)
        self._write(f"{'='*72}\n")
        self._write(f"FBSCRAP SESSION LOG — {datetime.now().isoformat()}\n")
        self._write(f"{'='*72}\n\n")
        print(f"  [LOG] Writing session log → {self.log_path}")

    # ── Public API ────────────────────────────────────────────────────────────

    def info(self, msg: str) -> None:
        self._emit("INFO ", msg, console=True)

    def debug(self, msg: str) -> None:
        self._emit("DEBUG", msg, console=self.verbose)

    def warn(self, msg: str) -> None:
        self._emit("WARN ", msg, console=True)

    def error(self, msg: str, exc: BaseException | None = None) -> None:
        self._emit("ERROR", msg, console=True)
        if exc:
            tb = traceback.format_exc()
            self._write(f"  TRACEBACK:\n{tb}\n")

    # ── Page lifecycle ────────────────────────────────────────────────────────

    def page_start(self, name: str, url: str) -> datetime:
        self._emit("PAGE↓", f"START  {name:40s}  {url}", console=True)
        return datetime.now()

    def page_landed(self, name: str, final_url: str) -> None:
        self._emit("PAGE↓", f"LANDED {name:40s}  final_url={final_url}", console=self.verbose)

    def page_login_wall(self, name: str) -> None:
        self._emit("WALL ", f"LOGIN WALL detected for [{name}] — skipping", console=True)

    def page_scroll(self, scroll_n: int, total_arts: int, new_arts: int, posts: int) -> None:
        msg = (f"scroll={scroll_n:02d}  articles={total_arts:3d}(+{new_arts:2d})"
               f"  posts_kept={posts:3d}")
        self._emit("SCRLL", msg, console=self.verbose)

    def page_stale(self, name: str, stale_n: int, max_stale: int) -> None:
        self._emit("STALE", f"[{name}] stale={stale_n}/{max_stale}", console=self.verbose)

    def page_stop(self, name: str, reason: str) -> None:
        self._emit("STOP ", f"[{name}] reason={reason}", console=self.verbose)

    def page_end(self, name: str, t_start: datetime, raw: int, kept: int, reason: str) -> None:
        elapsed = (datetime.now() - t_start).total_seconds()
        status  = "OK" if kept > 0 else "EMPTY"
        self._emit(
            "PAGE✓",
            f"END    {name:40s}  raw={raw:3d}  kept={kept:3d}  "
            f"reason={reason:<18s}  elapsed={elapsed:5.1f}s  [{status}]",
            console=True,
        )

    # ── Search lifecycle ──────────────────────────────────────────────────────

    def search_start(self, query: str, url: str) -> datetime:
        self._emit("SRCH↓", f"START  query={query!r}  {url}", console=True)
        return datetime.now()

    def search_filter(self, applied: bool) -> None:
        status = "applied" if applied else "FAILED — will get mixed results"
        self._emit("SRCH↓", f"Recent filter: {status}", console=True)

    def search_end(self, query: str, t_start: datetime, raw: int, kept: int, reason: str) -> None:
        elapsed = (datetime.now() - t_start).total_seconds()
        self._emit(
            "SRCH✓",
            f"END    query={query!r}  raw={raw:3d}  kept={kept:3d}  "
            f"reason={reason:<18s}  elapsed={elapsed:5.1f}s",
            console=True,
        )

    # ── Generic exception capture ─────────────────────────────────────────────

    def exception(self, context: str) -> None:
        tb = traceback.format_exc()
        self._emit("EXCPT", f"in [{context}]:\n{tb}", console=True)

    # ── Session summary ───────────────────────────────────────────────────────

    def summary(self, total: int, deduped: int, neg: int) -> None:
        self._write("\n" + "="*72 + "\n")
        self._emit("SUMM ", f"total={total}  deduped={deduped}  NEGATIVO={neg}", console=True)
        self._write(f"Session ended: {datetime.now().isoformat()}\n")

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit(self, tag: str, msg: str, console: bool = False) -> None:
        ts   = datetime.now().strftime("%H:%M:%S.%f")[:12]
        line = f"{ts}  [{tag}]  {msg}"
        self._write(line + "\n")
        if console:
            # Indent multi-line messages
            lines = msg.splitlines()
            print(f"  {ts}  [{tag}]  {lines[0]}")
            for extra in lines[1:]:
                print(f"             {extra}")

    def _write(self, text: str) -> None:
        try:
            self._fh.write(text)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
