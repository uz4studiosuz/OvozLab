"""Subtitr: so'z vaqtlaridan qisqa, o'qishga qulay qatorlar (SRT / WebVTT).

Standart (Netflix/CapCut uslubi): bir qatorda <= 42 belgi, bir subtitrda <= 2 qator, <= 6 soniya.
"""

from __future__ import annotations

from dataclasses import dataclass

SENTENCE_END = (".", "!", "?", "…")
CLAUSE_END = (",", ";", ":", "—", "-")


@dataclass(frozen=True)
class CueRules:
    max_chars: int = 42      # bir qatordagi belgilar
    max_lines: int = 2
    max_dur: float = 6.0     # soniya
    min_dur: float = 0.8
    gap_split: float = 0.6   # so'zlar orasidagi shuncha jimlikda yangi subtitr boshlanadi


def estimate_words(text: str, start: float, end: float) -> list[dict]:
    """So'z vaqtlari yo'q bo'lsa: bo'lak vaqtini so'zlarga uzunligiga qarab taqsimlaymiz."""
    words = text.split()
    if not words:
        return []
    total = sum(len(w) + 1 for w in words)
    span = max(end - start, 0.01)
    out, t = [], start
    for w in words:
        d = span * (len(w) + 1) / total
        out.append({"word": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def _wrap(text: str, max_chars: int, max_lines: int) -> list[str]:
    """Matnni qatorlarga bo'ladi; 2 qator bo'lsa, uzunliklari teng bo'ladigan joydan."""
    if len(text) <= max_chars or max_lines == 1:
        return [text]
    words = text.split()
    best, best_score = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        over = max(len(a) - max_chars, 0) + max(len(b) - max_chars, 0)
        score = (over, abs(len(a) - len(b)) - (4 if a.endswith(CLAUSE_END + SENTENCE_END) else 0))
        if best_score is None or score < best_score:
            best, best_score = [a, b], score
    return best or [text]


def build_cues(words: list[dict], rules: CueRules = CueRules()) -> list[dict]:
    """[{word, start, end}] -> [{start, end, text, lines}]."""
    limit = rules.max_chars * rules.max_lines
    cues: list[dict] = []
    cur: list[dict] = []

    def flush():
        if not cur:
            return
        text = " ".join(w["word"] for w in cur)
        cues.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": text,
                     "lines": _wrap(text, rules.max_chars, rules.max_lines)})
        cur.clear()

    for w in words:
        if not w["word"]:
            continue
        if cur:
            prev = cur[-1]
            text_len = sum(len(x["word"]) + 1 for x in cur) + len(w["word"])
            cur_len = text_len - len(w["word"]) - 1
            if (
                text_len > limit
                or w["end"] - cur[0]["start"] > rules.max_dur
                or w["start"] - prev["end"] > rules.gap_split
                or (prev["word"].endswith(SENTENCE_END) and cur_len >= 12)
                or (prev["word"].endswith(CLAUSE_END) and cur_len >= rules.max_chars)
            ):
                flush()
        cur.append(w)
    flush()

    # Juda qisqa subtitrlarni cho'zamiz (keyingisiga tegmasdan), ustma-ust tushishni yo'qotamiz.
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else None
        if c["end"] - c["start"] < rules.min_dur:
            c["end"] = c["start"] + rules.min_dur
        if nxt is not None and c["end"] > nxt:
            c["end"] = max(nxt, c["start"] + 0.05)
        c["start"], c["end"] = round(c["start"], 3), round(c["end"], 3)
    return cues


def _ts(seconds: float, sep: str) -> str:
    ms = max(int(round(seconds * 1000)), 0)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[dict]) -> str:
    return "\n".join(
        f"{i}\n{_ts(c['start'], ',')} --> {_ts(c['end'], ',')}\n" + "\n".join(c["lines"]) + "\n"
        for i, c in enumerate(cues, 1)
    )


def to_vtt(cues: list[dict]) -> str:
    body = "\n".join(
        f"{_ts(c['start'], '.')} --> {_ts(c['end'], '.')}\n" + "\n".join(c["lines"]) + "\n" for c in cues
    )
    return "WEBVTT\n\n" + body
