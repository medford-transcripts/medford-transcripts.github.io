"""
Does this GPU fit the pipeline, and how much faster is it?

STANDALONE. Copy this file, one .mp3, and hf_token.txt to the GPU machine.
It imports nothing from this repo.

WHAT IT IS DECIDING. The card in question is an NVIDIA T400 with 4 GB. That is
the interesting number: whisper large-v2 is ~1.55B parameters, so float16
weights alone are ~3.1 GB before any activations, and pyannote needs room
beside it. float16 may simply not fit. int8 should (~1.6 GB) at some accuracy
cost. This script finds out rather than guessing, and it tests DIARIZATION
too, because diarization is 50% of the pipeline's compute -- measured 43.9%
transcription / 6.2% alignment / 49.8% diarization over 14 meetings. A GPU
that accelerates only transcription caps out at a 2x speedup no matter how
fast it is.

THE BASELINE TO BEAT, measured on the current CPU box over 3 days of real
running: 2.21x realtime end to end (1 hour of audio costs 2.21 hours), which
puts the remaining 1,096-hour backlog at about 3.3 months.

Usage:
    pip install whisperx            # needs a CUDA torch build, see below
    python gpu_benchmark.py --audio meeting.mp3 --minutes 10

If it reports "torch is CPU-only" you have the wrong torch wheel; install a
CUDA build from https://pytorch.org before anything else here means anything.
"""

import argparse
import os
import subprocess
import sys
import time


def hr(t):
    return "%dm%02ds" % (int(t) // 60, int(t) % 60)


def report_env():
    print("=" * 62)
    print("ENVIRONMENT")
    print("=" * 62)
    try:
        import torch
    except ImportError:
        print("  torch not installed")
        return None
    print("  torch            : %s" % torch.__version__)
    print("  built for CUDA   : %s" % torch.version.cuda)
    ok = torch.cuda.is_available()
    print("  CUDA available   : %s" % ok)
    if not ok:
        print()
        print("  torch is CPU-only. Install a CUDA build from pytorch.org;")
        print("  nothing below will mean anything until torch.cuda works.")
        return None
    i = torch.cuda.current_device()
    props = torch.cuda.get_device_properties(i)
    gb = props.total_memory / 1024 ** 3
    print("  device           : %s" % props.name)
    print("  VRAM             : %.2f GB" % gb)
    print("  capability       : %d.%d" % (props.major, props.minor))
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True)
        if out.stdout.strip():
            print("  driver           : %s" % out.stdout.strip())
    except OSError:
        pass
    if gb < 5:
        print()
        print("  NOTE: under 5 GB. large-v2 in float16 is ~3.1 GB of weights")
        print("  before activations, so float16 may not fit. int8 is tried as a")
        print("  fallback and is the realistic configuration for this card.")
    return gb


def trim(audio, minutes, out="_bench_clip.wav"):
    """Cut the first N minutes so a test is minutes, not hours."""
    if not minutes:
        return audio
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", audio,
                        "-t", str(int(minutes * 60)), "-ac", "1", "-ar", "16000", out],
                       check=True)
        print("  trimmed first %g min -> %s" % (minutes, out))
        return out
    except (OSError, subprocess.CalledProcessError):
        print("  ffmpeg unavailable; using the whole file")
        return audio


