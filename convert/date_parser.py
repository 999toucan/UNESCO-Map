import re


LONG_AGO_YEAR = -50001
TIMELINE_MIN_YEAR = -50000
TIMELINE_MAX_YEAR = 2026

ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "twenty-first": 21,
}

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def era_from_text(text):
    upper = str(text).upper()
    return "BC" if "BCE" in upper or "BC" in upper else "AD"


def long_ago_date():
    return {
        "start_date": None,
        "end_date": None,
        "BC_AD": "LONG_AGO",
        "display": "A long time ago",
        "timeline_start": LONG_AGO_YEAR,
        "timeline_end": LONG_AGO_YEAR,
    }


def build_normalized_date(start_date, end_date, era, display):
    if start_date is None or end_date is None or era is None:
        return {
            "start_date": None,
            "end_date": None,
            "BC_AD": None,
            "display": None,
            "timeline_start": None,
            "timeline_end": None,
        }

    if era == "BC":
        timeline_start = -max(start_date, end_date)
        timeline_end = -min(start_date, end_date)
    elif era == "YA":
        years_ago = max(start_date, end_date)
        approx_year = TIMELINE_MAX_YEAR - years_ago
        if approx_year < TIMELINE_MIN_YEAR:
            return long_ago_date()
        timeline_start = approx_year
        timeline_end = approx_year
    else:
        timeline_start = min(start_date, end_date)
        timeline_end = max(start_date, end_date)

    if timeline_start < TIMELINE_MIN_YEAR:
        return long_ago_date()

    return {
        "start_date": start_date,
        "end_date": end_date,
        "BC_AD": era,
        "display": display,
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
    }


def format_display(start_date, end_date, era):
    if start_date == end_date:
        return f"{start_date} {era}"
    if era == "BC":
        return f"{max(start_date, end_date)}-{min(start_date, end_date)} {era}"
    return f"{min(start_date, end_date)}-{max(start_date, end_date)} {era}"


def century_years(century, era):
    if era == "BC":
        start = (century - 1) * 100
        end = century * 100
        return build_normalized_date(start, end, "BC", format_display(start, end, "BC"))

    start = (century - 1) * 100
    end = century * 100
    return build_normalized_date(start, end, "AD", format_display(start, end, "AD"))


def millennium_years(millennium, era):
    if era == "BC":
        start = (millennium - 1) * 1000
        end = millennium * 1000
        return build_normalized_date(start, end, "BC", format_display(start, end, "BC"))

    start = (millennium - 1) * 1000
    end = millennium * 1000
    return build_normalized_date(start, end, "AD", format_display(start, end, "AD"))


def number_word_value(raw):
    text = raw.lower().replace(" ", "-")
    return NUMBER_WORDS.get(text) or ORDINAL_WORDS.get(text)


def parse_years_ago(text):
    lowered = text.lower()
    if "million" in lowered and "year" in lowered:
        return long_ago_date()

    match = re.search(r"\b(\d[\d,\.]*)\s*(million\s+)?years?\s+ago\b", lowered)
    if match:
        if match.group(2):
            return long_ago_date()
        years_ago = int(float(match.group(1).replace(",", "")))
        return build_normalized_date(
            years_ago, years_ago, "YA", f"{years_ago:,} years ago"
        )

    word_match = re.search(r"\b([a-z]+(?:[-\s][a-z]+)?)\s+years?\s+ago\b", lowered)
    if word_match:
        years_ago = number_word_value(word_match.group(1))
        if years_ago is not None:
            return build_normalized_date(
                years_ago, years_ago, "YA", f"{years_ago:,} years ago"
            )

    return None


def parse_millennium(text):
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*millenni(?:um|a)\b", text, re.I)
    if match:
        return millennium_years(int(match.group(1)), era_from_text(text))

    lowered = text.lower()
    for word, millennium in ORDINAL_WORDS.items():
        if f"{word} millennium" in lowered:
            return millennium_years(millennium, era_from_text(text))
    return None


