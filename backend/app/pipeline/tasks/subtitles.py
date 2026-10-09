"""Gera legenda karaokê (.ass) a partir do JSON de palavras (start/end/word).

Uso isolado (CLI):
    python -m app.pipeline.tasks.subtitles words.json [-o karaoke.ass]
        [--max-words 7] [--font Arial] [--font-size 72] [--mode kf|k]

Convenção ASS: o texto de uma linha com \\k/\\kf começa na cor SECUNDÁRIA e é
preenchido com a PRIMÁRIA no instante em que a sílaba/palavra é cantada.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


class SubtitleError(Exception):
    pass


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (formato do ASS; alpha 0 = opaco)."""
    h = hex_rgb.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Cor inválida: {hex_rgb}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


@dataclass
class KaraokeStyle:
    font: str = "Arial"  # use "Montserrat" se estiver instalada
    font_size: int = 76
    fill_color: str = "#D8FF2E"  # verde-limão: cor "cantada" (PrimaryColour)
    base_color: str = "#FFFFFF"  # branco: cor "ainda não cantada" (SecondaryColour)
    outline_color: str = "#000000"
    shadow_color: str = "#000000"
    outline: float = 4.0
    shadow: float = 2.0
    margin_v: int = 90
    margin_h: int = 80
    res_x: int = 1920
    res_y: int = 1080
    # Bloco da letra (centro) e título (pílula no topo), em coordenadas de 1920x1080
    lyrics_center_y: int = 575
    row_max_chars: int = 34  # acima disso o verso quebra em 2 linhas
    title_color: str = "#8FE9FF"
    title_size: int = 54
    pill_x: int = 510
    pill_y: int = 75
    pill_w: int = 900
    pill_h: int = 100


@dataclass
class LayoutOptions:
    max_words: int = 10  # um verso = uma linha da letra (até 2 linhas na tela)
    max_chars: int = 60
    max_gap: float = 1.2  # pausa maior que isso quebra o verso
    lead_in: float = 0.4  # (mantido por compatibilidade)
    tail: float = 0.4  # o verso permanece depois da última palavra
    mode: str = "kf"  # "kf" (preenchimento suave) ou "k" (troca instantânea)


