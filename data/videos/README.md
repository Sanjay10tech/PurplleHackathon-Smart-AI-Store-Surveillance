# CCTV sample videos

Place the five Purplle pilot store MP4 files here (not committed — ~680 MB total):

| File | Camera role |
|------|-------------|
| `CAM 1.mp4` | Floor |
| `CAM 2.mp4` | Floor |
| `CAM 3.mp4` | Entry |
| `CAM 4.mp4` | Backroom |
| `CAM 5.mp4` | Billing |

## Setup

From the challenge dataset folder:

```bash
# Linux / macOS
python scripts/setup_videos.py --source "/path/to/CCTV Footage"

# Windows PowerShell
python scripts/setup_videos.py --source "C:\path\to\CCTV Footage"
```

Or copy the five files manually into this directory.

## Verify

```bash
python scripts/setup_videos.py --check
python -m pipeline.run --mock --camera "CAM 3" --max-frames 20
```

Pipeline config references these paths as `data/videos/CAM *.mp4` (relative to repo root).
