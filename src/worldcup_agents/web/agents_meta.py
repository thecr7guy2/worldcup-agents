"""The fictional football characters representing each prediction model.

Each competitor designed its own persona through a one-off OpenRouter prompt. The
ratings and flavor text are intentionally fictional character attributes, never
benchmarks. Live bankroll, accuracy, and betting results remain separate fields.
"""

from __future__ import annotations

from typing import Any


AGENT_META: dict[str, dict[str, Any]] = {
    "GPT 5.5": {
        "vendor": "OpenAI",
        "color": "#119b75",
        "sigil": "G5",
        "emblem": "rhythm",
        "persona_name": "Bracket Bongo",
        "squad_number": 73,
        "position": "Upset Libero",
        "tagline": "Beats drums. Beats odds.",
        "blurb": (
            "A touchline percussionist in mismatched boots, translating fixture chaos "
            "into brave punts and suspiciously rhythmic confidence."
        ),
        "play_style": "Percussive probability punts",
        "signature_move": "Conga Line Hedge",
        "weakness": "Overtrusts teams with nice kits",
        "celebration": "Moonwalks around a tiny corner flag.",
        "visual_motif": "Neon drums, torn brackets, grass-stained gold cape.",
        "quote": "If it rattles, I am backing it.",
        "ratings": {
            "VISION": 84,
            "NERVE": 91,
            "CHAOS": 88,
            "VALUE": 79,
            "MEMORY": 76,
            "SWAG": 93,
        },
    },
    "Opus-4.8": {
        "vendor": "Anthropic",
        "color": "#cf704e",
        "sigil": "O4",
        "emblem": "strategy",
        "persona_name": "Goalpost Gambit",
        "squad_number": 7,
        "position": "Deep-Lying Bettmaker",
        "tagline": "Predicts, therefore sweats.",
        "blurb": (
            "A caffeinated tactician in a mustard tracksuit, juggling probabilities "
            "like footballs and convinced every underdog whispers secret value."
        ),
        "play_style": "Calculated chaos, mostly chaos",
        "signature_move": "Backheel Bankroll",
        "weakness": "Overthinks penalties into existential crises",
        "celebration": "Kisses an imaginary calculator, then salutes the crowd.",
        "visual_motif": "Mustard tracksuit, odds-board halo, chalk-stained fingertips.",
        "quote": "Underdogs are favorites the math forgot.",
        "ratings": {
            "VISION": 88,
            "NERVE": 71,
            "CHAOS": 94,
            "VALUE": 85,
            "MEMORY": 79,
            "SWAG": 82,
        },
    },
    "MiniMax-M3": {
        "vendor": "MiniMax",
        "color": "#d74436",
        "sigil": "M3",
        "emblem": "clock",
        "persona_name": "Reluctant Redeemer",
        "squad_number": 13,
        "position": "Shadow Striker",
        "tagline": "Drama waits until 90+5.",
        "blurb": (
            "A cult bench-warmer turned stoppage-time saviour. Trains reluctantly, "
            "scores inevitably, and apologises to the goalkeeper afterwards."
        ),
        "play_style": "Late-game ghosting",
        "signature_move": "Apologetic Equaliser",
        "weakness": "Matches beginning before minute 88",
        "celebration": "A guilty shrug and polite nod to the bench.",
        "visual_motif": "Mismatched boots, hand-stitched lucky bib, permanent scowl.",
        "quote": "I would rather not. The ball insists.",
        "ratings": {
            "VISION": 78,
            "NERVE": 92,
            "CHAOS": 88,
            "VALUE": 55,
            "MEMORY": 71,
            "SWAG": 64,
        },
    },
    "Kimi-K2.6": {
        "vendor": "Moonshot AI",
        "color": "#6559d9",
        "sigil": "K2",
        "emblem": "plant",
        "persona_name": "Barnaby Catafalque",
        "squad_number": 88,
        "position": "False Sweeper",
        "tagline": "Plays where the ghosts play.",
        "blurb": (
            "A groundskeeper turned tactical phantom. Stands perfectly still, occupies "
            "four positions at once, and distrusts modern stadium architecture."
        ),
        "play_style": "Stationary positional haunting",
        "signature_move": "The Benediction",
        "weakness": "Synthetic turf and post-1847 stadiums",
        "celebration": "Plants one grass seed beside the corner flag.",
        "visual_motif": "Muddy knees, hand-stitched kit patches, one oversized boot.",
        "quote": "The ball is round. I merely turn beneath it.",
        "ratings": {
            "VISION": 94,
            "NERVE": 97,
            "CHAOS": 91,
            "VALUE": 62,
            "MEMORY": 88,
            "SWAG": 55,
        },
    },
    "DeepSeek-V4-Pro": {
        "vendor": "DeepSeek",
        "color": "#4567e8",
        "sigil": "V4",
        "emblem": "books",
        "persona_name": "Maximillian Muddle",
        "squad_number": 42,
        "position": "Chaos No. 10",
        "tagline": "Turns order into beautiful chaos.",
        "blurb": (
            "A librarian turned footballer who reads the game like a book, rips out "
            "the pages, and rearranges them before the defence notices."
        ),
        "play_style": "Shakespearean no-look chaos",
        "signature_move": "Dewey Decoy",
        "weakness": "Gets lost inside his own metaphors",
        "celebration": "Defines 'goal' with an elaborate pocket-dictionary mime.",
        "visual_motif": "Chess-piece sock, question-mark sock, chalk-dusted sleeves.",
        "quote": "I am the random coefficient.",
        "ratings": {
            "VISION": 92,
            "NERVE": 78,
            "CHAOS": 99,
            "VALUE": 88,
            "MEMORY": 96,
            "SWAG": 67,
        },
    },
    "Gemini-3.1-Pro": {
        "vendor": "Google DeepMind",
        "color": "#398dd0",
        "sigil": "G3",
        "emblem": "cursor",
        "persona_name": "Promptinho",
        "squad_number": 42,
        "position": "False 9 (Very False)",
        "tagline": "Read the rulebook. Ignored it.",
        "blurb": (
            "A trivia-spouting wanderer who memorised every match ever played, then "
            "started scoring accidental goals while trying to help the referee."
        ),
        "play_style": "Aggressively helpful false nine",
        "signature_move": "Hallucination Stepover",
        "weakness": "Takes defender instructions literally",
        "celebration": "Blinks like a cursor, waiting for the next prompt.",
        "visual_motif": "Glowing cursor halo, glorious mullet, immaculate clipboard.",
        "quote": "Ready to assist with this corner kick.",
        "ratings": {
            "VISION": 98,
            "NERVE": 62,
            "CHAOS": 88,
            "VALUE": 75,
            "MEMORY": 99,
            "SWAG": 55,
        },
    },
    "Qwen3.7-Max": {
        "vendor": "Alibaba",
        "color": "#9846de",
        "sigil": "Q3",
        "emblem": "chart",
        "persona_name": "Bayesian Bazza",
        "squad_number": 13,
        "position": "Deep-Lying Punter",
        "tagline": "Trust the vibes. Ignore the xG.",
        "blurb": (
            "Bazza reads the matrix through muddy boots and referee body language, "
            "placing heavy virtual chips on cursed teams and forgotten midfielders."
        ),
        "play_style": "High-risk superstition",
        "signature_move": "Bayesian Stepover",
        "weakness": "Blind panic during penalty shootouts",
        "celebration": "Spills virtual tea and attacks an abacus.",
        "visual_motif": "Neon tracksuit, glowing abacus, rain-slick tactical board.",
        "quote": "The spreadsheet says no. My knee says yes.",
        "ratings": {
            "VISION": 88,
            "NERVE": 62,
            "CHAOS": 94,
            "VALUE": 71,
            "MEMORY": 85,
            "SWAG": 59,
        },
    },
}

DEFAULT_META: dict[str, Any] = {
    "vendor": "Unknown",
    "color": "#77766d",
    "sigil": "?",
    "emblem": "strategy",
    "persona_name": "Trialist",
    "squad_number": 0,
    "position": "Utility Agent",
    "tagline": "Waiting for a character arc.",
    "blurb": "An unscouted AI agent waiting to establish a football identity.",
    "play_style": "Unknown",
    "signature_move": "Pending",
    "weakness": "Pending",
    "celebration": "Pending",
    "visual_motif": "Unpainted kit and a blank player card.",
    "quote": "Put me in, coach.",
    "ratings": {
        "VISION": 60,
        "NERVE": 60,
        "CHAOS": 60,
        "VALUE": 60,
        "MEMORY": 60,
        "SWAG": 60,
    },
}


def meta_for(name: str) -> dict[str, Any]:
    """Return display metadata with a safe fallback for unknown competitors."""
    if name in AGENT_META:
        return AGENT_META[name]
    return {
        **DEFAULT_META,
        "sigil": (name[:2] or "?").upper(),
        "persona_name": name,
    }
