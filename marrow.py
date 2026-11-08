#!/usr/bin/env python3
"""
Marrow prototype: decide whether the person at the computer is the enrolled user,
from the ordinary input events an operating system already sees.

Pointer movement, clicks, and text as it arrives (typed, on-screen keyboard, or
inserted by software such as dictation), including the pattern of corrections.
No audio, no camera, no assumption about the pointing device.

One command, from a fresh copy:

    python3 marrow.py

That generates fake data, enrols a profile, fixes a threshold, evaluates the
threshold on data it never saw during enrolment, runs the swap test, and writes
results/report.md.

Other commands:

    python3 marrow.py gen
    python3 marrow.py train --enroll <dir> --out profile.json
    python3 marrow.py score --profile profile.json --recordings <dir>

Standard library only. Python 3.8+.
"""

import argparse
import json
import math
import os
import random
import statistics
import sys
import time

RECORD_VERSION = 1
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RESULTS = os.path.join(HERE, "results")
SESSION_MS = 60000
EPS = 1e-9


# ---------------------------------------------------------------- input styles

# Two input styles, fixed before any detector code was written.
# speed is in screen fractions per second; tremor and bow are ratios of the
# step length, so they are independent of screen size and of the device.
STYLES = {
    "mouse_keyboard": {
        "speed": 0.45,
        "tremor": 0.035,
        "bow": 0.05,
        "hover_ms": 120,
        "hover_jit": 0.25,
        "click_gap_ms": 5200,
        "text_mode": "typed",
        "key_ms": 112,
        "key_jit": 0.30,
        "chunk_words": 1,
        "insert_ms": 0,
        "corr_per_word": 0.03,
        "corr_lag_ms": 420,
        "corr_chars": 1,
        "text_share": 0.45,
    },
    "joystick_dictation": {
        "speed": 0.085,
        "tremor": 0.55,
        "bow": 0.30,
        "hover_ms": 560,
        "hover_jit": 0.35,
        "click_gap_ms": 9000,
        "text_mode": "insert",
        "key_ms": 0,
        "key_jit": 0.0,
        "chunk_words": 9,
        "insert_ms": 2600,
        "corr_per_word": 0.38,
        "corr_lag_ms": 1700,
        "corr_chars": 3,
        "text_share": 0.50,
    },
}

# Personas. "owner" is the enrolled user; "owner_tired" is the same person in
# the evening; "stranger" is somebody else; "mimic" has watched the owner and
# copies the coarse habits (speed, hover, rhythm) but not the fine ones.
PERSONAS = {
    "owner": {},
    "owner_tired": {
        "speed": 0.72,
        "hover": 1.45,
        "tremor": 1.50,
        "corr": 1.80,
        "text_slow": 1.30,
    },
    "stranger": {
        "speed": 1.70,
        "hover": 0.45,
        "tremor": 0.45,
        "bow": 0.45,
        "corr": 0.25,
        "text_slow": 0.65,
    },
    "mimic": {
        "speed": 1.00,
        "hover": 1.00,
        "tremor": 2.60,
        "bow": 2.40,
        "corr": 0.35,
        "corr_lag": 0.45,
        "burst_irreg": 2.20,
    },
}

GROUPS = {
    "mouse_keyboard": ["owner", "owner_tired", "stranger", "mimic"],
    "joystick_dictation": ["owner", "owner_tired", "stranger", "mimic"],
}


def style_params(style, persona):
    p = dict(STYLES[style])
    m = PERSONAS[persona]
    p["speed"] *= m.get("speed", 1.0)
    p["tremor"] *= m.get("tremor", 1.0)
    p["bow"] *= m.get("bow", 1.0)
    p["hover_ms"] *= m.get("hover", 1.0)
    p["corr_per_word"] *= m.get("corr", 1.0)
    p["corr_lag_ms"] *= m.get("corr_lag", 1.0)
    slow = m.get("text_slow", 1.0)
    p["key_ms"] *= slow
    p["insert_ms"] *= slow
    p["burst_irreg"] = m.get("burst_irreg", 1.0)
    return p


