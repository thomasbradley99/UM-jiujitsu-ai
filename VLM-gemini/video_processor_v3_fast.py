#!/usr/bin/env python3
"""
BJJ Video Processor v3 - FAST Single-Prompt Approach

Strategy: Upload video once, get complete analysis in single API call
Goal: Reduce 8 minutes → 1-2 minutes
"""

import os
import json
import time
import subprocess
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pathlib import Path
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv


# Repo root = parent of this file's directory (VLM-gemini/).
REPO_ROOT = Path(__file__).resolve().parent.parent


def extract_first_json_object(text: str) -> str:
    """Extract the first balanced JSON object from a string.

    Tolerates leading/trailing whitespace, ```json``` markdown fences, and
    trailing extra data after the closing brace (the failure mode we hit on
    Flash output despite response_mime_type=application/json).

    Raises ValueError if no balanced object found.
    """
    s = text.strip()
    if s.startswith('```'):
        # Drop the opening fence line (```json or ```), and the trailing ``` if present.
        first_nl = s.find('\n')
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.rstrip().endswith('```'):
            s = s.rstrip()[:-3].rstrip()

    start = s.find('{')
    if start == -1:
        raise ValueError("no '{' found in response")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]

    raise ValueError("unterminated JSON object (depth never reached 0)")


def get_api_key():
    """Resolve the Gemini API key from env or .env.local at the repo root."""
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        env_path = REPO_ROOT / '.env.local'
        if env_path.exists():
            load_dotenv(env_path)
            api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise ValueError(
            f"GEMINI_API_KEY not found in environment or {REPO_ROOT / '.env.local'}"
        )
    return api_key


# ============================================================================
# FIGHTER PROFILING (from v2)
# ============================================================================

def get_video_info(video_path):
    """Get video FPS, duration, and total frames"""
    # Get FPS
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=r_frame_rate',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ], capture_output=True, text=True)
    
    fps_str = result.stdout.strip()
    if '/' in fps_str:
        num, den = fps_str.split('/')
        fps = float(num) / float(den)
    else:
        fps = float(fps_str)
    
    # Get duration
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 
        'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ], capture_output=True, text=True)
    
    duration = float(result.stdout.strip())
    total_frames = int(duration * fps)
    
    return fps, duration, total_frames


def extract_frames_for_profiling(video_path, num_frames=10):
    """Extract evenly distributed frames for fighter profiling"""
    print(f"📸 Extracting frames from {Path(video_path).name}...")
    
    fps, duration, total_frames = get_video_info(video_path)
    print(f"📹 Video: {fps:.1f} fps, {duration:.1f}s, {total_frames} total frames")
    
    # Calculate frame interval
    every_n_frames = max(total_frames // num_frames, 1)
    frame_numbers = list(range(0, total_frames, every_n_frames))[:num_frames]
    
    print(f"🎯 Extracting {len(frame_numbers)} frames (1 every {every_n_frames} frames)")
    
    frames_data = []
    video_path = Path(video_path)
    
    for i, frame_num in enumerate(frame_numbers):
        timestamp = frame_num / fps
        frame_path = video_path.parent / f"profile_frame_{i:04d}.jpg"
        
        subprocess.run([
            'ffmpeg', '-ss', str(timestamp), '-i', str(video_path),
            '-frames:v', '1', '-q:v', '2', str(frame_path),
            '-loglevel', 'error', '-y'
        ], check=True)
        
        if frame_path.exists():
            frames_data.append({
                'index': i,
                'timestamp': timestamp,
                'path': frame_path
            })
    
    print(f"✅ Extracted {len(frames_data)} frames")
    return frames_data


def analyze_single_frame(frame_data):
    """Analyze one frame (called in parallel)"""
    model = genai.GenerativeModel('gemini-2.5-flash')
    img = Image.open(frame_data['path'])
    
    prompt = """Describe the two people in this BJJ training video frame.

Focus on PERMANENT features (clothing, physical characteristics):
- Gi color and brand/text
- Rashguard color and design
- Body type, hair color, facial hair
- Distinctive features

Format: "Person 1: [description]. Person 2: [description]."
Keep it under 40 words."""

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }
    
    response = model.generate_content([prompt, img], safety_settings=safety_settings)
    return {
        'index': frame_data['index'],
        'timestamp': frame_data['timestamp'],
        'description': response.text.strip()
    }