# ----------------------------------------------------------------------------
def load_words(path: str | Path) -> list[dict]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubtitleError(f"Não foi possível ler {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise SubtitleError("O JSON deve ser uma lista de {start, end, word}.")

    words = []
    for item in raw:
        try:
            word = str(item["word"]).strip()
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if word and end >= start >= 0:
            words.append({"start": start, "end": end, "word": word})
    words.sort(key=lambda w: (w["start"], w["end"]))
    return words


def group_words(words: list[dict], opts: LayoutOptions) -> list[list[dict]]:
    """Agrupa palavras em linhas confortáveis de ler."""
    lines: list[list[dict]] = []
    cur: list[dict] = []
    chars = 0
    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            prev = cur[-1]["word"]
            too_long = len(cur) >= opts.max_words or chars + 1 + len(w["word"]) > opts.max_chars
            sentence_end = bool(re.search(r"[.!?…]$", prev)) and len(cur) >= 3
            clause_end = bool(re.search(r"[,;:]$", prev)) and len(cur) >= max(4, opts.max_words - 2)
            if gap > opts.max_gap or too_long or sentence_end or clause_end:
                lines.append(cur)
                cur, chars = [], 0
        cur.append(w)
        chars += len(w["word"]) + (1 if chars else 0)
    if cur:
        lines.append(cur)
    return lines


def _fmt_time(t: float) -> str:
    cs = max(0, round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _escape(text: str) -> str:
    """Remove caracteres que o ASS interpretaria como override/linha."""
    text = text.replace("\\", "").replace("{", "(").replace("}", ")")
    return re.sub(r"[\r\n]+", " ", text)


def _split_rows(words: list[str], max_chars: int) -> int | None:
    """Índice da última palavra da 1ª linha para quebrar o verso em 2 linhas equilibradas."""
    if len(words) < 2 or len(" ".join(words)) <= max_chars:
        return None
    best, best_diff = None, None
    for i in range(len(words) - 1):
        diff = abs(len(" ".join(words[: i + 1])) - len(" ".join(words[i + 1 :])))
        if best_diff is None or diff < best_diff:
            best, best_diff = i, diff
    return best


def _line_text(line: list[dict], line_start: float, mode: str, break_after: int | None = None) -> str:
    """Monta {\\kfN}palavra ... com tempos acumulados sem drift de arredondamento."""
    tag = "kf" if mode == "kf" else "k"
    parts: list[str] = []
    cursor = 0  # centissegundos já consumidos desde line_start
    for i, w in enumerate(line):
        start_cs = max(cursor, round((w["start"] - line_start) * 100))
        end_cs = max(start_cs, round((w["end"] - line_start) * 100))
        gap = start_cs - cursor
        if gap > 0:  # silêncio antes da palavra (inclui o lead-in)
            parts.append(f"{{\\k{gap}}}")
        dur = end_cs - start_cs
        if i == len(line) - 1:
            suffix = ""
        else:
            suffix = "\\N" if i == break_after else " "
        parts.append(f"{{\\{tag}{dur}}}{_escape(w['word'])}{suffix}")
        cursor = end_cs
    return "".join(parts)


def _static_text(line: list[dict], break_after: int | None) -> str:
    out = []
    for i, w in enumerate(line):
        out.append(_escape(w["word"]))
        if i < len(line) - 1:
            out.append("\\N" if i == break_after else " ")
    return "".join(out)


def _pill_events(style: KaraokeStyle, title: str, artist: str | None) -> list[str]:
    """Pílula neon no topo com "Título - Artista" (vetor ASS + texto)."""
    w, h, r = style.pill_w, style.pill_h, style.pill_h // 2
    shape = (
        f"m {r} 0 l {w - r} 0 b {w - r // 2} 0 {w} {r // 2} {w} {r} "
        f"b {w} {h - r // 2} {w - r // 2} {h} {w - r} {h} l {r} {h} "
        f"b {r // 2} {h} 0 {h - r // 2} 0 {r} b 0 {r // 2} {r // 2} 0 {r} 0"
    )
    edge = ass_color("#7FE3FF")
    end = "9:59:59.99"
    label = f"{title} - {artist}" if artist else title
    if len(label) > 70:
        label = label[:67].rstrip() + "..."
    size = max(30, min(style.title_size, int(style.pill_w * 0.88 / (0.52 * max(len(label), 1)))))
    cx, cy = style.pill_x + w // 2, style.pill_y + h // 2
    return [
        f"Dialogue: 0,0:00:00.00,{end},Title,,0,0,0,,"
        f"{{\\an7\\pos({style.pill_x},{style.pill_y})\\p1\\bord4\\3c{edge}\\1c&H201008&\\1a&H60&\\shad0\\blur3}}{shape}{{\\p0}}",
        f"Dialogue: 1,0:00:00.00,{end},Title,,0,0,0,,"
        f"{{\\an5\\pos({cx},{cy})\\fs{size}\\1c{ass_color(style.title_color)}\\bord2\\3c{edge}\\blur1}}{_escape(label)}",
    ]


def build_ass(
    words: list[dict],
    style: KaraokeStyle | None = None,
    opts: LayoutOptions | None = None,
    title: str | None = None,
    artist: str | None = None,
) -> str:
    style = style or KaraokeStyle()
    opts = opts or LayoutOptions()
    if opts.mode not in ("k", "kf"):
        raise SubtitleError("mode deve ser 'k' ou 'kf'.")

    header = f"""[Script Info]
Title: Karaoke
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: {style.res_x}
PlayResY: {style.res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{style.font},{style.font_size},{ass_color(style.fill_color)},{ass_color(style.base_color)},{ass_color(style.outline_color)},{ass_color(style.shadow_color, 96)},-1,0,0,0,100,100,0,0,1,{style.outline:g},{style.shadow:g},5,{style.margin_h},{style.margin_h},{style.margin_v},1
Style: Title,{style.font},{style.title_size},{ass_color(style.title_color)},{ass_color(style.title_color)},{ass_color(style.outline_color)},{ass_color(style.shadow_color, 96)},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    if title:
        events += _pill_events(style, title, artist)

    # Cada verso aparece em destaque (karaokê: branco -> verde-limão) com o próximo verso
    # em branco logo abaixo. O verso fica na tela desde o fim do anterior até o fim da sua
    # última palavra (a pausa instrumental serve de pré-visualização).
    lines = group_words(words, opts)
    cx, cy = style.res_x // 2, style.lyrics_center_y
    white = ass_color(style.base_color)
    prev_end = 0.0
    for i, line in enumerate(lines):
        first, last = line[0]["start"], line[-1]["end"]
        start = prev_end
        end = last + (opts.tail if i + 1 == len(lines) else 0.0)
        if i + 1 < len(lines):
            end = max(last, min(last + opts.tail, lines[i + 1][0]["start"]))
        end = max(end, start + 0.1)
        prev_end = end

        brk = _split_rows([w["word"] for w in line], style.row_max_chars)
        text = _line_text(line, start, opts.mode, brk)
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            nbrk = _split_rows([w["word"] for w in nxt], style.row_max_chars)
            text += f"\\N{{\\1c{white}}}{_static_text(nxt, nbrk)}"
        events.append(
            f"Dialogue: 2,{_fmt_time(start)},{_fmt_time(end)},Karaoke,,0,0,0,,{{\\an5\\pos({cx},{cy})}}{text}"
        )
    return header + "\n".join(events) + "\n"


def generate_karaoke_ass(
    words_json: str | Path,
    output_path: str | Path | None = None,
    style: KaraokeStyle | None = None,
    opts: LayoutOptions | None = None,
    title: str | None = None,
    artist: str | None = None,
) -> Path:
    """Lê o JSON de palavras e salva karaoke.ass (por padrão ao lado do JSON)."""
    words = load_words(words_json)
    if not words:
        raise SubtitleError("Nenhuma palavra válida no JSON.")
    out = Path(output_path) if output_path else Path(words_json).parent / "karaoke.ass"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_ass(words, style, opts, title, artist), encoding="utf-8")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Gera karaoke.ass a partir de words.json.")
    p.add_argument("input", help="words.json (start/end/word)")
    p.add_argument("-o", "--output", help="Arquivo de saída (padrão: karaoke.ass ao lado do JSON)")
    p.add_argument("--max-words", type=int, default=7)
    p.add_argument("--font", default="Arial")
    p.add_argument("--font-size", type=int, default=72)
    p.add_argument("--fill", default="#00E5FF", help="Cor após cantar (#RRGGBB)")
    p.add_argument("--base", default="#D9D9D9", help="Cor antes de cantar (#RRGGBB)")
    p.add_argument("--mode", choices=["k", "kf"], default="kf")
    a = p.parse_args()

    style = KaraokeStyle(font=a.font, font_size=a.font_size, fill_color=a.fill, base_color=a.base)
    opts = LayoutOptions(max_words=a.max_words, mode=a.mode)
    print(generate_karaoke_ass(a.input, a.output, style, opts))


if __name__ == "__main__":
    main()