# ------------------------------------------------------------------- generator

WORDS = ("the quick brown fox jumps over lazy dog while cursor drifts across "
         "screen and text arrives in bursts with occasional corrections made "
         "later than the writer intended").split()


def _jitter(rng, ratio):
    return 1.0 + rng.uniform(-ratio, ratio)


def simulate_session(p, seed, duration_ms=SESSION_MS):
    """Produce raw events from a physical-ish process. No feature values are
    injected here: the detector sees only the event stream below."""
    rng = random.Random(seed)
    events = []
    t = 0
    x, y = rng.random(), rng.random()
    heading = rng.uniform(0, 2 * math.pi)
    step_ms = 30
    pending_correction = None

    def add(kind, **kw):
        e = {"t": int(t), "kind": kind}
        e.update(kw)
        events.append(e)

    while t < duration_ms:
        if rng.random() < p["text_share"]:
            # ---- text arrives
            if p["text_mode"] == "typed":
                word = rng.choice(WORDS)
                for ch in word + " ":
                    if t >= duration_ms:
                        break
                    add("key", source="typed", text=ch)
                    t += max(8, int(p["key_ms"] * _jitter(rng, p["key_jit"])))
                if rng.random() < p["corr_per_word"]:
                    pending_correction = (t + p["corr_lag_ms"] * _jitter(rng, 0.5),
                                          int(p["corr_chars"]))
            else:
                words = max(1, int(p["chunk_words"] * _jitter(rng, 0.45)))
                text = " ".join(rng.choice(WORDS) for _ in range(words))
                add("insert", source="software", text=text)
                t += max(150, int(p["insert_ms"] * _jitter(rng, 0.30 * p["burst_irreg"])))
                if rng.random() < min(1.0, p["corr_per_word"]):
                    pending_correction = (t + p["corr_lag_ms"] * _jitter(rng, 0.5),
                                          int(p["corr_chars"]))
        else:
            # ---- pointer travels to a target, hovers, clicks
            tx, ty = rng.random(), rng.random()
            dx, dy = tx - x, ty - y
            dist = math.hypot(dx, dy)
            if dist < 0.02:
                tx, ty = rng.random(), rng.random()
                dx, dy = tx - x, ty - y
                dist = math.hypot(dx, dy)
            heading = math.atan2(dy, dx)
            step_len = p["speed"] * step_ms / 1000.0
            travelled = 0.0
            while travelled < dist and t < duration_ms:
                heading += p["bow"] * 0.02 * rng.choice((-1.0, 1.0))
                nx = math.cos(heading) * step_len
                ny = math.sin(heading) * step_len
                nx += -math.sin(heading) * step_len * p["tremor"] * rng.gauss(0, 1)
                ny += math.cos(heading) * step_len * p["tremor"] * rng.gauss(0, 1)
                x = min(1.0, max(0.0, x + nx))
                y = min(1.0, max(0.0, y + ny))
                travelled += step_len
                t += step_ms
                add("move", x=round(x, 5), y=round(y, 5))
            t += max(10, int(p["hover_ms"] * _jitter(rng, p["hover_jit"])))
            if t < duration_ms:
                add("click", x=round(x, 5), y=round(y, 5), button="left")
            t += max(200, int(p["click_gap_ms"] * _jitter(rng, 0.35)))

        if pending_correction and t >= pending_correction[0]:
            at, chars = pending_correction
            if at < duration_ms:
                t = at
                add("delete", source=p["text_mode"], chars=chars)
            pending_correction = None

    events.sort(key=lambda e: e["t"])
    return events


def write_recording(path, events, meta):
    with open(path, "w", encoding="utf-8") as f:
        head = {"v": RECORD_VERSION, "kind": "session"}
        head.update(meta)
        f.write(json.dumps(head) + "\n")
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")


