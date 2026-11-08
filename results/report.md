# Marrow prototype — synthetic evaluation

Generated 32 new fake sessions (existing ones kept). Two input styles, four personas each, 60 s per session.

## mouse_keyboard

Profile: 15 of 17 features. Threshold fixed at **2.0123** (worst calibration score 1.7498, x1.15).

| group | accepted | mean score |
|---|---|---|
| owner | 2/2 (100%) | 1.07 |
| owner_tired | 2/3 (67%) | 2.18 |
| stranger | 0/4 (0%) | 2.29 |
| mimic | 0/3 (0%) | 2.04 |

Strangers and mimics let in: **0/7 (0%)**. Real user doubted: **1/5 (20%)**.

Swap test — profile trained on the row, sessions of the column:

| trained on | owner | stranger | mimic |
|---|---|---|---|
| owner | 2/2 (100%) | 0/4 (0%) | 0/3 (0%) |
| stranger | 0/6 (0%) | 4/4 (100%) | 0/3 (0%) |
| mimic | 0/6 (0%) | 0/4 (0%) | 3/3 (100%) |

Drift — the owner gets tired, in order, and a stranger is scored again after every profile update:

| session | owner score | decision | stranger score after update | stranger refused |
|---|---|---|---|---|
| 1 | 1.72 | open | 2.753 | yes |
| 2 | 2.898 | ask password | 3.561 | yes |
| 3 | 2.16 | ask password | 3.277 | yes |

## joystick_dictation

Profile: 16 of 17 features. Threshold fixed at **2.2497** (worst calibration score 1.9563, x1.15).

| group | accepted | mean score |
|---|---|---|
| owner | 2/2 (100%) | 1.29 |
| owner_tired | 1/3 (33%) | 3.32 |
| stranger | 0/4 (0%) | 3.50 |
| mimic | 0/3 (0%) | 2.83 |

Strangers and mimics let in: **0/7 (0%)**. Real user doubted: **2/5 (40%)**.

Swap test — profile trained on the row, sessions of the column:

| trained on | owner | stranger | mimic |
|---|---|---|---|
| owner | 2/2 (100%) | 0/4 (0%) | 0/3 (0%) |
| stranger | 0/6 (0%) | 4/4 (100%) | 0/3 (0%) |
| mimic | 0/6 (0%) | 0/4 (0%) | 3/3 (100%) |

Drift — the owner gets tired, in order, and a stranger is scored again after every profile update:

| session | owner score | decision | stranger score after update | stranger refused |
|---|---|---|---|---|
| 1 | 4.475 | ask password | 4.326 | yes |
| 2 | 3.226 | ask password | 4.183 | yes |
| 3 | 3.092 | ask password | 4.197 | yes |

## What this does and does not show

The fake sessions come from a simulator whose parameters were fixed before the detector was written, and the detector only ever sees the event stream. That keeps the test honest, but it is still synthetic: passing here is necessary, not sufficient. Real movement data is not used and must not be posted; the same commands run on real recordings with `train` and `score`.

