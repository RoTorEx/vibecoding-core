"""One recording per process; recordings and transcripts never enter logs."""

import json
import os
import resource
import sys
import time


def run(model_dir: str, path: str) -> dict:
    started = time.monotonic()
    if hasattr(os, "nice"):
        os.nice(5)
    import av
    import numpy as np
    from faster_whisper import WhisperModel

    # Limit expansion before decoding compressed audio, including files without duration metadata.
    samples = []
    count = 0
    with av.open(path) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(stream):
            for output in resampler.resample(frame):
                count += output.samples
                if count > 300 * 16000:
                    raise ValueError("Voice recordings are limited to five minutes")
                samples.append(output.to_ndarray().flatten())
        for output in resampler.resample(None):
            count += output.samples
            if count > 300 * 16000:
                raise ValueError("Voice recordings are limited to five minutes")
            samples.append(output.to_ndarray().flatten())
    # PyAV handles Telegram Ogg/Opus directly; no host ffmpeg or network service.
    if not samples:
        raise ValueError("No audio in recording")
    audio = np.concatenate(samples).astype(np.float32) / 32768.0
    del samples
    model = WhisperModel(
        model_dir, device="cpu", compute_type="int8", cpu_threads=1, num_workers=1, local_files_only=True
    )
    segments, info = model.transcribe(audio, beam_size=1, vad_filter=True, task="transcribe")
    text = "".join(segment.text for segment in segments).strip()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "text": text,
        "language": info.language,
        "duration_seconds": len(audio) / 16000,
        "wall_seconds": time.monotonic() - started,
        "cpu_seconds": usage.ru_utime + usage.ru_stime,
        "peak_rss_mib": usage.ru_maxrss / (1024 if sys.platform != "darwin" else 1024 * 1024),
    }


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1], sys.argv[2]), ensure_ascii=False))
