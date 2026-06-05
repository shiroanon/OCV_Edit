# Media Metadata Specification

This document defines the structured metadata formats used by the **Precision Meta** annotator for both video and audio. The metadata is designed to be embedded directly into media files.

## 1. Video Metadata (com.shiro.video)

### 1.1 Storage Method

The metadata is stored as a UTF-8 encoded JSON string within an MP4 **Freeform Atom** (`----`).

- **Atom Type**: `moov.udta.meta.ilst.----`
- **Mean**: `com.shiro.video`
- **Name**: `metadata`

This approach ensures compatibility with most MP4 parsers while keeping the data hidden from standard players unless they specifically look for this namespace.

### 1.2 JSON Structure

The top-level object for video metadata contains the following fields:

| Field | Type | Description |
| :--- | :--- | :--- |
| `segments` | `Array<Segment>` | A list of annotated time ranges within the video. |
| `peak` | `String` | The global peak timestamp (`HH:MM:SS.ss`). |
| `blacklist` | `Array<String>` | List of ignored ranges in `HH:MM:SS.ss-HH:MM:SS.ss` format. |

---

#### 1.2.1. Segment Object

Each segment represents a specific clip or section of the video.

```json
{
  "id": 1,
  "interval": [60.00, 141.00],
  "tags": ["action", "exterior"],
  "meta": {
    "action": ["running"],
    "camera": ["tracking"],
    "focus": ["sharp"],
    "actpoints": ["00:01:10.50", "00:02:15.00"],
    "peakpoint": ["00:01:45.22"]
  }
}
```

#### Field Definitions:
- **`id`**: (Integer) A unique identifier for the segment within the video context.
- **`interval`**: (`[Float, Float]`) The start and end time of the segment in **seconds** from the beginning of the file.
- **`tags`**: (`Array<String>`) General labels for categorization.
- **`meta`**: (Object) Deep metadata for the segment.
    - **`action`**: (Array) List of physical actions occurring.
    - **`camera`**: (Array) Camera techniques (e.g., "Pan", "Tilt", "Static").
    - **`focus`**: (Array) Focus state or focal points.
    - **`actpoints`**: (`Array<String>`) High-precision timestamps (`HH:MM:SS.ss`) marking specific "beats" or events within the segment.
    - **`peakpoint`**: (`Array<String>`) Timestamps marking the climax or key frame of the segment.

---

#### 1.2.2. Blacklist Format

Blacklist intervals are stored as strings using the range format:
`HH:MM:SS.ss-HH:MM:SS.ss`

Example: `"00:05:10.00-00:05:22.50"`

---

### 1.3 Timecode Specification

All string-based timestamps use the following format:
`HH:MM:SS.ss`

- **HH**: Hours (00-99)
- **MM**: Minutes (00-59)
- **SS**: Seconds (00-59)
- **ss**: Centiseconds (00-99)

The **`interval`** field is the only one that uses raw **float seconds**, which is the preferred format for programmatic seeking and duration calculations.

### 1.4 Implementation Details (Backend)

The backend utilizes the `mutagen` library in Python to perform the injection:

```python
from mutagen.mp4 import MP4
video = MP4("video.mp4")
video["----:com.shiro.video:metadata"] = [json_data.encode("utf-8")]
video.save()
```

## 2. Audio Metadata (com.shiro.audio)

The audio metadata is similarly structured but focuses on musical and rhythmic elements like beats and transitions.

### 2.1 Storage Method

Like video, audio metadata can be stored in custom metadata tags depending on the container format (e.g., ID3 tags for MP3, Vorbis comments for FLAC/OGG, or custom atoms for M4A). The namespace is `com.shiro.audio`.

### 2.2 JSON Structure

The top-level object for audio metadata contains:

| Field | Type | Description |
| :--- | :--- | :--- |
| `segments` | `Array<Segment>` | A list of annotated time ranges within the audio. |

#### 2.2.1. Segment Object

Each segment represents a specific section of the audio track.

```json
{
  "id": 1,
  "interval": [60.00, 141.00],
  "major": [1.01, 2.42, 2.70, 3.10],
  "minor": [1.19, 1.33, 2.50, 2.60, 2.70, 2.80, 2.90],
  "suggestedtrans": ["slideup", "slidedown"]
}
```

#### Field Definitions:
- **`id`**: (Integer) A unique identifier for the segment within the audio context.
- **`interval`**: (`[Float, Float]`) The start and end time of the segment in **seconds** from the beginning of the file.
- **`major`**: (`Array<Float>`) List of major beat timestamps in seconds.
- **`minor`**: (`Array<Float>`) List of minor beat timestamps in seconds.
- **`suggestedtrans`**: (`Array<String>`) Suggested transitions suitable for this audio segment (e.g., "slideup", "slidedown").
