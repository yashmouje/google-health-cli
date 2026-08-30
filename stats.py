#!/usr/bin/env python3
"""Pull Fitbit Air data via ghealth and print CLI stats + terminal graphs."""
import subprocess
import json
import sys
import argparse
import statistics
from datetime import date, timedelta

GHEALTH = "./ghealth"

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


def collect(start, end):
    metrics = {}

    rows = series(ghealth_json("data", "steps", "daily-rollup", "--from", str(start), "--to", str(end)))
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

    rows = series(ghealth_json("data", "heart-rate", "daily-rollup", "--from", str(start), "--to", str(end)))
    metrics["heart_rate"] = {
        "label": "Heart Rate", "unit": " bpm", "icon": "❤",
        "dates": [r["date"] for r in rows if "beatsPerMinuteAvg" in r],
        "values": [r["beatsPerMinuteAvg"] for r in rows if "beatsPerMinuteAvg" in r],
    }

    rows = series(ghealth_json("data", "active-zone-minutes", "daily-rollup", "--from", str(start), "--to", str(end)))
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

    return metrics


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
    args = parser.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days - 1)

    print(f"\n{BOLD}{CYAN}Fitbit Air{RESET}  {DIM}last {args.days} days ({start} to {end}){RESET}\n")

    metrics = collect(start, end)
    print_glance(metrics)

    colors = [CYAN, MAGENTA, GREEN, YELLOW]
    for (key, m), color in zip(metrics.items(), colors):
        print_header(f"{m['icon']}  {m['label']}", color)
        print_stats(m["values"], m["unit"])
        plot(m["dates"], m["values"], f"{m['label']} / day", m["unit"])

    print()


if __name__ == "__main__":
    main()
