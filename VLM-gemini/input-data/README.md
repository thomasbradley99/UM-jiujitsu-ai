# JJ MVP Dataset — Videos + Submission Ground Truth

Minimal dataset for a submissions-only Jiu-Jitsu evaluation MVP.

One folder per game. Each game has the raw video and a structured `subs.json`
listing every completed submission with timestamp, technique, and which
fighter submitted which.

## Layout

```
input-data/
├── README.md                    this file
└── <game>/
    ├── video.mov                raw match footage
    └── subs.json                ground-truth submissions
```

## `subs.json` schema

Fighters are keyed by a **visual descriptor** (e.g. `BALD`, `STRIPED`) — the
single thing the AI pipeline can also see. There's deliberately no real-name
layer; the AI doesn't see names, and we don't (yet) need cross-game person
tracking. If/when we do, that lives in a separate `persons.json`.

```jsonc
{
  "video": "ryan-thomas",
  "video_file": "video.mov",
  "duration_sec": 370,
  "description": "free text",

  "fighters": {
    "<DESCRIPTOR>": {
      "visual": "human-readable description of what makes them visually distinctive"
    }
  },

  "submissions": [
    {
      "timestamp": 68,                  // seconds from start
      "technique": "armbar",            // canonical token, see vocabulary below
      "submitter": "<DESCRIPTOR>",      // key into fighters
      "submittee": "<DESCRIPTOR>",
      "notes": "free text, optional"
    }
  ]
}
```

### Descriptor conventions

- **All caps**, ≤2 tokens (`BALD`, `STRIPED`, `BLUE_GI`, `BLACK_RASH`).
- Pick the most stable visual feature: clothing > hair > body type.
- The eval matches the AI's free-text output (e.g. `"BALD RASHGUARD"`,
  `"STRIPED FIGHTER"`) to these keys via token overlap, so a single
  distinctive token (`BALD`) is enough — you don't need to anticipate
  exactly what the AI will say.

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

## Games included

| Game | Duration | Submissions | Status |
|---|---|---:|---|
| ryan-thomas | 6m10s | 5 | ✅ included |
| chris-instructor | 5m40s | 4 | TODO |
| columba | 5m13s | 1 | TODO |
| gio-thomas | 1m56s | 1 | TODO |

Note: `video.mov` is currently a symlink back to `jj/jj-ai/games/<game>/input/video.mov`.
Replace with a real copy before shipping the dataset off this machine.
