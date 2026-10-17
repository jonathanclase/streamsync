# StreamSync

---
## User Scenarios

**Matched Commentary Track**: Kylie has a downloaded copy of Rian Johnson's in-theater commentary for _Knives Out_ (2019), and a digital copy of the movie that she has purchased. She wants to embed the commentary so that she can play it in sync with the movie. Using StreamSync, she compares the two files to reveal an offset of +3.12010s. She opts to mux the files into an output, and an MKV file containing the commentary track is created automatically. She watches the video on her iPhone using Infuse, picking the commentary track when desired.

**Unmatched Reaction Track**: Ash has a RiffTrax audio file for _Santa Claus Conquers the Martians_ (1964) and a digital copy created from a DVD. They want to listen to the RiffTrax alongside the film. Using StreamSync, they compare the two files to reveal that there is no matching offset that will synchronize the two tracks. Ash does some research and determines that the DVD copy was created incorrectly; Ash looks for a newer version of the film.

---
## Requirements
- Python 3.10+ (tested on 3.12)
- [FFmpeg](https://ffmpeg.org/download.html), with `ffmpeg` and `ffprobe` on your PATH. pip can't install these, so install them yourself:

<table>
<th>Operating System</th><th>Run</th>
<tr><td>Windows</td><td>

```bash
winget install Gyan.FFmpeg
```
</td></tr>
<tr><td>macOS (with Homebrew)</td><td>

```bash
brew install ffmpeg
```
</td></tr>
<tr><td>Ubuntu/Mint/Debian</td><td>

```bash
sudo apt install ffmpeg
```
</td></tr>
<tr><td>Fedora/RHEL</td><td>

```bash
sudo dnf install ffmpeg-free
```
</td></tr>
</table>

To check that both are available, run `ffmpeg -version` and `ffprobe -version`.

The Python dependencies (NumPy and SciPy) are installed automatically.

---
## How it works
StreamSync works out how far a separate audio recording, such as a commentary track, is offset from a video. It then adds the recording to the video as an extra audio track, already in sync.

1. **Extract.** FFmpeg converts the first audio track of each file to a temporary mono 16-bit WAV. WAV files are used as they are.
2. **Coarse match.** Each recording is reduced to its *loudness envelope*: how loud it is, measured 400 times a second. The two envelopes are cross-correlated to find the shift where their loud and quiet moments line up best. This works even when the two recordings sound quite different, for example a commentary laid over the film's own audio. The result is accurate to about 2.5 ms.
3. **Fine match.** The baseline is split into about 40 windows. In each one, up to 10 s of full-quality audio from both files is compared within ±0.5 s of the coarse offset, which gives an offset accurate to a single sample for that window.
4. **Check.** Windows with a weak match are discarded. A robust trend line is fitted through the rest, and windows within 2 ms of it count as *matched*. The overall offset is the median of the matched windows. The slope of the line shows whether one recording's clock runs slightly fast or slow (*drift*).
5. **Mux.** If you choose to, FFmpeg copies the video with every original audio and subtitle track into a new MKV file, adding each matched recording as an extra audio track shifted by its offset. Nothing is re-encoded, so muxing is fast and loses no quality.

---
## Installation

#### Using `pipx` (Recommended)

**To install `pipx`:**

<table>
<th>Operating System</th><th>Run</th>
<tr><td>Windows</td><td>

```bash
py -m pip install --user pipx
py -m pipx ensurepath
```
</td></tr>
<tr><td>macOS (with Homebrew)</td><td>

```bash
brew install pipx
pipx ensurepath
```
</td></tr>
<tr><td>macOS (without Homebrew)</td><td>

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```
</td></tr>

<tr><td>Ubuntu/Mint/Debian</td><td>

```bash
sudo apt install pipx
pipx ensurepath
```
</td></tr>

<tr><td>Fedora/RHEL</td><td>

```bash
sudo dnf install pipx
pipx ensurepath
```
</td></tr>
</table>

*`pipx ensurepath` adds to the PATH environment variable, if necessary. Open a new terminal afterwards for the change to take effect.*

**To install StreamSync:**

```bash
pipx install git+https://github.com/jonathanclase/streamsync
```

pipx installs StreamSync in its own isolated environment, so its dependencies don't conflict with your other Python packages.

#### Using `pip`

Ideally, install into a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install git+https://github.com/jonathanclase/streamsync
```

The `streamsync` command is only available while the virtual environment is active.

#### Upgrading

```bash
pipx upgrade streamsync
```

If you installed with pip, run this with the virtual environment active:

```bash
pip install --upgrade git+https://github.com/jonathanclase/streamsync
```

#### Uninstalling

```bash
pipx uninstall streamsync
```

If you installed with pip, run this with the virtual environment active:

```bash
pip uninstall streamsync
```

FFmpeg is not removed. Uninstall it separately if you no longer need it.

---
## Development

Clone the repository and install it in editable mode with the development dependencies:

```bash
git clone https://github.com/jonathanclase/streamsync
cd streamsync
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Changes to the source take effect immediately, with no reinstall needed.

Run the tests with:

```bash
pytest
```

Tests that build media files are skipped if `ffmpeg` and `ffprobe` aren't on your PATH.

| File | Purpose |
|---|---|
| `main.py` | Command-line entry point: runs the sync and asks whether to mux |
| `makewaves.py` | Extracts each file's first audio track to a mono WAV |
| `correlate.py` | Finds the offset (coarse envelope match, then fine per-window match) |
| `syncresult.py` | The result types: offset, drift, matched segments and diagnostics |
| `convert.py` | Muxes the commentary tracks into the output file |
| `helpers.py` | ffprobe stream lookup and timestamp formatting |

All of these are in `src/streamsync/`.

To test just the offset detection on WAV files, without converting or muxing, run `correlate.py` on its own:

```bash
python -m streamsync.correlate -b reference.wav -s other.wav -v
```

---
## Usage

```bash
streamsync -b BASELINE -s SUBJECT [-s SUBJECT ...] [-v]
```

| Option | Description |
|---|---|
| `-b`, `--baseline` | The video file to sync to. Required. |
| `-s`, `--subject` | An audio or video file to sync, such as a commentary track. Required; repeat to sync several files in one run. |
| `-v`, `--verbose` | Also print diagnostics: the strongest coarse matches and every window's result. Useful when a result looks wrong. |

Any format FFmpeg can read works for both. Only the **first** audio track of each file is used for matching.

**Example:** sync two commentary tracks to a film.

```bash
streamsync -b "Big Fish (2003).mkv" -s "Director Commentary.mp3" -s "Cast Commentary.mp3"
```

After matching, StreamSync asks whether to mux the matched tracks into a new file. If you answer `y`, it asks for a title for each track (for example "Director's Commentary"), which is what media players show in their audio track menu.

---
## Output

For each subject file, StreamSync prints the result to the terminal:

```
Baseline: Film (2016).mkv
Film (2016) Commentary with Director.mp3:
	Offset: +0.50831s
	Drift: +1.8 ppm
	Test Segments:
		00:53:13 - 00:56:20: Offset +0.506 s
		01:05:44 - 01:08:52: Offset +0.508 s
		01:08:52 - 01:12:00: Offset +0.509 s
		01:58:57 - 02:02:05: Offset +0.512 s

Finished in 0m 18s.
	Mux into output? [y/N]
```

| Line | Meaning |
|---|---|
| **Offset** | How many seconds the subject is shifted by to line up with the baseline. Positive means the subject is delayed by that amount; negative means it is moved earlier. |
| **Drift** | How fast the offset changes over time, in parts per million, because the two recordings' clocks run at slightly different speeds. +1.8 ppm adds about 6.5 ms per hour. Shown only when at least 3 segments matched. |
| **Test Segments** | The stretches of the baseline where the full-quality audio confirmed the offset, each with its own measured offset. |

Other messages you may see:
- **`Coarse estimate (±2.5 ms) …`** The loudness patterns match, but no window confirmed it at full quality. The offset is probably right, but less precise.
- **`No match: … ; skipped`** No reliable offset was found, so the file is left out of the output. Run with `-v` to see why.
- **`No subject matched the baseline; nothing to mux.`** None of the subjects matched, so no file is written.

If you choose to mux, StreamSync writes **`output.mkv`** to the current directory, **overwriting** any existing file of that name. It contains:
- every video, audio and subtitle track from the baseline, unchanged
- one extra audio track per matched subject, shifted by its offset, with the title you entered and the language set to English (`eng`)

Nothing is re-encoded, so the output is the same quality as the inputs.

---
## Product Roadmap
**Goal:** To **reduce the manual work** required to synchronize **multiple audio tracks** into the same container and to **provide details** used to manually **check the automated work** when necessary.
#### 🟪 ${\color{purple}\textsf{Completed}}$
- ~~Initial build~~

#### 🟩 ${\color{green}\textsf{Now}}$
- Continue working on the thresholds to find a balance between false positives and false negatives

#### 🟦 ${\color{blue}\textsf{Next}}$

#### 🟧 ${\color{orange}\textsf{Later}}$
- Format the output and allow this script to be used as a tool in a larger workflow, e.g., by Claude

## License

[MIT](LICENSE)