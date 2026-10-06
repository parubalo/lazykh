"""Create the Gentle-style alignment JSON required by scheduler.py.

Whisper supplies word-level timestamps. CMU pronunciations are distributed
across each word duration so the legacy mouth renderer can run without Gentle.
"""

import argparse
import json
import re
from difflib import SequenceMatcher

import pronouncing
import whisper
from whisper.audio import SAMPLE_RATE

from utils import removeTags


PHONE_MAP = {
    "AA": "aa", "AE": "ae", "AH": "ah", "AO": "ao", "AW": "aw",
    "AY": "ay", "B": "b", "CH": "ch", "D": "d", "DH": "dh",
    "EH": "eh", "ER": "er", "EY": "ey", "F": "f", "G": "g",
    "HH": "hh", "IH": "ih", "IY": "iy", "JH": "jh", "K": "k",
    "L": "l", "M": "m", "N": "n", "NG": "ng", "OW": "ow",
    "OY": "oy", "P": "p", "R": "r", "S": "s", "SH": "sh",
    "T": "t", "TH": "th", "UH": "uh", "UW": "uw", "V": "v",
    "W": "w", "Y": "y", "Z": "z", "ZH": "zh",
    "AX": "ah", "AXR": "er", "DX": "d", "EL": "l", "EM": "m",
    "EN": "n", "NX": "n", "Q": "t",
}


def normalise(word):
    return re.sub(r"[^a-z]", "", word.lower())


def script_words(script):
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", removeTags(script))


def whisper_words(result):
    words = []
    for segment in result["segments"]:
        for word in segment.get("words", []):
            text = normalise(word["word"])
            if text:
                words.append((text, float(word["start"]), float(word["end"])))
    return words


def substitution_cost(expected, heard):
    if expected == heard:
        return 0.0
    if SequenceMatcher(None, expected, heard).ratio() >= 0.72:
        return 0.35
    return 2.1


def matched_timestamps(expected, heard):
    """Match the annotated script against Whisper's transcript with edit distance."""
    rows = len(expected) + 1
    columns = len(heard) + 1
    costs = [[0.0] * columns for _ in range(rows)]
    moves = [[None] * columns for _ in range(rows)]
    for i in range(1, rows):
        costs[i][0] = i
        moves[i][0] = "delete"
    for j in range(1, columns):
        costs[0][j] = j
        moves[0][j] = "insert"
    for i in range(1, rows):
        for j in range(1, columns):
            options = [
                (costs[i - 1][j] + 1, "delete"),
                (costs[i][j - 1] + 1, "insert"),
                (costs[i - 1][j - 1] + substitution_cost(expected[i - 1], heard[j - 1][0]), "match"),
            ]
            costs[i][j], moves[i][j] = min(options, key=lambda option: option[0])

    anchors = {}
    i, j = len(expected), len(heard)
    while i or j:
        move = moves[i][j]
        if move == "match":
            if substitution_cost(expected[i - 1], heard[j - 1][0]) < 1:
                anchors[i - 1] = heard[j - 1][1:]
            i -= 1
            j -= 1
        elif move == "delete":
            i -= 1
        else:
            j -= 1
    return anchors


def fill_missing_timestamps(words, anchors, duration):
    """Interpolate unmatched annotated words between reliable Whisper anchors."""
    timestamps = [None] * len(words)
    for index, timestamp in anchors.items():
        timestamps[index] = timestamp

    known = sorted(anchors)
    boundaries = [(-1, (0.0, 0.0))] + [(index, anchors[index]) for index in known] + [(len(words), (duration, duration))]
    for (left_index, left_time), (right_index, right_time) in zip(boundaries, boundaries[1:]):
        gap = right_index - left_index - 1
        if not gap:
            continue
        start = left_time[1]
        end = right_time[0]
        if end <= start:
            end = start + gap * 0.12
        for offset in range(gap):
            word_start = start + (end - start) * offset / gap
            word_end = start + (end - start) * (offset + 1) / gap
            timestamps[left_index + offset + 1] = (word_start, word_end)
    return timestamps


def phones_for(word, duration):
    pronunciations = pronouncing.phones_for_word(word.lower())
    raw_phones = pronunciations[0].split() if pronunciations else ["M"]
    phones = [PHONE_MAP.get(re.sub(r"\d", "", phone), "m") for phone in raw_phones]
    phone_duration = max(duration / len(phones), 0.01)
    return [{"phone": f"{phone}_0", "duration": phone_duration} for phone in phones]


def main():
    parser = argparse.ArgumentParser(description="Create Gentle-compatible timestamps using Whisper.")
    parser.add_argument("--input_file", required=True, help="Path without .wav/.txt suffix")
    parser.add_argument("--model", default="base", help="Whisper model name (default: base)")
    args = parser.parse_args()

    with open(args.input_file + ".txt", encoding="utf-8") as script_file:
        words = script_words(script_file.read())
    audio = whisper.load_audio(args.input_file + ".wav")
    model = whisper.load_model(args.model)
    result = model.transcribe(audio, language="en", word_timestamps=True, fp16=False)
    heard = whisper_words(result)
    if not heard:
        raise RuntimeError("Whisper returned no word timestamps for the supplied audio.")

    timestamps = fill_missing_timestamps(words, matched_timestamps([normalise(word) for word in words], heard), len(audio) / SAMPLE_RATE)
    aligned_words = []
    for word, (start, end) in zip(words, timestamps):
        duration = max(end - start, 0.03)
        aligned_words.append({
            "case": "success",
            "word": word,
            "start": round(start, 3),
            "end": round(start + duration, 3),
            "phones": phones_for(word, duration),
        })

    with open(args.input_file + ".json", "w", encoding="utf-8") as output_file:
        json.dump({"words": aligned_words}, output_file, indent=2)
    print(f"Created alignment for {len(words)} script words using {len(heard)} Whisper words.")


if __name__ == "__main__":
    main()