def peak_vram():
    import torch
    return torch.cuda.max_memory_allocated() / 1024 ** 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="an .mp3/.wav from the archive")
    ap.add_argument("--minutes", type=float, default=10.0,
                    help="how much audio to test (0 = all). 10 is plenty.")
    ap.add_argument("--model", default="large-v2")
    ap.add_argument("--batch-size", type=int, default=4,
                    help="lower this first if you hit OOM (CPU default is 8-16)")
    ap.add_argument("--hf-token-file", default="hf_token.txt")
    ap.add_argument("--skip-diarization", action="store_true")
    args = ap.parse_args()

    gb = report_env()
    if gb is None:
        return 1
    import torch
    import whisperx

    clip = trim(args.audio, args.minutes)
    audio = whisperx.load_audio(clip)
    seconds = len(audio) / 16000.0
    print("\n  test audio: %.1f minutes\n" % (seconds / 60.0))

    results = {}
    compute_used = None

    print("=" * 62)
    print("1. TRANSCRIPTION")
    print("=" * 62)
    for compute_type in ("float16", "int8"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        try:
            print("  trying compute_type=%s batch_size=%d ..." % (compute_type, args.batch_size))
            t0 = time.time()
            model = whisperx.load_model(args.model, "cuda", compute_type=compute_type,
                                        language="en")
            load = time.time() - t0
            t0 = time.time()
            out = model.transcribe(audio, batch_size=args.batch_size)
            dt = time.time() - t0
            print("     load %s, transcribe %s, peak VRAM %.2f GB"
                  % (hr(load), hr(dt), peak_vram()))
            results["transcribe"] = dt
            compute_used = compute_type
            break
        except Exception as e:
            msg = str(e)
            print("     FAILED: %s" % msg[:140])
            if "out of memory" in msg.lower() or "cuda" in msg.lower():
                print("     -> insufficient VRAM for %s; falling back" % compute_type)
            try:
                del model
            except Exception:
                pass
            torch.cuda.empty_cache()
    if compute_used is None:
        print("\n  VERDICT: this card cannot run %s at any precision tried." % args.model)
        print("  Try --model medium, or --batch-size 1.")
        return 2

    print("\n" + "=" * 62)
    print("2. ALIGNMENT")
    print("=" * 62)
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    amodel, meta = whisperx.load_align_model(language_code="en", device="cuda")
    aligned = whisperx.align(out["segments"], amodel, meta, audio, "cuda",
                             return_char_alignments=False)
    results["align"] = time.time() - t0
    print("  %s, peak VRAM %.2f GB" % (hr(results["align"]), peak_vram()))
    del amodel
    torch.cuda.empty_cache()

    if not args.skip_diarization:
        print("\n" + "=" * 62)
        print("3. DIARIZATION   (half the pipeline's compute -- the one that decides this)")
        print("=" * 62)
        try:
            token = open(args.hf_token_file).read().strip()
        except OSError:
            print("  no %s; skipping. Diarization is 50%% of the work, so a run"
                  % args.hf_token_file)
            print("  without it does NOT tell you whether this card is enough.")
            token = None
        if token:
            torch.cuda.reset_peak_memory_stats()
            try:
                t0 = time.time()
                dia = whisperx.DiarizationPipeline(
                    model_name="pyannote/speaker-diarization-3.1",
                    use_auth_token=token, device="cuda")
                segs = dia(audio)
                results["diarize"] = time.time() - t0
                print("  %s, peak VRAM %.2f GB, %d speaker turns"
                      % (hr(results["diarize"]), peak_vram(), len(segs)))
            except Exception as e:
                print("  FAILED: %s" % str(e)[:200])
                print("  If this is OOM, the card runs transcription but not the")
                print("  whole pipeline, which caps the useful speedup near 2x.")

    print("\n" + "=" * 62)
    print("RESULT")
    print("=" * 62)
    total = sum(results.values())
    print("  compute_type used : %s" % compute_used)
    print("  audio             : %.1f min" % (seconds / 60.0))
    for k in ("transcribe", "align", "diarize"):
        if k in results:
            print("  %-17s %8s   %5.2fx realtime"
                  % (k, hr(results[k]), results[k] / seconds))
    if "diarize" not in results:
        print("  diarize           (not measured -- see above)")
    print("  %-17s %8s   %5.2fx realtime" % ("TOTAL", hr(total), total / seconds))
    print()
    cpu = 2.21
    factor = total / seconds
    print("  CPU box measured  : %.2fx realtime (3 days of real running)" % cpu)
    if factor > 0:
        print("  this GPU          : %.2fx realtime  ->  %.1fx faster" % (factor, cpu / factor))
        backlog = 1096.0
        days = backlog * factor / 24.0
        print()
        print("  remaining backlog : %.0f audio-hours" % backlog)
        print("    on the CPU box  : %.0f days" % (backlog * cpu / 24.0))
        print("    on this GPU     : %.0f days" % days)
        newcity = 4365.0
        print("  a new city (%.0f h): %.0f days on this GPU" % (newcity, newcity * factor / 24.0))
    if "diarize" not in results:
        print()
        print("  INCOMPLETE: without the diarization number this cannot answer")
        print("  the question. Diarization is 49.8% of the pipeline's compute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