def parallel_frame_analysis(frames_data, max_workers=50):
    """Analyze all frames in parallel"""
    print(f"🚀 Analyzing {len(frames_data)} frames in parallel (max {max_workers} workers)...")
    
    descriptions = []
    start_time = time.time()
    completed = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_single_frame, frame): frame for frame in frames_data}
        
        for future in as_completed(futures):
            try:
                result = future.result()
                descriptions.append(result)
                completed += 1
                
                if completed % 5 == 0 or completed == len(frames_data):
                    elapsed = time.time() - start_time
                    print(f"✅ {completed}/{len(frames_data)} completed ({elapsed:.1f}s elapsed)")
            except Exception as e:
                print(f"⚠️ Frame failed: {e}")
    
    elapsed = time.time() - start_time
    print(f"✅ All frames analyzed in {elapsed:.1f}s")
    
    descriptions.sort(key=lambda x: x['index'])
    return descriptions


def synthesize_fighter_profiles(descriptions):
    """Synthesize individual descriptions into consistent fighter profiles"""
    print(f"🧠 Synthesizing {len(descriptions)} descriptions into fighter profiles...")
    
    all_text = "\n".join([f"{d['timestamp']:.0f}s: {d['description']}" for d in descriptions])
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""You have {len(descriptions)} independent descriptions from a BJJ training video. 
Synthesize these into TWO consistent fighter profiles.

Descriptions:
{all_text}

Output ONLY this JSON (no markdown):
{{
  "fighter1": {{
    "short_name": "DARK GI",
    "clothing_detailed": "Dark navy gi with white brand text",
    "physical_features": "Bald, medium build"
  }},
  "fighter2": {{
    "short_name": "WHITE GI",
    "clothing_detailed": "White gi, no visible branding",
    "physical_features": "Dark hair, athletic build"
  }},
  "format": "Gi training" or "No-gi training"
}}

Rules:
- short_name should be 2-3 words max (e.g., "DARK GI", "BLACK RASHGUARD")
- Ignore temporary states (positions, actions)
- Focus on what makes each fighter recognizable throughout"""

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }
    
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json"
        ),
        safety_settings=safety_settings
    )
    
    return json.loads(response.text)


def profile_fighters(video_path):
    """Complete fighter profiling pipeline"""
    print(f"\n🎯 Stage 0: Profiling fighters...")
    
    # Extract frames
    frames_data = extract_frames_for_profiling(video_path, num_frames=10)
    
    # Analyze in parallel
    descriptions = parallel_frame_analysis(frames_data, max_workers=50)
    
    # Synthesize profiles
    profiles = synthesize_fighter_profiles(descriptions)
    
    # Cleanup frames
    video_dir = Path(video_path).parent
    for frame_file in video_dir.glob("profile_frame_*.jpg"):
        frame_file.unlink()
    
    fighter1 = profiles['fighter1']['short_name']
    fighter2 = profiles['fighter2']['short_name']
    print(f"✅ Profiled: {fighter1} vs {fighter2}\n")
    
    return profiles


# ============================================================================
# VIDEO SPLITTING
# ============================================================================

def make_clips(video_path, clips_dir, duration=45, overlap=10):
    """Split video into overlapping clips (same as v2)"""
    clips_dir = Path(clips_dir)
    clips_dir.mkdir(exist_ok=True, parents=True)
    
    _, video_duration, _ = get_video_info(video_path)
    
    start_times = []
    current = 0
    while current < video_duration:
        start_times.append(current)
        current += (duration - overlap)
    
    for start in start_times:
        mins = int(start // 60)
        secs = int(start % 60)
        output_path = clips_dir / f"clip_{mins:02d}m{secs:02d}s.mp4"
        
        subprocess.run([
            'ffmpeg', '-ss', str(start), '-i', str(video_path),
            '-t', str(duration), '-c', 'copy',
            str(output_path), '-loglevel', 'error', '-y'
        ], check=True)
        
        print(f"✅ {output_path.name}")
    
    return len(start_times)


# ============================================================================
# CLIP ANALYSIS
# ============================================================================

def build_clip_prompt(profiles):
    """Build prompt for analyzing individual clips"""
    fighter1 = profiles['fighter1']
    fighter2 = profiles['fighter2']
    
    return f"""Watch this Brazilian Jiu-Jitsu TRAINING clip and describe what happens chronologically.

