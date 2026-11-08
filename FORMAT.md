# Recording format

One session per file, UTF-8, one JSON object per line (JSONL). The first line is a
header, the rest are events sorted by `t`.

```
{"v":1,"kind":"session","id":"2026-11-09-a","synthetic":true}
{"t":0,"kind":"move","x":0.41234,"y":0.71902}
{"t":30,"kind":"move","x":0.41401,"y":0.71655}
{"t":640,"kind":"click","x":0.42871,"y":0.70211,"button":"left"}
{"t":880,"kind":"key","source":"typed","text":"h"}
{"t":1120,"kind":"insert","source":"software","text":"hello there"}
{"t":2400,"kind":"delete","source":"software","chars":3}
```

## Fields

| field | type | meaning |
|---|---|---|
| `v` | int | format version, currently `1` |
| `kind` | string | `session`, `move`, `click`, `key`, `insert`, `delete` |
| `t` | int | milliseconds since the start of the session, monotonic |
| `x`, `y` | float | pointer position as a fraction of the screen, `0.0` to `1.0`, origin top-left |
| `button` | string | `left`, `right`, `middle` (clicks only) |
| `source` | string | how the text arrived: `typed`, `onscreen`, or `software` |
| `text` | string | the characters that arrived, for `key` and `insert` |
| `chars` | int | how many characters were removed, for `delete` |

## Rules

- Positions are fractions of the screen, never pixels. A recording made on a 4K
  monitor and one made on a laptop land on the same scale.
- Timestamps are milliseconds. A recorder that only has seconds multiplies by 1000.
- `key` is one character per event. `insert` is a chunk, the way dictation and
  on-screen keyboards deliver text.
- `delete` records the count, not which characters. Corrections matter as a
  pattern; the removed text does not.
- Nothing in the format names the operating system, the device, the window, or
  the capture tool. The detector reads only these fields, so a browser recorder,
  a native hook, and a synthetic generator all produce usable files.

## Redaction

The prototype never reads the content of `text`, only its length. A real
recording can therefore replace every character with the same-length filler
before it leaves the machine:

```
"text": "xxxxxxxxxxx"
```

The rhythm, the chunk sizes, and the correction pattern survive; the words do
not. This matters because a person's writing is as identifying as their
movement, and the bounty's rule is that no real movement data is posted.
