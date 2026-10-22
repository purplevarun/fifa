import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .store import Store


def font(size):
    for name in ("/System/Library/Fonts/Menlo.ttc", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def crop_region(image, bounds):
    return image.crop(
        (
            round(bounds[0] * image.width / 1366),
            round(bounds[1] * image.height / 768),
            round(bounds[2] * image.width / 1366),
            round(bounds[3] * image.height / 768),
        )
    )


def make_squad_sheets(rows, root, output):
    results = []
    for offset in range(0, len(rows), 6):
        page = rows[offset : offset + 6]
        sheet = Image.new("RGB", (1120, 590 * ((len(page) + 1) // 2)), "#ececec")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(page):
            left, top = (index % 2) * 560, (index // 2) * 590
            draw.text(
                (left + 10, top + 5),
                f"Screenshot {row['sequence']}",
                fill="black",
                font=font(19),
            )
            with Image.open(root / row["path"]) as image:
                region = crop_region(image.convert("RGB"), (695, 236, 1045, 602))
                sheet.paste(region.resize((525, 549)), (left + 10, top + 30))
        destination = (
            output / f"squads-{page[0]['sequence']}-{page[-1]['sequence']}.png"
        )
        sheet.save(destination)
        results.append(str(destination))
    return results


def make_sheets(connection, root, output, mode="matches", start=0, end=99999):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    screen_types = (
        {"match_facts"}
        if mode in {"matches", "teams"}
        else {"player_performance", "goalkeeper_performance"}
    )
    if mode == "squads":
        screen_types = {"squad"}
    rows = []
    for path in connection.rows("source_paths", present=True):
        if path["sequence"] is None or not start <= path["sequence"] <= end:
            continue
        source = connection.get("source_images", path["source_id"])
        extraction = connection.get("extractions", path["source_id"])
        if extraction and source["screen_type"] in screen_types:
            rows.append({**source, **path, **extraction})
    rows.sort(key=lambda row: (row["sequence"], row["path"]))
    if mode == "squads":
        return make_squad_sheets(rows, root, output)
    if mode == "teams":
        distinct = []
        seen_matches = set()
        for row in rows:
            fixture = connection.find("match_sources", source_id=row["id"])
            if fixture and fixture["match_id"] not in seen_matches:
                seen_matches.add(fixture["match_id"])
                distinct.append(row)
        rows = distinct
    page_size = 8 if mode in {"matches", "teams"} else 20
    width, row_height = (
        (1100, 180)
        if mode == "matches"
        else ((1200, 350) if mode == "teams" else (1400, 112))
    )
    results = []
    for offset in range(0, len(rows), page_size):
        page_rows = rows[offset : offset + page_size]
        sheet = Image.new("RGB", (width, row_height * len(page_rows)), "#ececec")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(page_rows):
            top = index * row_height
            with Image.open(root / row["path"]) as original:
                image = original.convert("RGB")
            candidate = json.loads(row["candidate_json"])
            candidate = candidate[0] if candidate else {}
            draw.text((8, top + 4), str(row["sequence"]), fill="black", font=font(18))
            if mode == "matches":
                header = crop_region(image, (250, 42, 1140, 163))
                sheet.paste(header, (90, top))
                summary = {
                    key: candidate.get(key)
                    for key in (
                        "played_on",
                        "home_club",
                        "home_goals",
                        "away_goals",
                        "away_club",
                        "competition",
                    )
                }
                draw.text(
                    (8, top + 128),
                    json.dumps(summary, ensure_ascii=True),
                    fill="black",
                    font=font(12),
                )
            elif mode == "teams":
                sheet.paste(crop_region(image, (718, 275, 1250, 598)), (70, top + 20))
                draw.text(
                    (615, top + 10),
                    f"{candidate.get('played_on')}  {candidate.get('competition')}",
                    fill="black",
                    font=font(15),
                )
                stats = candidate.get("team_stats", {})
                draw.text((850, top + 45), "home    away", fill="black", font=font(15))
                for field_index, field in enumerate(
                    (
                        "shots",
                        "shots_on_target",
                        "possession_pct",
                        "tackles",
                        "fouls",
                        "corners",
                        "shot_accuracy_pct",
                        "pass_accuracy_pct",
                    )
                ):
                    home = stats.get("home", {}).get(field)
                    away = stats.get("away", {}).get(field)
                    draw.text(
                        (615, top + 75 + field_index * 31),
                        field,
                        fill="black",
                        font=font(14),
                    )
                    draw.text(
                        (850, top + 75 + field_index * 31),
                        f"{str(home):>5}   {str(away):>5}",
                        fill="black",
                        font=font(15),
                    )
            else:
                draw.text(
                    (70, top + 2), row["screen_type"], fill="black", font=font(12)
                )
                sheet.paste(crop_region(image, (175, 139, 405, 230)), (75, top + 18))
                sheet.paste(crop_region(image, (745, 179, 855, 232)), (325, top + 20))
                goalkeeper = row["screen_type"] == "goalkeeper_performance"
                regions = [
                    (
                        "GA" if goalkeeper else "G",
                        (627, 323, 662, 344) if goalkeeper else (627, 348, 662, 370),
                    ),
                    (
                        "A",
                        (1158, 314, 1193, 336) if goalkeeper else (627, 425, 662, 447),
                    ),
                    (
                        "caught/parried" if goalkeeper else "on/off",
                        (562, 347, 662, 370) if goalkeeper else (562, 373, 662, 397),
                    ),
                    ("position", (191, 251, 325, 280)),
                    ("club", (544, 140, 726, 174)),
                ]
                left = 450
                for label, bounds in regions:
                    draw.text((left, top + 4), label, fill="black", font=font(12))
                    region = crop_region(image, bounds)
                    sheet.paste(region, (left, top + 25))
                    left += max(region.width + 20, 65)
                review = {
                    key: candidate.get(key)
                    for key in (
                        "player",
                        "overall",
                        "rating",
                        "goals_conceded" if goalkeeper else "goals",
                        "assists",
                    )
                }
                draw.text(
                    (440, top + 65),
                    json.dumps(review, ensure_ascii=True),
                    fill="black",
                    font=font(12),
                )
            draw.line(
                (0, top + row_height - 1, width, top + row_height - 1), fill="#888888"
            )
        destination = (
            output
            / f"{mode}-{page_rows[0]['sequence']}-{page_rows[-1]['sequence']}.png"
        )
        sheet.save(destination)
        results.append(str(destination))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Render original image regions for batch visual review."
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--mode", choices=("matches", "players", "teams", "squads"), default="matches"
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=99999)
    arguments = parser.parse_args()
    data_directory = arguments.root / "processing" / "data"
    store = Store.load(data_directory / "diagnostics.json")
    for result in make_sheets(
        store,
        arguments.root,
        arguments.output or data_directory / "review" / "sheets",
        arguments.mode,
        arguments.start,
        arguments.end,
    ):
        print(result)


if __name__ == "__main__":
    main()