This is COOPERATIVE TRAINING between training partners learning technique.

ATHLETES:
- {fighter1['short_name']}: {fighter1['clothing_detailed']}, {fighter1['physical_features']}
- {fighter2['short_name']}: {fighter2['clothing_detailed']}, {fighter2['physical_features']}

USE THESE EXACT NAMES in your description.

CRITICAL - BJJ TRAINING ROUND LOGIC:
1. Only ONE technique completion per round (when someone concedes/yields)
2. After EVERY successful technique, there is ALWAYS an immediate RESET:
   - Athletes release the position instantly
   - Both separate and stand up
   - Fist bump or hand acknowledgment (super obvious)
   - Both move to neutral positions
   - Brief pause before restarting

3. The RESET is proof a technique was successfully applied:
   - No reset = technique was defended (just an attempt)
   - Multiple "yields" without resets = incorrect, pick the real one

4. IMPORTANT - DO NOT describe attempts and completions separately:
   - If you see a reset at 60s, describe "50-60s: Athlete applies armbar, partner yields, reset"
   - DO NOT write: "50s: Athlete attempts armbar" AND "60s: Athlete completes armbar"
   - The attempt and completion are ONE EVENT, not two
   
5. When you see a RESET:
   - Describe the ENTIRE sequence (setup → application → reset) as ONE event
   - Include the 10 seconds before the reset in your description
   
6. Technique attempts vs successful applications:
   - Most techniques are DEFENDED (athlete escapes or resists)
   - Only mention successful application if you see the reset after
   - If no reset, just describe the position change or escape

Describe:
- Positions (guard, mount, back control, side control)
- Technique attempts (joint locks, neck controls, leg attacks - most are defended!)
- ONLY mark as successful if you see the reset sequence after
- Who has positional control at each moment
- Technical details (grips, pressure, defensive movements)

Write chronologically with approximate timestamps relative to clip start."""


def analyze_clip(clip_path, start_time, profiles):
    """Analyze one video clip via the Gemini File API.

    Inline payloads are capped at 20 MB; 90s @ 6 Mbps clips are ~70 MB, so we
    must upload via genai.upload_file() and reference the resulting file handle.
    """
    print(f"  Analyzing {clip_path.name}...", end=' ', flush=True)
    clip_start = time.time()

    uploaded = genai.upload_file(path=str(clip_path), mime_type='video/mp4')

    # Poll until the file is ACTIVE (Gemini transcodes/indexes video on upload).
    while uploaded.state.name == 'PROCESSING':
        time.sleep(2)
        uploaded = genai.get_file(uploaded.name)
    if uploaded.state.name != 'ACTIVE':
        print(f"⚠️  upload state={uploaded.state.name}")
        return {
            'start_time': start_time,
            'description': f"[Clip upload failed. state={uploaded.state.name}. Time range: {start_time}s-{start_time+90}s]"
        }

    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = build_clip_prompt(profiles)

    # Disable safety filters for BJJ training footage
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    try:
        response = model.generate_content(
            [uploaded, prompt],
            safety_settings=safety_settings
        )
    finally:
        try:
            genai.delete_file(uploaded.name)
        except Exception:
            pass

    # Handle blocked prompts
    if not response.candidates or not response.parts:
        print(f"⚠️  BLOCKED (safety filters)")
        return {
            'start_time': start_time,
            'description': f"[Clip analysis blocked by safety filters. Time range: {start_time}s-{start_time+90}s]"
        }

    clip_time = time.time() - clip_start
    print(f"({clip_time:.1f}s)")

    return {
        'start_time': start_time,
        'description': response.text.strip()
    }


# ============================================================================
# NARRATIVE ANALYSIS
# ============================================================================

def build_narrative_prompt(profiles):
    """Build prompt for Stage 1: Narrative description"""
    fighter1 = profiles['fighter1']
    fighter2 = profiles['fighter2']
    
    return f"""You are a Brazilian Jiu-Jitsu expert watching a match.

