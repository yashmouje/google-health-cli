#!/usr/bin/env python3
"""Pull Fitbit Air data via ghealth and print CLI stats + terminal graphs."""
import subprocess
import json
import sys
import math
import argparse
import statistics
from datetime import date, timedelta

GHEALTH = "./ghealth"

# SpO2 is sampled continuously; a day with only a handful of readings is a
# partial/incomplete day, not a real measurement. Averaging it alongside full
# days makes today (or a day you took the band off) look like a health event.
MIN_SPO2_SAMPLES = 50

# --- ANSI colors ---
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
GRAY = "\033[90m"


def ghealth_json(*args):
    result = subprocess.run([GHEALTH, *args], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ! ghealth {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}", file=sys.stderr)
        return []
    try:
        d = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(d, dict):
        return d.get("dataPoints", [])
    return d


def series(rows, date_key="date"):
    return sorted(rows, key=lambda r: r.get(date_key, ""))


def daily_rollup_chunked(data_type, start, end, chunk_days=14):
    """Rollup endpoints cap the range per request (heart-rate: 14d, steps and
    active-zone-minutes: 90d). Pull in <=chunk_days windows and merge."""
    rows = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        rows.extend(ghealth_json("data", data_type, "daily-rollup", "--from", str(cursor), "--to", str(chunk_end)))
        cursor = chunk_end + timedelta(days=1)
    return rows


def trend_pct(values):
    if len(values) < 4:
        return None
    mid = len(values) // 2
    first_half = statistics.mean(values[:mid])
    second_half = statistics.mean(values[mid:])
    if first_half == 0:
        return None
    return (second_half - first_half) / first_half * 100


def arrow(pct):
    if pct is None:
        return f"{GRAY}·{RESET}"
    if pct > 1:
        return f"{GREEN}▲{RESET}"
    if pct < -1:
        return f"{RED}▼{RESET}"
    return f"{YELLOW}▬{RESET}"


def print_stats(values, unit=""):
    if not values:
        print("  no data")
        return
    pct = trend_pct(values)
    direction = "up" if (pct or 0) > 0 else "down" if (pct or 0) < 0 else "flat"
    trend_color = GREEN if (pct or 0) > 1 else RED if (pct or 0) < -1 else YELLOW
    print(f"  avg: {BOLD}{statistics.mean(values):.1f}{unit}{RESET}   "
          f"min: {min(values):.1f}{unit}   "
          f"max: {max(values):.1f}{unit}   "
          f"latest: {BOLD}{values[-1]:.1f}{unit}{RESET}")
    if pct is not None:
        print(f"  trend: {trend_color}{direction} {abs(pct):.1f}%{RESET} "
              f"{DIM}(first half {statistics.mean(values[:len(values)//2]):.1f} "
              f"-> second half {statistics.mean(values[len(values)//2:]):.1f}){RESET}")


def print_header(title, color=CYAN):
    print(f"\n{BOLD}{color}{title}{RESET}")
    print(f"{color}{'─' * len(title)}{RESET}")


def plot(dates, values, title, unit=""):
    import plotext as plt
    if not values:
        return
    plt.clf()
    plt.date_form("Y-m-d")
    plt.plot(dates, values, marker="braille", color="cyan")
    plt.title(title)
    plt.ylabel(unit)
    plt.plotsize(70, 15)
    plt.theme("clear")
    plt.show()


def fetch_age():
    result = subprocess.run([GHEALTH, "user", "profile", "get"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        d = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return d.get("age")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def collect(start, end):
    metrics = {}

    rows = series(daily_rollup_chunked("steps", start, end, chunk_days=90))
    metrics["steps"] = {
        "label": "Steps", "unit": "", "icon": "🏃",
        "dates": [r["date"] for r in rows if "countSum" in r],
        "values": [float(r["countSum"]) for r in rows if "countSum" in r],
    }

    rows = series(ghealth_json("data", "sleep", "list", "--from", str(start), "--to", str(end)), date_key="end")
    metrics["sleep"] = {
        "label": "Sleep", "unit": "h", "icon": "🌙",
        "dates": [r["end"][:10] for r in rows if "minutesAsleep" in r],
        "values": [r["minutesAsleep"] / 60.0 for r in rows if "minutesAsleep" in r],
    }

    rows = series(daily_rollup_chunked("heart-rate", start, end))
    metrics["heart_rate"] = {
        "label": "Heart Rate", "unit": " bpm", "icon": "❤",
        "dates": [r["date"] for r in rows if "beatsPerMinuteAvg" in r],
        "values": [r["beatsPerMinuteAvg"] for r in rows if "beatsPerMinuteAvg" in r],
    }

    rows = series(daily_rollup_chunked("active-zone-minutes", start, end, chunk_days=90))
    dates, values = [], []
    for r in rows:
        if "date" not in r:
            continue
        total = (int(r.get("sumInFatBurnHeartZone", 0))
                 + int(r.get("sumInCardioHeartZone", 0))
                 + int(r.get("sumInPeakHeartZone", 0)))
        dates.append(r["date"])
        values.append(float(total))
    metrics["azm"] = {"label": "Active Zone Minutes", "unit": " min", "icon": "⚡", "dates": dates, "values": values}
    metrics["azm"]["raw_rows"] = rows

    rows = series(ghealth_json("data", "daily-heart-rate-variability", "list", "--from", str(start), "--to", str(end)))
    metrics["hrv"] = {
        "label": "Heart Rate Variability", "unit": " ms", "icon": "〰",
        "dates": [r["date"] for r in rows if "averageHeartRateVariabilityMilliseconds" in r],
        "values": [float(r["averageHeartRateVariabilityMilliseconds"]) for r in rows if "averageHeartRateVariabilityMilliseconds" in r],
    }
    metrics["resting_hr"] = {
        "dates": [r["date"] for r in rows if "nonRemHeartRateBeatsPerMinute" in r],
        "values": [float(r["nonRemHeartRateBeatsPerMinute"]) for r in rows if "nonRemHeartRateBeatsPerMinute" in r],
    }

    rows = ghealth_json("data", "oxygen-saturation", "list", "--from", str(start), "--to", str(end), "--limit", "5000")
    by_day = {}
    for r in rows:
        if "percentage" not in r or "time" not in r:
            continue
        by_day.setdefault(r["time"][:10], []).append(r["percentage"])
    full_days = sorted(d for d in by_day if len(by_day[d]) >= MIN_SPO2_SAMPLES)
    dropped = sorted(d for d in by_day if len(by_day[d]) < MIN_SPO2_SAMPLES)
    metrics["spo2"] = {
        "label": "Blood Oxygen (SpO2)", "unit": "%", "icon": "🫁",
        "dates": full_days,
        "values": [statistics.mean(by_day[d]) for d in full_days],
        "dropped_days": dropped,
    }

    return metrics


def compute_recovery(metrics):
    """WHOOP-style recovery %: blends HRV vs personal baseline, resting HR vs
    baseline, and last night's sleep. Directional, not a medical score."""
    hrv_vals = metrics["hrv"]["values"]
    rhr_vals = metrics["resting_hr"]["values"]
    sleep_vals = metrics["sleep"]["values"]
    if len(hrv_vals) < 2 or len(rhr_vals) < 2 or not sleep_vals:
        return None

    baseline_hrv = statistics.mean(hrv_vals[:-1])
    baseline_rhr = statistics.mean(rhr_vals[:-1])
    today_hrv, today_rhr = hrv_vals[-1], rhr_vals[-1]
    last_sleep = sleep_vals[-1]

    hrv_score = clamp(50 + (today_hrv / baseline_hrv - 1) * 100, 0, 100) if baseline_hrv else 50
    rhr_score = clamp(50 + (baseline_rhr / today_rhr - 1) * 100, 0, 100) if today_rhr else 50
    sleep_score = clamp(last_sleep / 8 * 100, 0, 100)

    recovery = round(0.5 * hrv_score + 0.3 * rhr_score + 0.2 * sleep_score)
    return clamp(recovery, 0, 100)


def compute_strain(azm_raw_rows):
    """WHOOP-style 0-21 strain, from the most recent day's heart-rate-zone
    minutes (peak weighted heaviest, an exponential scale so strain climbs
    fast early and flattens out at higher load, like WHOOP's)."""
    rows = [r for r in azm_raw_rows if "date" in r]
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r["date"])
    last = rows[-1]
    load = (int(last.get("sumInFatBurnHeartZone", 0)) * 1
            + int(last.get("sumInCardioHeartZone", 0)) * 2
            + int(last.get("sumInPeakHeartZone", 0)) * 3)
    strain = 21 * (1 - pow(2.71828, -load / 60))
    return round(clamp(strain, 0, 21), 1)


def compute_fitness_age(chrono_age, metrics):
    """A fun, directional 'fitness age' -- NOT a medical or clinical
    measurement. Nudges your real age up/down based on how your resting HR,
    HRV, daily steps, and sleep compare to healthy-adult reference points."""
    if chrono_age is None:
        return None

    rhr_vals = metrics["resting_hr"]["values"]
    hrv_vals = metrics["hrv"]["values"]
    steps_vals = metrics["steps"]["values"]
    sleep_vals = metrics["sleep"]["values"]
    if not (rhr_vals and hrv_vals and steps_vals and sleep_vals):
        return None

    avg_rhr = statistics.mean(rhr_vals)
    avg_hrv = statistics.mean(hrv_vals)
    avg_steps = statistics.mean(steps_vals)
    avg_sleep = statistics.mean(sleep_vals)

    rhr_adj = (avg_rhr - 60) / 5        # reference: 60 bpm resting HR
    hrv_adj = (45 - avg_hrv) / 5        # reference: 45ms RMSSD
    activity_adj = (9000 - avg_steps) / 2000   # reference: 9k steps/day
    sleep_adj = max(0.0, 7.5 - avg_sleep)      # reference: 7.5h/night

    delta = (rhr_adj + hrv_adj + activity_adj + sleep_adj) / 2
    fitness_age = clamp(chrono_age + delta, chrono_age - 15, chrono_age + 25)
    return round(fitness_age, 1)


def score_color(pct, good_high=True):
    if pct is None:
        return GRAY
    if good_high:
        return GREEN if pct >= 67 else YELLOW if pct >= 34 else RED
    return GREEN if pct <= 34 else YELLOW if pct <= 67 else RED


def print_performance(metrics, chrono_age):
    recovery = compute_recovery(metrics)
    strain = compute_strain(metrics["azm"].get("raw_rows", []))
    sleep_vals = metrics["sleep"]["values"]
    sleep_perf = round(clamp(sleep_vals[-1] / 8 * 100, 0, 150)) if sleep_vals else None
    fitness_age = compute_fitness_age(chrono_age, metrics)

    print(f"\n{BOLD}{GREEN}┌{'─'*66}┐{RESET}")
    print(f"{BOLD}{GREEN}│{RESET} {BOLD}PERFORMANCE{RESET}{' '*53}{BOLD}{GREEN}│{RESET}")
    print(f"{BOLD}{GREEN}├{'─'*66}┤{RESET}")

    def row(icon, label, value_str, color):
        line = f"{icon}  {label:<20} {color}{BOLD}{value_str}{RESET}"
        pad = 66 - len(_strip_ansi(line)) - 1
        print(f"{BOLD}{GREEN}│{RESET} {line}{' '*max(pad,0)}{BOLD}{GREEN}│{RESET}")

    row("🔋", "Recovery", f"{recovery}%" if recovery is not None else "not enough data", score_color(recovery))
    row("🔥", "Strain (last day)", f"{strain} / 21" if strain is not None else "not enough data",
        score_color((strain / 21 * 100) if strain is not None else None))
    row("😴", "Sleep Performance", f"{sleep_perf}%" if sleep_perf is not None else "not enough data", score_color(sleep_perf))
    if fitness_age is not None:
        delta = fitness_age - chrono_age
        delta_str = f"{'+' if delta >= 0 else ''}{delta:.1f}y vs actual {chrono_age}"
        age_color = GREEN if delta < -1 else RED if delta > 1 else YELLOW
        row("🧬", "Fitness Age", f"{fitness_age}  {DIM}({delta_str}){RESET}", age_color)
    else:
        row("🧬", "Fitness Age", "not enough data", GRAY)

    print(f"{BOLD}{GREEN}└{'─'*66}┘{RESET}")
    print(f"{DIM}  Fitness Age is a directional, for-fun estimate from your RHR, HRV,\n"
          f"  steps and sleep vs. healthy-adult reference points -- not medical advice.{RESET}")


def as_dict(m):
    """metric entry -> {date: value}"""
    return dict(zip(m["dates"], m["values"]))


def weekly_slope(d):
    """Least-squares slope, expressed per week."""
    ks = sorted(d)
    if len(ks) < 6:
        return None
    origin = date.fromisoformat(ks[0])
    x = [(date.fromisoformat(k) - origin).days for k in ks]
    y = [d[k] for k in ks]
    mx, my = statistics.mean(x), statistics.mean(y)
    den = sum((a - mx) ** 2 for a in x)
    if not den:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / den * 7


def split_half(d):
    """Compare first half vs second half with a Welch t-statistic.
    |t| > 2 is our rough 'clears the noise bar' threshold."""
    ks = sorted(d)
    if len(ks) < 8:
        return None
    mid = len(ks) // 2
    a = [d[k] for k in ks[:mid]]
    b = [d[k] for k in ks[mid:]]
    if len(a) < 2 or len(b) < 2:
        return None
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    if not se:
        return None
    ma, mb = statistics.mean(a), statistics.mean(b)
    return {"first": ma, "last": mb, "delta": mb - ma, "t": (mb - ma) / se,
            "n_first": len(a), "n_last": len(b)}


def correlate(d1, d2):
    ks = sorted(set(d1) & set(d2))
    if len(ks) < 8:
        return None, 0
    x = [d1[k] for k in ks]
    y = [d2[k] for k in ks]
    mx, my = statistics.mean(x), statistics.mean(y)
    den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    if not den:
        return None, len(ks)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / den, len(ks)


def print_trend(metrics):
    print_header("📈  TREND ANALYSIS", MAGENTA)

    d = {k: as_dict(v) for k, v in metrics.items() if v.get("dates")}

    # --- direction of travel ---
    print(f"\n  {BOLD}Per-week drift{RESET}")
    labels = [("steps", "Steps", ""), ("azm", "Active Zone Min", " min"),
              ("sleep", "Sleep", " h"), ("hrv", "HRV", " ms"),
              ("resting_hr", "Sleeping RHR", " bpm"), ("heart_rate", "Avg HR", " bpm"),
              ("spo2", "SpO2", "%")]
    for key, label, unit in labels:
        if key not in d:
            continue
        s = weekly_slope(d[key])
        if s is None:
            continue
        # For RHR, up is bad; for everything else here, up is good.
        good_up = key not in ("resting_hr", "heart_rate")
        color = GREEN if (s > 0) == good_up else RED
        if abs(s) < 1e-9:
            color = YELLOW
        print(f"    {label:<16} {color}{s:+8.2f}{unit}/week{RESET}")

    # --- what clears the noise bar ---
    print(f"\n  {BOLD}First half vs second half{RESET} {DIM}(|t| > 2 = clears noise){RESET}")
    shown = 0
    for key, label, unit in labels:
        if key not in d:
            continue
        r = split_half(d[key])
        if r is None:
            continue
        shown += 1
        good_up = key not in ("resting_hr", "heart_rate")
        meaningful = abs(r["t"]) > 2
        if meaningful:
            color = GREEN if (r["delta"] > 0) == good_up else RED
            verdict = "meaningful"
        else:
            color = GRAY
            verdict = "within noise"
        print(f"    {label:<16} {r['first']:6.1f} → {r['last']:6.1f}{unit}  "
              f"{color}{r['delta']:+6.1f}{RESET}  {DIM}t={r['t']:+5.2f}{RESET}  {color}{verdict}{RESET}")
    if not shown:
        print(f"    {GRAY}need ~8+ days of data{RESET}")

    # --- rolling view ---
    if "hrv" in d and "resting_hr" in d:
        ks = sorted(set(d["hrv"]) & set(d["resting_hr"]))
        if len(ks) >= 10:
            print(f"\n  {BOLD}7-day rolling recovery markers{RESET}")
            step = max(1, len(ks) // 12)
            for i in range(6, len(ks), step):
                w = ks[i - 6:i + 1]
                hrv_avg = statistics.mean([d["hrv"][k] for k in w])
                rhr_avg = statistics.mean([d["resting_hr"][k] for k in w])
                bar = "█" * int(round(hrv_avg / 4))
                print(f"    {w[-1]}  hrv {hrv_avg:5.1f}ms  rhr {rhr_avg:5.1f}bpm  {CYAN}{bar}{RESET}")

    # --- correlations ---
    print(f"\n  {BOLD}Correlations{RESET} {DIM}(|r| < 0.3 is effectively nothing){RESET}")
    pairs = [("sleep", "hrv", "Sleep → HRV"),
             ("sleep", "resting_hr", "Sleep → RHR"),
             ("steps", "hrv", "Steps → HRV"),
             ("azm", "hrv", "Strain → HRV"),
             ("steps", "sleep", "Steps → Sleep"),
             ("azm", "sleep", "Strain → Sleep")]
    shown = 0
    for a, b, label in pairs:
        if a not in d or b not in d:
            continue
        r, n = correlate(d[a], d[b])
        if r is None:
            continue
        shown += 1
        color = CYAN if abs(r) >= 0.3 else GRAY
        print(f"    {label:<16} {color}r = {r:+.2f}{RESET}  {DIM}(n={n}){RESET}")
    if not shown:
        print(f"    {GRAY}need ~8+ days of data{RESET}")

    # --- consistency ---
    print(f"\n  {BOLD}Consistency{RESET}")
    if "sleep" in d:
        v = list(d["sleep"].values())
        short = sum(1 for x in v if x < 6)
        good = sum(1 for x in v if x >= 8)
        print(f"    Nights < 6h      {RED if short/len(v) > 0.2 else GREEN}{short}/{len(v)}{RESET} "
              f"{DIM}({short/len(v)*100:.0f}%){RESET}")
        print(f"    Nights ≥ 8h      {GREEN if good/len(v) > 0.3 else YELLOW}{good}/{len(v)}{RESET} "
              f"{DIM}({good/len(v)*100:.0f}%){RESET}")
    if "steps" in d:
        v = list(d["steps"].values())
        low = sum(1 for x in v if x < 5000)
        high = sum(1 for x in v if x >= 10000)
        print(f"    Days < 5k steps  {RED if low/len(v) > 0.3 else YELLOW}{low}/{len(v)}{RESET} "
              f"{DIM}({low/len(v)*100:.0f}%){RESET}")
        print(f"    Days ≥ 10k steps {GREEN if high/len(v) > 0.3 else YELLOW}{high}/{len(v)}{RESET} "
              f"{DIM}({high/len(v)*100:.0f}%){RESET}")

    dropped = metrics.get("spo2", {}).get("dropped_days", [])
    if dropped:
        print(f"\n{DIM}  Note: excluded {len(dropped)} partial SpO2 day(s) with <{MIN_SPO2_SAMPLES} "
              f"readings ({', '.join(dropped[-3:])}){RESET}")
    print(f"{DIM}  Trends are descriptive statistics on a short window, not a diagnosis.{RESET}")


def print_glance(metrics):
    print(f"{BOLD}{MAGENTA}┌{'─'*66}┐{RESET}")
    print(f"{BOLD}{MAGENTA}│{RESET} {BOLD}AT A GLANCE{RESET}{' '*53}{BOLD}{MAGENTA}│{RESET}")
    print(f"{BOLD}{MAGENTA}├{'─'*66}┤{RESET}")
    for m in metrics.values():
        values = m["values"]
        if not values:
            line = f"{m['icon']}  {m['label']:<20} {GRAY}no data{RESET}"
        else:
            latest = values[-1]
            avg = statistics.mean(values)
            pct = trend_pct(values)
            a = arrow(pct)
            pct_str = f"{abs(pct):4.1f}%" if pct is not None else "  -- "
            line = (f"{m['icon']}  {m['label']:<20} "
                     f"{BOLD}{latest:>8.1f}{m['unit']:<4}{RESET} "
                     f"{DIM}(avg {avg:.1f}{m['unit']}){RESET}  "
                     f"{a} {pct_str}")
        pad = 66 - len(_strip_ansi(line)) - 1
        print(f"{BOLD}{MAGENTA}│{RESET} {line}{' '*max(pad,0)}{BOLD}{MAGENTA}│{RESET}")
    print(f"{BOLD}{MAGENTA}└{'─'*66}┘{RESET}")


def _strip_ansi(s):
    import re
    return re.sub(r"\033\[[0-9;]*m", "", s)


def main():
    parser = argparse.ArgumentParser(description="Fitbit Air stats + terminal graphs via ghealth")
    parser.add_argument("--days", type=int, default=14, help="Days of history to pull (default 14)")
    parser.add_argument("--trend", action="store_true",
                        help="Run trend analysis (drift, significance, correlations) instead of graphs")
    args = parser.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days - 1)

    print(f"\n{BOLD}{CYAN}Fitbit Air{RESET}  {DIM}last {args.days} days ({start} to {end}){RESET}\n")

    metrics = collect(start, end)
    chrono_age = fetch_age()

    graphable = {k: v for k, v in metrics.items() if k != "resting_hr"}
    print_glance(graphable)
    print_performance(metrics, chrono_age)

    if args.trend:
        print_trend(metrics)
    else:
        colors = [CYAN, MAGENTA, GREEN, YELLOW, "\033[95m", "\033[94m"]
        for (key, m), color in zip(graphable.items(), colors):
            print_header(f"{m['icon']}  {m['label']}", color)
            print_stats(m["values"], m["unit"])
            plot(m["dates"], m["values"], f"{m['label']} / day", m["unit"])

    print()


if __name__ == "__main__":
    main()