def read_recording(path):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("kind") == "session":
                continue
            events.append(e)
    events.sort(key=lambda e: e["t"])
    return events


def generate_all(force=False):
    """Deterministic fake data: 2 styles x 4 personas, several sessions each.
    Names are opaque on purpose; the detector never reads a persona label."""
    plan = {
        "owner": 6,          # 4 enrol + 2 calibration
        "owner_tired": 3,
        "stranger": 4,
        "mimic": 3,
    }
    made = 0
    for style in STYLES:
        for persona, count in plan.items():
            d = os.path.join(DATA, style, persona)
            os.makedirs(d, exist_ok=True)
            for i in range(count):
                name = os.path.join(d, f"s{i + 1:02d}.jsonl")
                if os.path.exists(name) and not force:
                    continue
                seed = 7000 + (abs(hash(style)) % 1000) * 100 + \
                    abs(hash(persona)) % 97 * 7 + i * 13
                seed = 7000 + (list(STYLES).index(style) + 1) * 1000 + \
                    (list(plan).index(persona) + 1) * 100 + i * 13
                p = style_params(style, persona)
                ev = simulate_session(p, seed)
                write_recording(name, ev, {
                    "id": f"{style}-{persona}-s{i + 1:02d}",
                    "style": style,
                    "persona": persona,
                    "synthetic": True,
                    "note": "fake session generated by marrow.py; no real movement data",
                })
                made += 1
    return made


# ------------------------------------------------------------------- features

def _median(vals, default=None):
    vals = [v for v in vals if v is not None and math.isfinite(v)]
    return statistics.median(vals) if vals else default