FIGHTERS:
- {fighter1['short_name']}: {fighter1['clothing_detailed']}, {fighter1['physical_features']}
- {fighter2['short_name']}: {fighter2['clothing_detailed']}, {fighter2['physical_features']}

Watch this entire BJJ match and provide a DETAILED chronological narrative of everything that happens.

Include:
- Every position change (guard pass, mount, side control, back control, etc.)
- Every submission attempt (successful or not)
- Every sweep, takedown, escape
- Timestamps for each event
- Who is doing what (use the fighter names above)
- Technical details (grips, pressure, mistakes)

Be THOROUGH. Don't miss submissions, back takes, or major positions.

Format as a detailed paragraph or chronological list with timestamps."""


def build_parsing_prompt(profiles, narrative):
    """Build prompt for Stage 2: Parse narrative into structured JSON"""
    fighter1 = profiles['fighter1']
    fighter2 = profiles['fighter2']
    
    fighter_section = (
        f"FIGHTERS:\n"
        f"- {fighter1['short_name']}\n"
        f"- {fighter2['short_name']}\n\n"
        f"Use these EXACT names in all JSON output."
    )
    
    narrative_section = f"MATCH NARRATIVE:\n{narrative}\n"
    
    # JSON template (no f-string to avoid brace conflicts)
    json_template = """
{
  "events": [
    {
      "timestamp": <seconds>,
      "type": "POSITION|SUBMISSION|TAKEDOWN|SWEEP|ESCAPE",
      "title": "<brief title>",
      "description": "<detailed description>",
      "attacker": "<fighter_id>",
      "defender": "<fighter_id>",
      "submission": <true|false>,
      "attempt": <true|false>,
      "perspectives": {
        "<fighter_id>": {
          "quality": "excellent|good|inaccuracy|mistake|blunder",
          "score": <0-100>,
          "points": <IBJJF points>,
          "analysis": "<what they did>",
          "betterMove": "<what they should do instead|null>",
          "whyBad": "<why it was bad|null>"
        }
      }
    }
  ],
  "fighter_stats": {
    "<fighter_id>": {
      "submissions": <count>,
      "takedowns": <count>,
      "sweeps": <count>,
      "positions": <count>,
      "escapes": <count>,
      "blunders": <count>,
      "mistakes": <count>,
      "inaccuracies": <count>,
      "total_points": <IBJJF points>
    }
  },
  "match_summary": {
    "final_scores": {
      "<fighter_id>": <points>
    },
    "point_differential": <diff>,
    "dominant_fighter": "<fighter_id|null>",
    "key_moment": {
      "event_index": <index>,
      "timestamp": <seconds>,
      "title": "<title>",
      "fighter": "<fighter_id>",
      "points": <points>
    }
  },
  "position_timeline": {
    "duration_seconds": <video_length>,
    "fighter_timelines": {
      "<fighter_id>": [
        {"position": "<position>", "start": <seconds>, "end": <seconds>}
      ]
    },
    "submissions": [
      {
        "fighter": "<fighter_id>",
        "type": "<submission_type>",
        "timestamp": <seconds>,
        "from_position": "<position>",
        "completed": <true|false>
      }
    ]
  },
  "key_moments": [
    {
      "event_index": <index>,
      "timestamp": <seconds>,
      "title": "<title>",
      "fighter": "<fighter_id>",
      "importance": <1-10>,
      "perspectives": {
        "<fighter_id>": {
          "whyBad": "<reason|null>",
          "betterMove": "<alternative|null>",
          "quality": "excellent|good|inaccuracy|mistake|blunder",
          "score": <0-100>,
          "points": <IBJJF points>
        }
      }
    }
  ]
}

