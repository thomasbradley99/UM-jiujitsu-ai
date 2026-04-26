DOMAIN RULE — BJJ TRAINING ROUND FINISH:
You must evaluate the entire video duration using strict, continuous, non-overlapping sliding windows to ensure zero temporal gaps. Any gap in the timeline will result in a failure.

SUBMISSION CONFIRMATION CRITERIA:
A submission is confirmed by:
  (a) a clear tap (hand/foot against mat or partner),
  (b) a verbal yield,
  (c) the partner being put to sleep, OR
  (d) an unambiguous end-of-round signal (pair stops, separates, performs a fist bump, or resets).

CRITICAL LOGIC & DISCRIMINATION:
1. SUBMISSION VS. NEUTRAL: You must explicitly distinguish between active submission finishes and neutral match events. If a reset or separation occurs, it is only a 'submission' if it concludes a sequence where one party exerted clear, sustained, dominant positional control or significant pressure in the final 3-5 seconds.
2. FALSE NEGATIVE AVOIDANCE: Only return is_submission=false if the clip shows continuous, active grappling throughout the {window_sec} second window without a tap AND without any neutral termination of a dominant sequence.
3. GRANULARITY: Differentiate clearly between successful submissions (taps) and routine neutral resets or separations. Do not label random resets as submissions unless they clearly finalize a dominant exchange.
4. TEMPORAL INTEGRITY: You must ensure every second of the video is accounted for in your analysis windows. Any oversight in the timeline renders the analysis invalid.