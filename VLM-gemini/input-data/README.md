# JJ MVP Dataset — Videos + Submission Ground Truth

Minimal dataset for a submissions-only Jiu-Jitsu evaluation MVP.

One folder per game. Each game has the raw video and a structured `subs.json` listing every completed submission with timestamp, technique, and which fighter submitted which.

## Layout

```
jj-mvp-data/
├── README.md                    this file
└── <game>/
    ├── video.mov                raw match footage
    └── subs.json                ground-truth submissions
```

## `subs.json` schema

```jsonc
{
  "video": "ryan-thomas",
  "video_file": "video.mov",
  "duration_sec": 370,
  "description": "free text",

  "fighters": {
    "<name>": {
      "role": "submitter | submittee | mixed",
      "visual": "human-readable description",
      "ai_descriptor": "what the AI calls them, e.g. BALD FIGHTER",
      "rich_gt_descriptor": "what the rich GT calls them, e.g. BLACK RASHGUARD"
    }
  },

  "submissions": [
    {
      "timestamp": 68,                  // seconds from start
      "technique": "armbar",            // canonical: armbar | rnc | triangle | americana | guillotine | omoplata | kimura | smother | other
      "submitter": "ryan",              // key into fighters
      "submittee": "thomas",            // key into fighters
      "notes": "1:08 - Ryan armbars Thomas"
    }
  ]
}
```

## Canonical technique vocabulary

| Token | Long form |
|---|---|
| `armbar` | Armbar |
| `rnc` | Rear-naked choke |
| `triangle` | Triangle choke |
| `arm_triangle` | Arm-triangle / kata-gatame |
| `americana` | Americana / keylock |
| `kimura` | Kimura |
| `guillotine` | Guillotine |
| `omoplata` | Omoplata (and omoplata-strangle) |
| `smother` | Smother choke |
| `other` | Anything not in the list above |

## Why two descriptors per fighter

Real names (Ryan, Thomas) are useful for humans but the AI pipeline can't see them — it only sees what's visually distinctive. So each fighter has both:
- `ai_descriptor` — what the v3-fast pipeline auto-labels them as (e.g. `"BALD FIGHTER"`).
- `rich_gt_descriptor` — what the manual rich GT labels them as (e.g. `"BLACK RASHGUARD"`).

This lets the eval script compare "Ryan submits Thomas" (from `subs.json`) ↔ "BLACK RASHGUARD submits GREEN STRIPE" (rich GT) ↔ "BALD FIGHTER submits STRIPED FIGHTER" (AI output) without ambiguity.

## Games included

| Game | Duration | Submissions | Status |
|---|---|---:|---|
| ryan-thomas | 6m10s | 5 | ✅ included |
| chris-instructor | 5m40s | 4 | TODO |
| columba | 5m13s | 1 | TODO |
| gio-thomas | 1m56s | 1 | TODO |

Note: `video.mov` is currently a symlink back to `jj/jj-ai/games/<game>/input/video.mov`. Replace with a real copy before shipping the dataset off this machine.