VALID POSITION NAMES (use EXACTLY these - no variations or extra descriptions):
- Dominant: mount, back_control, side_control, knee_on_belly, north_south
- Neutral: closed_guard, open_guard, half_guard, butterfly_guard, standing
- Defensive: being_mounted, back_taken, side_control_bottom, turtle
- Transitions: scramble

RESET AFTER SUBMISSION RULE (MANDATORY):
After EVERY successful submission (completed=true), the next position segment MUST be "standing" for BOTH fighters.
This represents the reset that happens after someone taps.
Example: If submission at 58s, the position from 58s-63s should be "standing" for both fighters.

CRITICAL INSTRUCTIONS:
1. Use the EXACT fighter names provided above (e.g., "DARK GI", "WHITE GI", etc.)
2. Include perspectives for BOTH fighters on EVERY event
3. Detect ALL significant events (position changes, submissions, sweeps, escapes, attempts)
4. Calculate IBJJF points correctly (takedown: 2, sweep: 2, pass: 3, knee-on-belly: 2, mount: 4, back: 4, submission: 10)
5. Identify 4 key moments per fighter (8 total) - focus on mistakes/learning opportunities
6. Position timeline must cover entire video with no gaps
7. Position timeline MUST use ONLY the exact position names from the VALID POSITION NAMES list above - NO descriptions, NO parentheses, NO extra context
8. Quality ratings: excellent (80-100), good (61-79), inaccuracy (61-79), mistake (31-60), blunder (0-30)
9. Be THOROUGH - don't miss submissions, back control, mount, or other major positions
10. ONLY return valid JSON - no markdown, no code blocks, no explanations

