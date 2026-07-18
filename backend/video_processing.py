from pathlib import Path
import cv2


def extract_frames(video_path: str, video_id: str, every_seconds: float = 3.0, frames_root=None):
    if frames_root is None:
        from settings import get_settings
        frames_root = get_settings().frames_dir
    output_dir = Path(frames_root) / video_id
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_interval = max(int(fps * every_seconds), 1)

    frames = []
    frame_index = 0
    saved_index = 0

    while True:
        success, frame = cap.read()
        if not success:
            break

        if frame_index % frame_interval == 0:
            timestamp = frame_index / fps
            frame_path = output_dir / f"frame_{saved_index:04d}.jpg"
            cv2.imwrite(str(frame_path), frame)

            frames.append({
                "frame_index": frame_index,
                "timestamp_sec": round(timestamp, 2),
                "path": str(frame_path)
            })

            saved_index += 1

        frame_index += 1

    cap.release()
    return frames