def parse_century(text):
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*centur(?:y|ies)\b", text, re.I)
    if match:
        return century_years(int(match.group(1)), era_from_text(text))

    lowered = text.lower()
    for word, century in ORDINAL_WORDS.items():
        if f"{word} century" in lowered:
            return century_years(century, era_from_text(text))
    return None


def parse_decade(text):
    match = re.search(r"\b(\d{3,4})s\b", text, re.I)
    if not match:
        return None
    start = int(match.group(1))
    end = start + 99 if start % 100 == 0 else start + 9
    era = era_from_text(text)
    return build_normalized_date(start, end, era, format_display(start, end, era))


def parse_year_range(text):
    era = era_from_text(text)
    matches = re.findall(r"\b(\d{1,5})\b", text)
    if len(matches) < 2 or not re.search(r"\d\s*(?:-|to|and)\s*\d", text, re.I):
        return None

    first = int(matches[0])
    second = int(matches[1])
    if first > 50000 or second > 50000:
        return long_ago_date()

    return build_normalized_date(
        first, second, era, format_display(first, second, era)
    )


def parse_single_year(text):
    match = re.search(r"\b(\d{1,5})\b", text)
    if not match:
        return None
    year = int(match.group(1))
    if year > 50000:
        return long_ago_date()
    era = era_from_text(text)
    return build_normalized_date(year, year, era, f"{year} {era}")


def parse_llm_date_text(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "unknown", "unclear"}:
        return None

    for parser in (
        parse_years_ago,
        parse_millennium,
        parse_century,
        parse_decade,
        parse_year_range,
        parse_single_year,
    ):
        parsed = parser(text)
        if parsed:
            return parsed

    return None


parseLlmDateText = parse_llm_date_text


def validate_normalized_date(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        return None

    bc_ad = value.get("BC_AD")
    display = value.get("display")
    timeline_start = value.get("timeline_start")
    timeline_end = value.get("timeline_end")

    if bc_ad not in {"AD", "BC", "LONG_AGO"}:
        return None
    if not isinstance(display, str) or not display.strip():
        return None
    if not isinstance(timeline_start, (int, float)):
        return None
    if not isinstance(timeline_end, (int, float)):
        return None

    start_date = value.get("start_date")
    end_date = value.get("end_date")

    if bc_ad == "LONG_AGO":
        if int(timeline_start) != LONG_AGO_YEAR or int(timeline_end) != LONG_AGO_YEAR:
            return None
        return {
            "start_date": None,
            "end_date": None,
            "BC_AD": "LONG_AGO",
            "display": "A long time ago",
            "timeline_start": LONG_AGO_YEAR,
            "timeline_end": LONG_AGO_YEAR,
        }

    if not isinstance(start_date, (int, float)):
        return None
    if not isinstance(end_date, (int, float)):
        return None

    start_date = int(start_date)
    end_date = int(end_date)
    timeline_start = int(timeline_start)
    timeline_end = int(timeline_end)

    if bc_ad == "AD":
        if timeline_start > timeline_end:
            return None
    elif bc_ad == "BC":
        if timeline_start > timeline_end:
            return None
        if timeline_start >= 0 or timeline_end >= 0:
            return None

    if timeline_start < TIMELINE_MIN_YEAR:
        return long_ago_date()

    return {
        "start_date": start_date,
        "end_date": end_date,
        "BC_AD": bc_ad,
        "display": display.strip(),
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
    }


def parser_examples():
    return {
        "ten million years ago": parse_llm_date_text("ten million years ago"),
        "10 million years ago": parse_llm_date_text("10 million years ago"),
        "17th century": parse_llm_date_text("17th century"),
        "1310": parse_llm_date_text("1310"),
        "1700s": parse_llm_date_text("1700s"),
        "10th century BC": parse_llm_date_text("10th century BC"),
        "5th millennium BC": parse_llm_date_text("5th millennium BC"),
        "1400-1600": parse_llm_date_text("1400-1600"),
        "900-1000 BC": parse_llm_date_text("900-1000 BC"),
        "unknown": parse_llm_date_text("unknown"),
    }
