"""
fetch_worldcup.py
==================
מושך נתונים עדכניים על מונדיאל 2026 (טבלאות בתים, משחקים לפי שלב,
מלכי שערים, ורשימת כל השחקנים) ובונה מחדש את mundial2026.html.

הרצה:
    python fetch_worldcup.py

לפני ההרצה הראשונה:
    1. pip install requests   (פעם אחת בלבד, אם requests לא מותקן)
    2. הרשמה חינמית לשני מקורות הנתונים וקבלת מפתח מכל אחד:
       - football-data.org : https://www.football-data.org/client/register
       - api-sports.io      : https://dashboard.api-football.com/register
    3. הדבקת שני המפתחות למטה, במקום PUT_..._KEY_HERE
    4. לוודא ש-template.html נמצא באותה תיקייה כמו הסקריפט הזה

הערה חשובה על api-sports.io:
    התוכנית החינמית שלהם מוגבלת בעונות מסוימות (הם כותבים את זה מפורשות
    בתיעוד: "Free plans are limited in terms of available seasons").
    אם season=2026 מחזיר רשימות ריקות בזמן ש-2022 עובד, כנראה שזו מגבלת
    תוכנית ולא באג בקוד. אפשר לבדוק בדשבורד שלך תחת "Seasons"/"Plan" אילו
    עונות כלולות, או להסתכל בשדה "errors" בתשובת ה-JSON הגולמית.

הרצה אוטומטית (GitHub Actions):
    כשהסקריפט הזה רץ בתוך GitHub Actions (ר' .github/workflows/update.yml),
    המפתחות והגדרות מסוימות מגיעים ממשתני סביבה (Secrets) ולא מהקבועים
    למטה - כדי שלא יהיה צורך לשמור מפתחות בתוך הקוד שעולה ל-GitHub.
    כשמריצים רגיל על המחשב האישי (כולל דרך ה-exe), פשוט משתמשים בקבועים
    הרגילים למטה, בדיוק כמו קודם.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
import requests


# ---------------------------------------------------------------------------
# הגדרות
# ---------------------------------------------------------------------------
# כל הגדרה כאן ניתנת לדריסה ממשתנה סביבה (למשל בתוך GitHub Actions) - אם
# משתנה הסביבה לא קיים, נופלים חזרה לערך הקבוע הרגיל. כך אותו קובץ בדיוק
# עובד גם על המחשב האישי (עם המפתחות הקבועים למטה) וגם בהרצה אוטומטית
# מרוחקת (עם מפתחות ש"מוזרקים" כ-Secrets, בלי שהם כתובים בקוד בכלל).
API_KEYS = {
    "football_data": os.environ.get("FOOTBALL_DATA_KEY", "PUT_YOUR_FOOTBALL_DATA_KEY_HERE"),
    "api_sports":    os.environ.get("API_SPORTS_KEY", "PUT_YOUR_API_SPORTS_KEY_HERE"),
}

# --- מקור 1: football-data.org - טבלאות בתים ומשחקים -----------------------
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
COMPETITION_CODE = "WC"          # הקוד של המונדיאל אצל football-data.org

# --- מקור 2: api-sports.io - שחקנים, מלכי שערים -----------------------------
API_SPORTS_BASE = "https://v3.football.api-sports.io"
WORLDCUP_LEAGUE_ID = 1           # מזהה קבוע של המונדיאל אצל api-sports.io
SEASON = 2026

# האם למשוך את הסגלים המלאים של כל 48 הנבחרות (בנוסף למלכי השערים)?
# זו הרחבה שדורשת ~49 קריאות API נוספות (1 לרשימת קבוצות + 48 לסגלים),
# בתוך המכסה החינמית של 100 ליום - אבל שווה לשים לב אם מריצים כמה
# פעמים באותו יום. אפשר לכבות זמנית ע"י שינוי ל-False.
# בהרצה אוטומטית (GitHub Actions) זה נשלט ע"י משתנה הסביבה FETCH_ALL_PLAYERS,
# כדי שריצות התזמון האוטומטיות התכופות לא "יבזבזו" את המכסה על סגלים
# שכמעט ואינם משתנים, ורק הרצה ידנית תמשוך אותם מחדש כשבאמת רוצים.
FETCH_ALL_PLAYERS = os.environ.get("FETCH_ALL_PLAYERS", "false").lower() == "true"
REQUEST_DELAY_SECONDS = 0.7  # הפסקה קטנה בין קריאות כדי לא לפגוע במגבלת קצב

TEMPLATE_FILE = "template.html"
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "mundial2026.html")

FOOTBALL_DATA_HEADERS = {"X-Auth-Token": API_KEYS["football_data"]}
API_SPORTS_HEADERS = {"x-apisports-key": API_KEYS["api_sports"]}

STAGE_LABELS = {
    "GROUP_STAGE": "שלב הבתים",
    "LAST_32": "שלב ה-32",
    "LAST_16": "שמינית גמר",
    "QUARTER_FINALS": "רבע גמר",
    "SEMI_FINALS": "חצי גמר",
    "THIRD_PLACE": "משחק על מקום שלישי",
    "FINAL": "גמר",
}


# ---------------------------------------------------------------------------
# מקור 1: football-data.org
# ---------------------------------------------------------------------------
def fetch_standings():
    """מושך את טבלאות הבתים ומחזיר רשימת מילונים בפורמט שהעמוד מצפה לו."""
    url = f"{FOOTBALL_DATA_BASE}/competitions/{COMPETITION_CODE}/standings"
    resp = requests.get(url, headers=FOOTBALL_DATA_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for group_table in data.get("standings", []):
        # מטפל בכל צורת כתיבה אפשרית: "GROUP_A" / "Group_A" / "Group A" -> "A"
        group_name = group_table["group"].replace("_", " ").strip().split(" ")[-1]
        for entry in group_table["table"]:
            rows.append({
                "rank": entry["position"],
                "team": entry["team"]["name"],
                "w": entry["won"],
                "d": entry["draw"],
                "l": entry["lost"],
                "pts": entry["points"],
                "group": group_name,
            })
    return rows


def fetch_matches():
    """מושך משחקים (עבר + עתיד), כולל שלב הטורניר של כל משחק."""
    url = f"{FOOTBALL_DATA_BASE}/competitions/{COMPETITION_CODE}/matches"
    resp = requests.get(url, headers=FOOTBALL_DATA_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    status_map = {
        "IN_PLAY": "in_progress",
        "PAUSED": "in_progress",
        "FINISHED": "final",
        "SCHEDULED": "scheduled",
        "TIMED": "scheduled",
        "POSTPONED": "scheduled",
    }

    games = []
    for m in data.get("matches", []):
        status = status_map.get(m["status"], "scheduled")
        raw_stage = m.get("stage", "GROUP_STAGE")
        game = {
            "status": status,
            "home": m["homeTeam"]["name"] or m["homeTeam"].get("shortName", "?"),
            "away": m["awayTeam"]["name"] or m["awayTeam"].get("shortName", "?"),
            "local": m["utcDate"],
            "stage": raw_stage,
            "stageLabel": STAGE_LABELS.get(raw_stage, raw_stage),
        }
        if status in ("final", "in_progress"):
            full_time = m.get("score", {}).get("fullTime", {})
            game["hs"] = full_time.get("home") or 0
            game["as"] = full_time.get("away") or 0
        games.append(game)
    return games


# ---------------------------------------------------------------------------
# מקור 2: api-sports.io
# ---------------------------------------------------------------------------
def fetch_top_scorers():
    """
    מושך את טבלת מלכי השערים - עד 20 שחקנים, עם עמדה וגיל (מגיעים
    ישירות מהתשובה, בלי קריאות נוספות).
    """
    url = f"{API_SPORTS_BASE}/players/topscorers"
    params = {"league": WORLDCUP_LEAGUE_ID, "season": SEASON}
    resp = requests.get(url, headers=API_SPORTS_HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("errors"):
        print(f"  שים לב - ה-API החזיר שגיאה: {data['errors']}")

    scorers = []
    for i, item in enumerate(data.get("response", []), start=1):
        player = item.get("player", {})
        stats_list = item.get("statistics") or [{}]
        stats = stats_list[0]

        goals = stats.get("goals", {}) or {}
        games_stats = stats.get("games", {}) or {}
        cards = stats.get("cards", {}) or {}
        team = stats.get("team", {}) or {}

        scorers.append({
            "rank": i,
            "name": player.get("name"),
            "nationality": player.get("nationality"),
            "team": team.get("name"),
            "position": games_stats.get("position"),
            "age": player.get("age"),
            "photo": player.get("photo"),
            "goals": goals.get("total") or 0,
            "assists": goals.get("assists") or 0,
            "appearances": games_stats.get("appearences") or 0,
            "minutes": games_stats.get("minutes") or 0,
            "yellow": cards.get("yellow") or 0,
            "red": cards.get("red") or 0,
        })
    return scorers


def fetch_worldcup_team_ids():
    """מושך את רשימת 48 הנבחרות עם מזהה ה-team ID שלהן אצל api-sports.io."""
    url = f"{API_SPORTS_BASE}/teams"
    params = {"league": WORLDCUP_LEAGUE_ID, "season": SEASON}
    resp = requests.get(url, headers=API_SPORTS_HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("errors"):
        print(f"  שים לב - ה-API החזיר שגיאה: {data['errors']}")

    id_map = {}
    for item in data.get("response", []):
        team = item.get("team", {})
        if team.get("id") and team.get("name"):
            id_map[team["name"]] = team["id"]
    return id_map


def fetch_all_players(team_ids):
    """
    מושך את הסגל המלא (שם, גיל, עמדה, מספר, תמונה) של כל נבחרת, לפי
    מזהי הקבוצות שקיבלנו מ-fetch_worldcup_team_ids. קריאה אחת לכל
    נבחרת - בלי סטטיסטיקות (רק פרטי סגל), כדי לחסוך במכסה.
    """
    all_players = []
    url = f"{API_SPORTS_BASE}/players/squads"

    for team_name, team_id in team_ids.items():
        try:
            resp = requests.get(url, headers=API_SPORTS_HEADERS,
                                 params={"team": team_id}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            squads = data.get("response", [])
            if squads:
                for p in squads[0].get("players", []):
                    all_players.append({
                        "name": p.get("name"),
                        "team": team_name,
                        "position": p.get("position"),
                        "age": p.get("age"),
                        "number": p.get("number"),
                        "photo": p.get("photo"),
                    })
        except requests.RequestException as e:
            print(f"  לא ניתן היה למשוך את הסגל של {team_name}: {e}")

        time.sleep(REQUEST_DELAY_SECONDS)

    return all_players


# ---------------------------------------------------------------------------
# בניית הקובץ הסופי
# ---------------------------------------------------------------------------
def build_html(standings, games, scorers, all_players):
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    # שעון ישראל, כולל מעבר קיץ/חורף אוטומטי. ב-Windows ייתכן שחסר מאגר
    # אזורי הזמן (tzdata) - במקרה כזה נופלים בחזרה לקירוב קבוע של UTC+3.
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Jerusalem"))
        tz_label = "שעון ישראל"
    except Exception:
        now = datetime.now(timezone.utc) + timedelta(hours=3)
        tz_label = "קירוב לשעון ישראל, UTC+3"
    updated_str = f"{now.strftime('%d.%m.%Y %H:%M')} ({tz_label})"

    replacements = {
        "/*__STANDINGS__*/[]/*__STANDINGS__*/": json.dumps(standings, ensure_ascii=False),
        "/*__GAMES__*/[]/*__GAMES__*/": json.dumps(games, ensure_ascii=False),
        "/*__SCORERS__*/[]/*__SCORERS__*/": json.dumps(scorers, ensure_ascii=False),
        "/*__ALLPLAYERS__*/[]/*__ALLPLAYERS__*/": json.dumps(all_players, ensure_ascii=False),
        "/*__SEASON__*/2026/*__SEASON__*/": json.dumps(SEASON),
        "/*__UPDATED__*/\"\"/*__UPDATED__*/": json.dumps(updated_str),
    }
    html = template
    for marker, value in replacements.items():
        html = html.replace(marker, value)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# הרצה
# ---------------------------------------------------------------------------
def main():
    missing = [name for name, key in API_KEYS.items() if key.startswith("PUT_")]
    if missing:
        sys.exit(
            "צריך קודם להדביק מפתחות API אמיתיים בתוך הקובץ (באובייקט API_KEYS).\n"
            f"חסר עדיין: {', '.join(missing)}\n"
            "football-data.org: https://www.football-data.org/client/register\n"
            "api-sports.io:     https://dashboard.api-football.com/register"
        )

    if not os.path.isfile(TEMPLATE_FILE):
        sys.exit(
            f"לא נמצא הקובץ '{TEMPLATE_FILE}' בתיקייה הנוכחית.\n"
            "ודא ש-template.html נמצא באותה תיקייה בדיוק כמו קובץ ה-exe/py הזה."
        )

    print("מושך טבלאות בתים...")
    standings = fetch_standings()
    print(f"  נמצאו {len(standings)} שורות.")

    print("מושך משחקים...")
    games = fetch_matches()
    print(f"  נמצאו {len(games)} משחקים.")

    print("מושך מלכי שערים...")
    scorers = fetch_top_scorers()
    print(f"  נמצאו {len(scorers)} שחקנים.")
    if not scorers:
        print("  (ריק - כנראה מגבלת עונה בתוכנית החינמית של api-sports.io, ראה הערה בראש הקובץ)")

    all_players = []
    if FETCH_ALL_PLAYERS:
        print("מושך רשימת נבחרות (לצורך שליפת סגלים)...")
        team_ids = fetch_worldcup_team_ids()
        print(f"  נמצאו {len(team_ids)} נבחרות.")
        if team_ids:
            print(f"מושך סגלים מלאים ({len(team_ids)} קריאות, זה ייקח כדקה)...")
            all_players = fetch_all_players(team_ids)
            print(f"  נמצאו {len(all_players)} שחקנים בסך הכול.")

    print("בונה קובץ HTML...")
    build_html(standings, games, scorers, all_players)
    print(f"מוכן! פתח את {OUTPUT_FILE} בדפדפן, או גרור אותו ל-Netlify Drop.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code:
            print(e.code)
    except Exception as e:
        print(f"\nשגיאה בלתי צפויה: {e}")
    finally:
        # שורה זו חשובה בעיקר כשמריצים בלחיצה כפולה (למשל את קובץ ה-exe) -
        # בלעדיה החלון היה נפתח ונסגר מיד לפני שאפשר לקרוא את הפלט.
        # sys.stdin.isatty() בודק שיש מקלדת אמיתית מחוברת; ב-GitHub Actions
        # (וכל הרצה אוטומטית אחרת) אין קלט בכלל, אז מדלגים על זה כדי לא לקרוס.
        if sys.stdin.isatty():
            input("\nלחץ Enter כדי לסגור את החלון...")