def _iqr(vals):
    vals = sorted(v for v in vals if v is not None and math.isfinite(v))
    if len(vals) < 4:
        return None
    q1 = vals[len(vals) // 4]
    q3 = vals[(3 * len(vals)) // 4]
    return q3 - q1


def extract_features(events):
    """Every feature is a ratio, a rate, or a duration, so nothing depends on
    screen size, absolute pixel coordinates, OS, or the recording tool."""
    moves = [e for e in events if e["kind"] == "move"]
    clicks = [e for e in events if e["kind"] == "click"]
    arrivals = []      # (t, chars) regardless of how the text arrived
    deletes = []
    for e in events:
        if e["kind"] == "key":
            arrivals.append((e["t"], 1))
        elif e["kind"] == "insert":
            arrivals.append((e["t"], len(e.get("text", ""))))
        elif e["kind"] == "delete":
            deletes.append((e["t"], int(e.get("chars", 1))))

    if len(events) < 20:
        return {}
    span_s = max(1e-3, (events[-1]["t"] - events[0]["t"]) / 1000.0)
    minutes = span_s / 60.0

    # ---- pointer kinematics
    steps = []          # (dt_ms, len, heading, second_diff_ratio)
    for a, b in zip(moves, moves[1:]):
        dt = b["t"] - a["t"]
        if dt <= 0:
            continue
        ln = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
        steps.append((dt, ln, math.atan2(b["y"] - a["y"], b["x"] - a["x"])))
    speeds = [ln / (dt / 1000.0) for dt, ln, _ in steps]
    turns = []
    for s1, s2 in zip(steps, steps[1:]):
        d = abs((s2[2] - s1[2] + math.pi) % (2 * math.pi) - math.pi)
        if s2[1] > EPS:
            turns.append(d / s2[1])   # radians per screen fraction: shape, not speed
    jitters = []
    for i in range(1, len(moves) - 1):
        ax, ay = moves[i - 1]["x"], moves[i - 1]["y"]
        bx, by = moves[i]["x"], moves[i]["y"]
        cx, cy = moves[i + 1]["x"], moves[i + 1]["y"]
        second = math.hypot(cx - 2 * bx + ax, cy - 2 * by + ay)
        base = math.hypot(bx - ax, by - ay)
        if base > EPS:
            jitters.append(second / base)

    # ---- segments between clicks: straightness of the path
    straight = []
    seg = []
    for e in events:
        if e["kind"] == "move":
            seg.append(e)
        elif e["kind"] == "click":
            if len(seg) >= 3:
                path = sum(math.hypot(b["x"] - a["x"], b["y"] - a["y"])
                           for a, b in zip(seg, seg[1:]))
                disp = math.hypot(seg[-1]["x"] - seg[0]["x"], seg[-1]["y"] - seg[0]["y"])
                if path > EPS:
                    straight.append(disp / path)
            seg = []

    # ---- clicks
    hovers = []
    last_move_t = None
    for e in events:
        if e["kind"] == "move":
            last_move_t = e["t"]
        elif e["kind"] == "click" and last_move_t is not None:
            hovers.append(e["t"] - last_move_t)
    click_gaps = [b["t"] - a["t"] for a, b in zip(clicks, clicks[1:])]

    move_gaps = [b["t"] - a["t"] for a, b in zip(moves, moves[1:])]
    med_gap = _median(move_gaps, 0)
    pause_frac = None
    if move_gaps and med_gap:
        pause_frac = sum(1 for g in move_gaps if g > 3 * med_gap) / len(move_gaps)

    # ---- text rhythm
    arr_times = [t for t, _ in arrivals]
    arr_chars = [c for _, c in arrivals]
    arr_int = [b - a for a, b in zip(arr_times, arr_times[1:])]
    arr_int_med = _median(arr_int)
    irreg = None
    if arr_int_med and len(arr_int) >= 4:
        iqr = _iqr(arr_int)
        if iqr is not None:
            irreg = iqr / arr_int_med

    corr_lag = []
    for dt_, _ in deletes:
        prev = [t for t in arr_times if t <= dt_]
        if prev:
            corr_lag.append(dt_ - prev[-1])

    speed_cv = None
    if len(speeds) > 2 and statistics.mean(speeds) > EPS:
        speed_cv = statistics.pstdev(speeds) / statistics.mean(speeds)

    total_in = sum(arr_chars)
    total_del = sum(c for _, c in deletes)

    f = {
        "speed_med": _median(speeds),
        "speed_p90": (sorted(speeds)[int(0.9 * (len(speeds) - 1))] if speeds else None),
        "hover_med": _median(hovers),
        "click_gap_med": _median(click_gaps),
        "straightness_med": _median(straight),
        "turn_per_dist": _median(turns),
        "jitter_med": _median(jitters),
        "pause_frac": pause_frac,
        "arr_int_med": arr_int_med,
        "chars_per_arr_med": _median(arr_chars),
        "arr_irreg": irreg,
        "del_ratio": (total_del / total_in) if total_in else None,
        "corr_lag_med": _median(corr_lag),
        "txt_rate": (total_in / minutes) if minutes else None,
        "move_rate": (len(moves) / minutes) if minutes else None,
        "speed_cv": speed_cv,
    }
    f["corr_lag_rel"] = (f["corr_lag_med"] / f["arr_int_med"]
                         if f.get("corr_lag_med") and f.get("arr_int_med") else None)
    return {k: float(v) for k, v in f.items() if v is not None and math.isfinite(v)}


# --------------------------------------------------------------------- profile

FEATURES = ["speed_med", "speed_p90", "hover_med", "click_gap_med", "straightness_med",
            "turn_per_dist", "jitter_med", "pause_frac", "arr_int_med", "chars_per_arr_med",
            "arr_irreg", "del_ratio", "corr_lag_med", "txt_rate", "move_rate",
            "speed_cv", "corr_lag_rel"]

# Identity lives in the shape of the movement and the rhythm of corrections;
# fatigue lives in the magnitudes. Shape features carry twice the weight, so a
# tired owner drifts without opening the door for someone copying the numbers.
SHAPE = {"straightness_med", "turn_per_dist", "jitter_med", "arr_irreg",
         "speed_cv", "corr_lag_rel", "corr_lag_med"}
WEIGHTS = {f: (2.0 if f in SHAPE else 1.0) for f in FEATURES}

TOP_K = 5          # kept for the report: how many habits may drift at once
Z_CLIP = 6.0
TOL_FLOOR = 0.25   # 25% multiplicative tolerance: ordinary session-to-session spread


def _tf(name, v):
    """Heavy-tailed session features are compared in log space, so a doubling
    counts the same whether the value is 0.05 or 5. A handful of bounded ratios
    use a logit or an offset instead."""
    if v is None or not math.isfinite(v):
        return None
    if name == "straightness_med":
        s = min(0.999, max(0.001, v))
        return math.log(s / (1.0 - s))
    if name in ("pause_frac", "del_ratio", "arr_irreg"):
        return math.log(v + 0.01)
    if v <= 0:
        return None
    return math.log(v)


def enrol(feature_rows):
    prof = {}
    for name in FEATURES:
        vals = [_tf(name, r[name]) for r in feature_rows if name in r]
        vals = [v for v in vals if v is not None]
        if len(vals) < 2:
            continue
        med = statistics.median(vals)
        mad = statistics.median([abs(v - med) for v in vals]) * 1.4826
        mad = max(mad, TOL_FLOOR)
        prof[name] = {"med": med, "mad": mad, "n": len(vals)}
    return prof


def score(profile, feats):
    items = []
    for name, p in profile.items():
        if name not in feats:
            continue
        t = _tf(name, feats[name])
        if t is None:
            continue
        items.append((min(abs(t - p["med"]) / p["mad"], Z_CLIP), WEIGHTS.get(name, 1.0)))
    if len(items) < 6:
        return None
    wsum = sum(w for _, w in items)
    mean = sum(z * w for z, w in items) / wsum
    items.sort(key=lambda t: t[0] * t[1], reverse=True)
    top = items[:TOP_K]
    tw = sum(w for _, w in top)
    topm = sum(z * w for z, w in top) / tw
    return 0.55 * mean + 0.45 * topm


def calibrate(profile, calib_rows, frr_target=0.10):
    """Fix the threshold from the owner's own held-out sessions only, then write
    it to disk. Evaluation reads the file; it never recomputes the threshold."""
    scores = [s for s in (score(profile, r) for r in calib_rows) if s is not None]
    if not scores:
        raise SystemExit("calibration failed: no scorable owner sessions")
    worst = max(scores)
    threshold = min(5.0, max(1.0, worst * 1.15))
    return {
        "threshold": round(threshold, 4),
        "calibration_scores": [round(s, 4) for s in scores],
        "worst_calibration_score": round(worst, 4),
        "rule": "threshold = 1.15 x worst score on the owner's calibration sessions",
        "frr_target": frr_target,
        "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "computed from enrolment/calibration sessions only, before any test data was scored",
    }


def adapt(profile, feats, rate):
    """Move the profile toward a session that has been trusted. Slow by default,
    faster after the master password has confirmed the person."""
    for name, p in profile.items():
        t = _tf(name, feats.get(name))
        if t is None:
            continue
        p["med"] = (1.0 - rate) * p["med"] + rate * t


# ------------------------------------------------------------------ evaluation

def load_group(style, persona):
    d = os.path.join(DATA, style, persona)
    rows = []
    for name in sorted(os.listdir(d)):
        if name.endswith(".jsonl"):
            rows.append(extract_features(read_recording(os.path.join(d, name))))
    return rows


def evaluate(style, threshold):
    prof = enrol(load_group(style, "owner")[:4])
    calib = load_group(style, "owner")[4:]
    out = {"style": style, "threshold": threshold, "groups": {}}
    for persona in ("owner", "owner_tired", "stranger", "mimic"):
        rows = load_group(style, persona)
        if persona == "owner":
            rows = calib          # the enrolled half is not a test
        decided = []
        for r in rows:
            s = score(prof, r)
            decided.append({"score": None if s is None else round(s, 3),
                            "accept": (s is not None and s <= threshold)})
        out["groups"][persona] = decided
    return out


def drift_test(style, threshold):
    """The owner changes. Walk the tired sessions in order: a session inside the
    threshold opens and nudges the profile; a session outside it asks for the
    password, and only then teaches the profile. After every update a stranger
    session is scored again, so drift cannot become an open door."""
    prof = enrol(load_group(style, "owner")[:4])
    tired = load_group(style, "owner_tired")
    strangers = load_group(style, "stranger") + load_group(style, "mimic")
    rows = []
    for i, s in enumerate(tired):
        sc = score(prof, s)
        if sc is None:
            continue
        if sc <= threshold:
            decision = "open"
            adapt(prof, s, 0.20)
        else:
            decision = "ask password"
            adapt(prof, s, 0.50)
        st = score(prof, strangers[i % len(strangers)])
        rows.append({
            "session": i + 1,
            "score": round(sc, 3),
            "decision": decision,
            "stranger_score_after": None if st is None else round(st, 3),
            "stranger_refused": (st is not None and st > threshold),
        })
    return rows


def swap_test(style, threshold):
    """Train on one persona, then score every persona's sessions. The profile
    trained on someone else must not open for the owner."""
    prof_rows = {p: load_group(style, p) for p in ("owner", "stranger", "mimic")}
    matrix = {}
    for trainer in ("owner", "stranger", "mimic"):
        prof = enrol(prof_rows[trainer][:4])
        row = {}
        for subject in ("owner", "stranger", "mimic"):
            rows = prof_rows[subject]
            if trainer == "owner" and subject == "owner":
                rows = rows[4:]
            hits = 0
            scored = 0
            for r in rows:
                s = score(prof, r)
                if s is None:
                    continue
                scored += 1
                if s <= threshold:
                    hits += 1
            row[subject] = {"accepted": hits, "scored": scored}
        matrix[trainer] = row
    return matrix


def pct(a, b):
    return "0/0" if not b else f"{a}/{b} ({100.0 * a / b:.0f}%)"


def main_demo():
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(RESULTS, exist_ok=True)
    made = generate_all()
    lines = []
    add = lines.append

    add("# Marrow prototype — synthetic evaluation")
    add("")
    add(f"Generated {made} new fake sessions (existing ones kept). "
        f"Two input styles, four personas each, 60 s per session.")
    add("")

    summary = {}
    for style in STYLES:
        prof = enrol(load_group(style, "owner")[:4])
        calib = load_group(style, "owner")[4:]
        cal = calibrate(prof, calib)
        with open(os.path.join(RESULTS, f"threshold-{style}.json"), "w", encoding="utf-8") as f:
            json.dump(cal, f, indent=2)
        # threshold is now frozen on disk; evaluation reads it back
        with open(os.path.join(RESULTS, f"threshold-{style}.json"), encoding="utf-8") as f:
            T = json.load(f)["threshold"]
        ev = evaluate(style, T)
        swap = swap_test(style, T)
        drift = drift_test(style, T)
        summary[style] = {"threshold": T, "eval": ev, "swap": swap, "drift": drift}

        add(f"## {style}")
        add("")
        add(f"Profile: {len(prof)} of {len(FEATURES)} features. "
            f"Threshold fixed at **{T}** (worst calibration score "
            f"{cal['worst_calibration_score']}, x1.15).")
        add("")
        add("| group | accepted | mean score |")
        add("|---|---|---|")
        for persona, rows in ev["groups"].items():
            hits = sum(1 for r in rows if r["accept"])
            sc = [r["score"] for r in rows if r["score"] is not None]
            mean_sc = f"{sum(sc) / len(sc):.2f}" if sc else "-"
            add(f"| {persona} | {pct(hits, len(rows))} | {mean_sc} |")
        add("")
        far_num = sum(1 for p in ("stranger", "mimic")
                      for r in ev["groups"][p] if r["accept"])
        far_den = sum(len(ev["groups"][p]) for p in ("stranger", "mimic"))
        frr_num = sum(1 for r in ev["groups"]["owner"] + ev["groups"]["owner_tired"]
                      if not r["accept"])
        frr_den = len(ev["groups"]["owner"]) + len(ev["groups"]["owner_tired"])
        add(f"Strangers and mimics let in: **{pct(far_num, far_den)}**. "
            f"Real user doubted: **{pct(frr_num, frr_den)}**.")
        add("")
        add("Swap test — profile trained on the row, sessions of the column:")
        add("")
        add("| trained on | owner | stranger | mimic |")
        add("|---|---|---|---|")
        for trainer, row in swap.items():
            cells = []
            for subject in ("owner", "stranger", "mimic"):
                d = row[subject]
                cells.append(pct(d["accepted"], d["scored"]))
            add(f"| {trainer} | " + " | ".join(cells) + " |")
        add("")
        add("Drift — the owner gets tired, in order, and a stranger is scored again "
            "after every profile update:")
        add("")
        add("| session | owner score | decision | stranger score after update | stranger refused |")
        add("|---|---|---|---|---|")
        for r in drift:
            add(f"| {r['session']} | {r['score']} | {r['decision']} | "
                f"{r['stranger_score_after']} | {'yes' if r['stranger_refused'] else 'NO'} |")
        add("")

    add("## What this does and does not show")
    add("")
    add("The fake sessions come from a simulator whose parameters were fixed "
        "before the detector was written, and the detector only ever sees the "
        "event stream. That keeps the test honest, but it is still synthetic: "
        "passing here is necessary, not sufficient. Real movement data is not "
        "used and must not be posted; the same commands run on real recordings "
        "with `train` and `score`.")
    add("")

    with open(os.path.join(RESULTS, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    print(f"report written to {os.path.join(RESULTS, 'report.md')}")


def cmd_train(args):
    rows = []
    for name in sorted(os.listdir(args.enroll)):
        if name.endswith(".jsonl"):
            rows.append(extract_features(read_recording(os.path.join(args.enroll, name))))
    if len(rows) < 2:
        raise SystemExit("need at least 2 recordings to enrol")
    prof = enrol(rows)
    calib = calibrate(prof, rows)
    out = {"profile": prof, "threshold": calib["threshold"], "calibration": calib}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"profile from {len(rows)} recordings, {len(prof)} features, "
          f"threshold {calib['threshold']} -> {args.out}")


def cmd_score(args):
    with open(args.profile, encoding="utf-8") as f:
        data = json.load(f)
    prof, T = data["profile"], data["threshold"]
    rows = []
    for name in sorted(os.listdir(args.recordings)):
        if name.endswith(".jsonl"):
            rows.append((name, extract_features(read_recording(os.path.join(args.recordings, name)))))
    if not rows:
        raise SystemExit("no .jsonl recordings found")
    for name, feats in rows:
        s = score(prof, feats)
        if s is None:
            print(f"{name}: not scorable (too few events or features)")
            continue
        print(f"{name}: score {s:.2f} -> {'OPEN' if s <= T else 'ASK PASSWORD'} (threshold {T})")


def main():
    ap = argparse.ArgumentParser(description="Marrow prototype")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gen", help="generate the fake data only")
    t = sub.add_parser("train", help="enrol a profile from a folder of recordings")
    t.add_argument("--enroll", required=True)
    t.add_argument("--out", default="profile.json")
    s = sub.add_parser("score", help="score recordings against a profile")
    s.add_argument("--profile", required=True)
    s.add_argument("--recordings", required=True)
    args = ap.parse_args()

    if args.cmd == "gen":
        os.makedirs(DATA, exist_ok=True)
        print(f"generated {generate_all(force=True)} fake sessions into {DATA}")
    elif args.cmd == "train":
        cmd_train(args)
    elif args.cmd == "score":
        cmd_score(args)
    else:
        main_demo()


if __name__ == "__main__":
    main()
