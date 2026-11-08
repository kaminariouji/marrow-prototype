# Marrow prototype

Decides whether the person at the computer is the enrolled user, using the input
events an operating system already sees: pointer movement, clicks, and text as it
arrives from a keyboard, an on-screen keyboard, or dictation, including the
pattern of corrections.

No audio, no camera, no assumption about the pointing device. A lip joystick and
a mouse go through the same code.

## Run it

```
python3 marrow.py
```

Standard library only, Python 3.8+. No install, no network, no data download.
From an empty copy the command generates the fake data, enrols a profile, fixes a
threshold, evaluates it, runs the swap test, and writes `results/report.md`.

Other commands:

```
python3 marrow.py gen                                   # regenerate the fake data
python3 marrow.py train --enroll <dir> --out profile.json
python3 marrow.py score --profile profile.json --recordings <dir>
```

`train` and `score` work on any recording that follows [FORMAT.md](FORMAT.md), so
the same code runs on real sessions without touching the synthetic set.

## What it measures

Fifteen to seventeen session features, all of them ratios, rates, or durations,
so nothing depends on screen size or device:

- pointer: median speed, 90th percentile speed, hover before a click, gap between
  clicks, path straightness, heading change per screen fraction travelled, tremor
  as a ratio of step length, pause fraction, speed variability, move rate
- text: median interval between arrivals, characters per arrival, interval
  irregularity, delete-to-insert ratio, correction lag, correction lag relative to
  the arrival interval, characters per minute

The profile is a median and a scaled median absolute deviation per feature, taken
from four of the owner's sessions. Features are compared in log space with a 25%
tolerance floor, because a person's own sessions differ by more than a few percent
and treating that spread as signal would make the profile fragile.

Shape features (straightness, heading change, tremor, rhythm irregularity,
correction lag) carry twice the weight of magnitude features (speed, hover,
intervals). Fatigue moves the magnitudes; an impostor usually gets the shape
wrong.

## Results on the fake data

Both styles, threshold fixed before any test session was scored. Threshold is
1.15x the worst score on the owner's calibration sessions, written to
`results/threshold-<style>.json`, then read back for evaluation.

**mouse + keyboard** — threshold 2.0123

| group | accepted | mean score |
|---|---|---|
| owner | 2/2 (100%) | 1.07 |
| owner, tired | 2/3 (67%) | 2.18 |
| stranger | 0/4 (0%) | 2.29 |
| mimic | 0/3 (0%) | 2.04 |

Strangers and mimics let in: 0/7 (0%). Real user doubted: 1/5 (20%).

**lip joystick + dictation** — threshold 2.2497

| group | accepted | mean score |
|---|---|---|
| owner | 2/2 (100%) | 1.29 |
| owner, tired | 1/3 (33%) | 3.32 |
| stranger | 0/4 (0%) | 3.50 |
| mimic | 0/3 (0%) | 2.83 |

Strangers and mimics let in: 0/7 (0%). Real user doubted: 2/5 (40%).

## Swap test

Profile trained on the row, sessions of the column, same thresholds.

| trained on | owner | stranger | mimic |
|---|---|---|---|
| owner | 2/2 (100%) | 0/4 (0%) | 0/3 (0%) |
| stranger | 0/6 (0%) | 4/4 (100%) | 0/3 |
| mimic | 0/6 (0%) | 0/4 (0%) | 3/3 (100%) |

A profile trained on someone else does not open for the owner, in either style,
on any of the six owner sessions it is shown.

## Drift

A session inside the threshold opens and nudges the profile by 20%. A session
outside it asks for the master password, and only after that does it teach the
profile, at 50%. After every update a stranger session is scored again.

| style | session | owner score | decision | stranger after update |
|---|---|---|---|---|
| mouse + keyboard | 1 | 1.72 | open | 2.75, refused |
| mouse + keyboard | 2 | 2.90 | ask password | 3.56, refused |
| mouse + keyboard | 3 | 2.16 | ask password | 3.28, refused |
| lip joystick | 1 | 4.48 | ask password | 4.33, refused |
| lip joystick | 2 | 3.23 | ask password | 4.18, refused |
| lip joystick | 3 | 3.09 | ask password | 4.20, refused |

The fake fatigue is a large, abrupt change, so the prototype keeps asking for the
password through it. What the update guarantees is the other direction: no
stranger was let in after any update. A drift that arrives over weeks, which is
what happens to a body, is what the 20% nudge is for.

## Limits

- The fake data comes from a simulator, not from a person. Passing here is
  necessary, not sufficient. The simulator's parameters were fixed before the
  detector was written and the detector only ever sees the event stream, which
  keeps the comparison honest, but no number above is a claim about real users.
- Four enrolment sessions is thin. A real deployment would enrol across several
  days and re-check the profile against the password every so often.
- The feature set is small enough to read in one sitting. It is a prototype of the
  method, not a hardened product.
- The threshold is per profile and computed only from that person's own sessions.
  It is never fitted to strangers or mimics.

## Files

```
marrow.py              the method, the simulator, the evaluation, the CLI
FORMAT.md              recording format, units, redaction
results/report.md      generated on every run
results/threshold-*.json  the frozen threshold and its calibration scores
data/<style>/<persona>/*.jsonl  fake sessions, four personas per style
```

The fake set has two styles and, for each, an owner, a tired owner, a stranger,
and a mimic who copies the owner's coarse habits but not the fine ones.
