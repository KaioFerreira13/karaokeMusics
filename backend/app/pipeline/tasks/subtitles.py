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
    font_size: int = 68  # tamanho otimizado para caber versos completos sem cortar
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
    max_lines_page: int = 2  # máximo de versos por tela (bloco)
    tail: float = 0.5  # tempo de permanência da tela após cantar a última palavra
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
            is_verse = bool(item.get("is_verse_start", False))
        except (KeyError, TypeError, ValueError):
            continue
        if word and end >= start >= 0:
            entry = {"start": start, "end": end, "word": word}
            if is_verse:
                entry["is_verse_start"] = True
            words.append(entry)
    words.sort(key=lambda w: (w["start"], w["end"]))
    return words


def split_into_verses(words: list[dict]) -> list[list[dict]]:
    """Divide palavras em versos exatos da canção.
    
    Regras estritas:
    - 2 versos NUNCA podem ficar na mesma linha.
    - O mesmo verso NUNCA pode ser quebrado entre 2 telas.
    """
    verses: list[list[dict]] = []
    cur_verse: list[dict] = []
    
    FUNCTION_WORDS = {"não", "de", "do", "da", "em", "por", "com", "sem", "e", "ou", "mas", "se"}

    for w in words:
        if cur_verse:
            prev = cur_verse[-1]
            gap = round(w["start"] - prev["end"], 2)
            prev_word = prev["word"].strip()
            curr_word = w["word"].strip()
            clean_curr = re.sub(r"^\W+", "", curr_word).lower()
            
            is_explicit = w.get("is_verse_start", False)
            has_terminal_punct = bool(re.search(r"[.!?…]$", prev_word)) and len(cur_verse) >= 3
            is_cap = curr_word[0].isupper() if curr_word else False
            
            can_break = len(cur_verse) >= 3 or has_terminal_punct or is_explicit
            
            should_break = False
            if can_break:
                if is_explicit or has_terminal_punct:
                    should_break = True
                elif gap >= 1.0:  # Pausa respiratória ou instrumental longa entre versos
                    should_break = True
                elif is_cap and clean_curr in FUNCTION_WORDS:
                    # Conectivos em maiúscula só quebram se houver pausa real ou vírgula anterior
                    if gap >= 0.5 or prev_word.endswith(","):
                        should_break = True
                elif is_cap and len(cur_verse) >= 5:  # Palavra em maiúscula após verso substancial
                    should_break = True
                elif is_cap and (gap >= 0.25 or prev_word.endswith(",")):
                    should_break = True
                elif gap >= 0.75 and len(cur_verse) >= 6:
                    should_break = True

            if should_break:
                verses.append(cur_verse)
                cur_verse = []
                
        cur_verse.append(w)
        
    if cur_verse:
        verses.append(cur_verse)
        
    return verses


def group_into_pages(verses: list[list[dict]], max_verses_per_page: int = 2) -> list[list[list[dict]]]:
    """Agrupa versos inteiros em telas (páginas).
    
    Garante que nenhum verso seja dividido entre telas diferentes.
    """
    pages: list[list[list[dict]]] = []
    cur_page: list[list[dict]] = []
    
    for v in verses:
        v_chars = sum(len(w["word"]) for w in v) + len(v) - 1
        is_long = v_chars > 55
        
        if cur_page:
            gap = v[0]["start"] - cur_page[-1][-1]["end"]
            prev_chars = sum(len(w["word"]) for w in cur_page[-1]) + len(cur_page[-1]) - 1
            prev_is_long = prev_chars > 55
            
            # Quebra de tela se atingiu o máximo de versos, pausa instrumental > 2.5s, ou verso muito longo
            if len(cur_page) >= max_verses_per_page or gap > 2.5 or prev_is_long or is_long:
                pages.append(cur_page)
                cur_page = []
                
        cur_page.append(v)
        
    if cur_page:
        pages.append(cur_page)
        
    return pages


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

    verses = split_into_verses(words)
    pages = group_into_pages(verses, max_verses_per_page=opts.max_lines_page)
    cx, cy = style.res_x // 2, style.lyrics_center_y
    prev_end = 0.0
    
    for i, page in enumerate(pages):
        first_word = page[0][0]
        last_word = page[-1][-1]
        
        start = prev_end
        
        # Determinar o fim da página
        end = last_word["end"] + opts.tail
        if i + 1 < len(pages):
            next_start = pages[i + 1][0][0]["start"]
            # Se a próxima página está muito perto, emenda direto
            if next_start - end < 1.0:
                end = next_start
        
        end = max(end, start + 0.1)
        
        # Se demora muito para começar, avança o start para limpar a tela durante pausas longas
        if first_word["start"] - start > 2.5:
            start = max(prev_end, first_word["start"] - 2.5)
            
        prev_end = end
        
        # Construir o texto da página (múltiplas linhas com delays cumulativos)
        text_parts = []
        cursor = 0
        
        for r, line in enumerate(page):
            line_parts = []
            for w, word in enumerate(line):
                start_cs = max(cursor, round((word["start"] - start) * 100))
                end_cs = max(start_cs, round((word["end"] - start) * 100))
                
                gap = start_cs - cursor
                if gap > 0:
                    line_parts.append(f"{{\\k{gap}}}")
                
                dur = end_cs - start_cs
                tag = "kf" if opts.mode == "kf" else "k"
                suffix = " " if w < len(line) - 1 else ""
                
                line_parts.append(f"{{\\{tag}{dur}}}{_escape(word['word'])}{suffix}")
                cursor = end_cs
            text_parts.append("".join(line_parts))
        
        text = "\\N".join(text_parts)
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
    opts = LayoutOptions(mode=a.mode)
    print(generate_karaoke_ass(a.input, a.output, style, opts))


if __name__ == "__main__":
    main()
