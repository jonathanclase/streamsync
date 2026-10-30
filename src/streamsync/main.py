from . import helpers, correlate, makewaves
from .fileobject import fileobject

import subprocess, sys, tempfile, time
from wave import Error as waverror
from argparse import ArgumentParser

from .convert import comm, combine_files

ERRORS = (OSError, waverror, ValueError, RuntimeError, subprocess.CalledProcessError)

def main(baseline:str, subjects:list, verbose:bool=False, minimal_output:bool=False) -> list[comm]:
    comms = []
    baseline = fileobject(baseline)

    with tempfile.TemporaryDirectory(prefix="streamsync_") as tmpdir:
        try:
            baseline_wav = makewaves.create_wav(baseline, tmpdir)
            baseline_env = correlate.envelope(baseline_wav)
        except ERRORS as e:
            sys.exit(f"Baseline: {e}")

        if not minimal_output: print(f"Baseline: {baseline.name}")
        for subj in subjects:
            subj = fileobject(subj)
            if not minimal_output: print(f"{subj.name}:")

            try:
                subj_wav = makewaves.create_wav(subj, tmpdir)
                result = correlate.find_offset(baseline_wav, subj_wav, baseline_env)
            except ERRORS as e:
                print(f"\tError: {e}", file=sys.stderr)
                if minimal_output: print("None")
                continue

            if not result.matched:
                if not minimal_output: print(f"\t{correlate.no_match_reason(result)}; skipped")
                else: print("None")
                if verbose and not minimal_output:
                    correlate.print_diagnostics(result)
                continue

            if not minimal_output:
                print(f"\tOffset: {result.offset:+.5f}s")
            else:
                print(f"{result.offset:+.5f}")
            if note := correlate.coarse_only_note(result):
                if not minimal_output:print(f"\t{note}")
            if result.drift_ppm is not None:
                if not minimal_output: print(f"\tDrift: {result.drift_ppm:+.1f} ppm")
            if result.segments and not minimal_output: print("\tTest Segments:")
            for s in result.segments:
                if not minimal_output: print(f"\t\t{helpers.float_to_timestamp(s.start)} - {helpers.float_to_timestamp(s.stop)}: Offset {s.offset:+.3f} s")
            if verbose and not minimal_output:
                correlate.print_diagnostics(result)
            comms.append(comm(file=subj, offset=result.offset, titletag="", titlelang="eng"))

    return comms

def cli() -> None:
    started = time.monotonic()

    argparser = ArgumentParser()
    argparser.add_argument('-b', '--baseline', required=True, help="The baseline media file (the video stream)")
    argparser.add_argument('-s', '--subject', required=True, action="append", help="A media file to compare against the baseline (a commentary stream); repeatable")
    argparser.add_argument('-v', '--verbose', action="store_true", help="Also print the coarse peaks and every window's fine result")
    argparser.add_argument('-o', '--output-only', action="store_true", help="Don't prompt to mux the files; display the results only")
    argparser.add_argument('-m', '--minimal-output', action="store_true", help="Show only the offset result (float) or None, with no other details (Overrides -v/--verbose)")
    args = argparser.parse_args()

    baseline = args.baseline

    comms = main(baseline, args.subject, args.verbose, args.minimal_output)

    if not args.minimal_output:
        print()
        minutes, seconds = divmod(round(time.monotonic() - started), 60)
        print(f"Finished in {minutes}m {seconds:02}s.")

    if not comms:
        # No match is a valid result in output-only mode, so exit cleanly
        if args.minimal_output:
            return      # each subject already printed its None
        elif args.output_only:
            print("No subject matched the baseline.")
            return
        sys.exit("No subject matched the baseline; nothing to mux.")

    
    if not args.output_only and not args.minimal_output and input("\tMux into output? [y/N] ").strip().lower() in ("y", "yes"):
        try:
            combine_files(baseline, comms, "output.mkv")
        except ERRORS as e:
            print(f"Output: {e}", file=sys.stderr)
            sys.exit(1)
        print("Wrote output.mkv")

if __name__ == "__main__":
    cli()

