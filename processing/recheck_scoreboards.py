"""Targeted, read-only scoreboard retries; never resets or imports archive data."""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from .catalog import image_hash
from .extraction import BASE_HEIGHT, BASE_WIDTH, ScreenshotExtractor
from .pipeline import parse_sequences, select_sources
from .store import Store, write_json

SCORE_FIELDS = (
    "home_goals",
    "away_goals",
    "home_penalties",
    "away_penalties",
    "duration_minutes",
    "extra_time",
)
REGIONS = {
    "home_goals": (597, 103, 644, 157),
    "away_goals": (725, 103, 774, 157),
    "clock": (619, 74, 753, 110),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--screenshots", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--vision",
        action="store_true",
        help="Also use macOS Apple Vision on padded crops",
    )
    args = parser.parse_args(argv)
    store = Store.load(args.root / "processing/data/diagnostics.json")
    extractor = ScreenshotExtractor()
    results = []
    prepared = []
    with tempfile.TemporaryDirectory(prefix="career-scoreboards-") as temporary:
        for source in select_sources(store, parse_sequences(args.screenshots)):
            path = args.root / source["path"]
            if (
                source["screen_type"] != "match_facts"
                or image_hash(path) != source["sha256"]
            ):
                raise ValueError(f"Not an unchanged match summary: {path}")
            with Image.open(path) as original:
                image = original.convert("RGB")
            record, evidence = extractor.extract_match(image)
            previous = json.loads(
                store.get("extractions", source["id"])["candidate_json"]
            )[0]
            row = {
                "path": source["path"],
                "sha256": source["sha256"],
                "fixture": {
                    key: record.get(key)
                    for key in ("played_on", "home_club", "away_club")
                },
                "saved": {key: previous.get(key) for key in SCORE_FIELDS},
                "fresh": {key: record.get(key) for key in SCORE_FIELDS},
                "evidence": {key: evidence[key] for key in REGIONS},
                "vision": {},
            }
            results.append(row)
            if args.vision:
                for field, bounds in REGIONS.items():
                    scaled = tuple(
                        round(
                            value
                            * (
                                image.width / BASE_WIDTH
                                if index % 2 == 0
                                else image.height / BASE_HEIGHT
                            )
                        )
                        for index, value in enumerate(bounds)
                    )
                    crop = ImageOps.autocontrast(image.crop(scaled).convert("L"))
                    if ImageStat.Stat(crop).mean[0] < 128:
                        crop = ImageOps.invert(crop)
                    # A lone narrow digit is often ignored by Vision. Give it
                    # whitespace and repeated context; retain both reads.
                    for copies in (1, 3):
                        enlarged = crop.resize((crop.width * 3, crop.height * 3))
                        strip = Image.new(
                            "L",
                            ((enlarged.width + 32) * copies + 32, enlarged.height + 64),
                            255,
                        )
                        for index in range(copies):
                            strip.paste(
                                enlarged, (32 + index * (enlarged.width + 32), 32)
                            )
                        target = (
                            Path(temporary)
                            / f"{source['sequence']}-{field}-{copies}.png"
                        )
                        strip.save(target)
                        prepared.append((str(target), row, field, copies))
            print(source["path"], row["fresh"], flush=True)
        if prepared:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(json.dumps([path for path, *_ in prepared]))
            completed = subprocess.run(
                [
                    "swift",
                    str(Path(__file__).with_name("scoreboard_vision.swift")),
                    str(manifest),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=240,
            )
            readings = {
                row["path"]: row
                for row in map(json.loads, completed.stdout.splitlines())
            }
            for path, row, field, copies in prepared:
                reading = readings[path]
                compact = re.sub(
                    r"\s+", "", "".join(token["text"] for token in reading["tokens"])
                )
                row["vision"].setdefault(field, []).append(
                    {
                        "copies": copies,
                        "tokens": reading["tokens"],
                        "error": reading.get("error"),
                        "agrees": None
                        if field == "clock"
                        else bool(compact)
                        and compact == str(row["fresh"][field]) * copies,
                    }
                )
        report = {
            "method": "Fresh RapidOCR plus optional padded Apple Vision crops; not manual visual verification",
            "screenshots": results,
        }
        write_json(args.output, report)
        print(f"Saved read-only report: {args.output}")
        for row in results:
            print(
                row["path"], json.dumps(row["vision"], ensure_ascii=False), flush=True
            )


if __name__ == "__main__":
    main()