Return ONLY the JSON object.
"""
    
    return (
        "You are a Brazilian Jiu-Jitsu expert. Parse the match narrative below into structured JSON.\n\n" +
        fighter_section + "\n" +
        narrative_section + "\n" +
        "Convert this narrative into the following JSON structure:\n" +
        json_template
    )


def process_video(video_path, out_dir=None):
    """
    Clip-based two-stage analysis:
    1. Split video, analyze each clip
    2. Parse combined narratives into structured JSON

    Args:
        video_path: path to the video file.
        out_dir: directory for clips/ and result.json. Defaults to <video_dir>.
    """
    print(f"\n🥋 BJJ Video Processor v3 - Clip-Based")
    print(f"{'='*70}")
    print(f"Video: {Path(video_path).name}")
    print(f"{'='*70}\n")
    
    # Configure Gemini
    api_key = get_api_key()
    genai.configure(api_key=api_key)
    
    start_time = time.time()
    
    # Stage 0: Profile fighters
    profiles = profile_fighters(video_path)
    
    # Stage 1: Split and analyze clips
    print(f"📹 Stage 1: Splitting and analyzing clips...")
    stage1_start = time.time()
    
    out_dir = Path(out_dir) if out_dir else Path(video_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = out_dir / "clips"
    
    num_clips = make_clips(video_path, clips_dir, duration=90, overlap=10)
    print(f"✅ Created {num_clips} clips\n")
    
    clip_files = sorted(clips_dir.glob("clip_*.mp4"))
    
    # Prepare clip data for parallel processing
    clip_data = []
    for clip_path in clip_files:
        # Extract start time from filename (e.g., clip_01m30s.mp4 -> 90)
        stem = clip_path.stem  # clip_01m30s
        time_part = stem.split('_')[1]  # 01m30s
        mins = int(time_part.split('m')[0])
        secs = int(time_part.split('m')[1].replace('s', ''))
        clip_start_time = mins * 60 + secs
        clip_data.append({
            'path': clip_path,
            'start_time': clip_start_time
        })
    
    # Analyze clips in parallel (reduced workers for Lambda memory constraints)
    print(f"🚀 Analyzing {len(clip_data)} clips in parallel (2 workers)...\n")
    clip_narratives = []
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(analyze_clip, clip['path'], clip['start_time'], profiles): clip 
            for clip in clip_data
        }
        
        for future in as_completed(futures):
            try:
                result = future.result()
                clip_narratives.append(result)
            except Exception as e:
                clip = futures[future]
                print(f"⚠️ Clip {clip['path'].name} failed: {e}")
    
    # Sort by start time
    clip_narratives.sort(key=lambda x: x['start_time'])

    stage1_time = time.time() - stage1_start
    print(f"\n✅ Stage 1 complete: Analyzed {len(clip_narratives)} clips ({stage1_time:.1f}s)\n")

    # Persist Stage 1 narratives so we never lose them to a Stage 2 parse failure.
    narratives_path = out_dir / "stage1_narratives.json"
    narratives_path.write_text(json.dumps(
        {
            "profiles": profiles,
            "clip_narratives": [
                {"start_time": n["start_time"], "description": n["description"]}
                for n in clip_narratives
            ],
        },
        indent=2,
    ))
    print(f"💾 wrote Stage 1 narratives -> {narratives_path}")

    # Combine all clip narratives
    combined_narrative = "\n\n".join([
        f"[{n['start_time']}s - {n['start_time']+90}s]\n{n['description']}"
        for n in clip_narratives
    ])

    # Stage 2: Parse combined narrative into structured JSON
    print(f"📊 Stage 2: Parsing narratives into structured JSON...", flush=True)
    parsing_prompt = build_parsing_prompt(profiles, combined_narrative)

    model = genai.GenerativeModel('gemini-2.5-flash')
    stage2_start = time.time()

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    response = model.generate_content(
        parsing_prompt,
        request_options={"timeout": 600},
        safety_settings=safety_settings
    )
    stage2_time = time.time() - stage2_start
    print(f"✅ Stage 2 complete: Parsed to JSON ({stage2_time:.1f}s)\n")

    # ALWAYS save the raw response before parsing — the model's most expensive
    # output should never be ephemeral.
    response_text = response.text or ""
    raw_response_path = out_dir / "stage2_response_raw.txt"
    raw_response_path.write_text(response_text)
    print(f"💾 wrote raw Stage 2 response -> {raw_response_path}")

    # Parse JSON response — robust to fences and trailing extra data.
    print(f"📊 Parsing response...")
    try:
        json_blob = extract_first_json_object(response_text)
        result = json.loads(json_blob)
        print(f"✅ Successfully parsed JSON\n")
    except (ValueError, json.JSONDecodeError) as e:
        print(f"❌ Failed to parse JSON response: {e}")
        print(f"   Raw response saved at: {raw_response_path}")
        print(f"\nResponse preview (first 500 chars):")
        print(response_text[:500])
        raise
    
    # Basic validation
    print(f"🔍 Validating structure...")
    required_keys = ['events', 'fighter_stats', 'match_summary', 'position_timeline', 'key_moments']
    missing = [k for k in required_keys if k not in result]
    
    if missing:
        print(f"❌ Missing required keys: {missing}")
        print(f"   Available keys: {list(result.keys())}")
        raise ValueError(f"Incomplete response - missing: {missing}")
    
    print(f"✅ All required fields present\n")
    
    # Summary
    total_time = time.time() - start_time
    num_events = len(result.get('events', []))
    num_moments = len(result.get('key_moments', []))
    num_submissions = sum(1 for e in result.get('events', []) if e.get('submission'))
    
    print(f"{'='*70}")
    print(f"✅ COMPLETED")
    print(f"{'='*70}")
    print(f"⏱️  Total Time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
    print(f"📊 Events: {num_events}")
    print(f"🎯 Key Moments: {num_moments}")
    print(f"🥋 Submissions: {num_submissions}")
    
    if num_submissions > 0:
        print(f"\nSubmissions detected:")
        for event in result['events']:
            if event.get('submission'):
                print(f"   • {event['timestamp']}s: {event['title']} ({event.get('attacker', '?')})")
    
    print(f"\n{'='*70}\n")
    
    return result, total_time


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="BJJ video processor v3 (fast).")
    parser.add_argument("video", help="path to input video file")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="output directory for clips/ and result.json (default: <video_dir>)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"Error: Video not found: {args.video}")
        raise SystemExit(1)

    out_dir = Path(args.out_dir) if args.out_dir else Path(args.video).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    result, elapsed = process_video(args.video, out_dir=out_dir)

    output_path = out_dir / "result.json"
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"💾 Saved to: {output_path}")

