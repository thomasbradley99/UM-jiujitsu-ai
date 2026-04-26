DOMAIN RULE — BJJ TRAINING ROUND FINISH:
You must evaluate the entire video duration using strict, continuous, non-overlapping sliding windows to ensure no temporal gaps exist. Any gap or oversight in the timeline will result in a False Negative.

A submission is confirmed by ANY of:
  (a) a clear tap (hand/foot tapping mat or partner),
  (b) a verbal yield,
  (c) the partner being put to sleep, OR
  (d) a RESET signal (pair stops, separates, fist bump, both stand up).

CRITICAL DISTINCTION & LOGIC:
1. SUBMISSION VS. NEUTRAL: You must strictly distinguish between tactical submission finishes and neutral match events (resets, separations, or post-round fist bumps). 
2. ATTRIBUTION: If a reset/separation occurs, determine if it concludes an interaction where one party held dominant positional control or applied pressure in the final 3-5 seconds. Only if a clear winner or dominant position is established at the end of the window should this count as a submission.
3. FALSE NEGATIVES: Only return is_submission=false if the clip shows continuous, active grappling the entire {window_sec} seconds with NO submission evidence AND no neutral termination of a dominant sequence.
4. GRANULARITY: When analyzing, differentiate between successful submissions (taps) and neutral resets/separations. Assign 'is_submission=true' only when a high-probability end-of-round state is reached through dominance.