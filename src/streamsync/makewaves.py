import subprocess, os
from .fileobject import fileobject
from .helpers import audio_streams

def find_audio_stream(in_file:fileobject) -> int:
    """Finds the stream index of the first audio track

    Args:
        in_file (fileobject): The file to probe

    Returns:
        int: The absolute stream index, for use with `-map 0:<index>`

    Raises:
        ValueError: If the file has no audio tracks
        subprocess.CalledProcessError: If ffprobe fails
    """
    streams = audio_streams(in_file)
    if not streams:
        raise ValueError(f"No audio tracks found in '{in_file.path}'")

    return streams[0]

def create_wav(in_file:fileobject, clip_dir:str, audio_filter:str|None=None) -> str:
    """Converts the first audio track of a file to a mono 16-bit .wav.

    .wav inputs are returned as-is. Others are saved to clip_dir as
    "<stem>.wav", with "_1", "_2", ... appended if that name is taken.

    Args:
        in_file (fileobject): The file to convert
        clip_dir (str): The directory to save the .wav in
        audio_filter (str | None): An ffmpeg audio filter to clean up the audio, such as
            "highpass=f=200,lowpass=f=3500,afftdn", or None for unfiltered audio

    Returns:
        str: The path of the .wav file

    Raises:
        ValueError: If the file has no audio tracks
        subprocess.CalledProcessError: If ffprobe fails
        RuntimeError: If ffmpeg fails to convert the file
    """
    if in_file.name.lower().endswith(".wav"):
        return in_file.path

    stream_index = find_audio_stream(in_file)
    clip_path = os.path.join(clip_dir, f"{in_file.stem}.wav")
    n = 0
    while os.path.exists(clip_path):
        n += 1
        clip_path = os.path.join(clip_dir, f"{in_file.stem}_{n}.wav")

    # correlate reads 16-bit samples from channel 0 only, so downmix to keep every channel's content
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y",
                "-i", in_file.path,
                "-map", f"0:{stream_index}",
                "-ac", "1", "-c:a", "pcm_s16le"]
    if audio_filter:
        command += ["-af", audio_filter]
    command += [clip_path]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed converting '{in_file.path}':\n{result.stderr}")

    return clip_path
