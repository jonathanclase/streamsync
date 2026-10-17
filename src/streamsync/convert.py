import subprocess
from .fileobject import fileobject
from .helpers import audio_streams

from dataclasses import dataclass

@dataclass
class comm:
    """A commentary track to mux into the baseline.

    Attributes:
        file (fileobject): The commentary file; its first audio track is used
        offset (float): Seconds to shift the commentary by (SyncResult.offset)
        titletag (str): The track's title
        titlelang (str): The track's ISO 639-2 language code, such as "eng"
    """
    file: fileobject
    offset: float
    titletag: str
    titlelang: str

def combine_files(in_file:str, comms:list[comm], out_file:str) -> None:
    """Copies every stream of in_file, plus each commentary as an extra audio track, into out_file.

    Nothing is re-encoded. Each commentary is shifted by its offset and tagged
    with its title and language.

    Args:
        in_file (fileobject): The baseline (video) file
        comms (list[comm]): The commentary tracks to add
        out_file (str): The output path; overwritten if it exists

    Raises:
        subprocess.CalledProcessError: If ffprobe fails on in_file
        RuntimeError: If ffmpeg fails
    """
    in_file = fileobject(in_file)
    for comm in comms:
        comm.titletag = input(f"\tTitle for {comm.file.name}? ")

    n_base_audio = len(audio_streams(in_file))

    command = ["ffmpeg", "-nostdin", "-v", "error", "-y",
                "-i", in_file.path]
                # "-metadata:s:a:0", 'title="Original Audio"',
                # "-metadata:s:a:0", 'language="eng"']
    for c in comms:
        command += ["-itsoffset", str(c.offset),
                    "-i", c.file.path]
    command += ["-map", "0:v", "-map", "0:a"]
    for i in range(len(comms)):
        command += ["-map", f"{i + 1}:a:0"]
    command += ["-c", "copy"]
    command += ["-map", "0:s?"]        # "?": a baseline without subtitles is fine
    for i, c in enumerate(comms):
        command += [f"-metadata:s:a:{n_base_audio + i}", f"title={c.titletag}",
                    f"-metadata:s:a:{n_base_audio + i}", f"language={c.titlelang}",
                    f"-metadata:s:a:{n_base_audio + i}", f"itsoffset={c.offset:+.5f}"]
    command += [out_file]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed muxing '{out_file}':\n{result.stderr}")
