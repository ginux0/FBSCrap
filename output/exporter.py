"""Data exporter — JSON, CSV, and URL-list outputs."""
from __future__ import annotations
import csv, json
from pathlib import Path


class Exporter:

    def __init__(self, out_dir: Path | str):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def to_json(self, data: list[dict], filename: str = "posts.json") -> Path:
        out = self.out / filename
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        print(f"  [EXPORT] JSON  → {out}  ({len(data)} records)")
        return out

    def to_csv(self, data: list[dict], filename: str = "posts.csv") -> Path:
        if not data:
            return self.out / filename
        out   = self.out / filename
        flat  = [self._flatten(r) for r in data]
        fields = list(flat[0].keys())

        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(flat)

        print(f"  [EXPORT] CSV   → {out}  ({len(flat)} rows)")
        return out

    def to_urls(self, data: list[dict], filename: str = "urls.txt") -> Path:
        """Plain text file with one Facebook URL per line — for quick manual review."""
        out   = self.out / filename
        lines = [p["url"] for p in data if p.get("url")]
        out.write_text("\n".join(lines) + "\n")
        print(f"  [EXPORT] URLs  → {out}  ({len(lines)} links)")
        return out

    @staticmethod
    def _flatten(row: dict) -> dict:
        r    = dict(row)
        sent = r.pop("sentiment", {}) or {}
        r["sentiment_label"]    = sent.get("label", "")
        r["sentiment_neg"]      = sent.get("negative_score", "")
        r["sentiment_pos"]      = sent.get("positive_score", "")
        r["sentiment_net"]      = sent.get("net_score", "")
        r["sentiment_triggers"] = "|".join(sent.get("top_triggers", []))
        r.pop("comments", None)  # nested list — stays in JSON only
        return r
