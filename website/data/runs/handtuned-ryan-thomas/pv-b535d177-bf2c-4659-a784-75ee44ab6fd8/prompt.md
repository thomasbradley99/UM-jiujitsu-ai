DOMAIN RULE — BJJ TRAINING ROUND FINISH:
Rounds in training do not end mid-roll without a submission. You must evaluate the entire video duration using continuous, non-overlapping sliding windows to ensure no temporal gaps occur, as these lead to False Negatives.

A submission is confirmed by ANY of:
  (a) a clear tap (hand/foot tapping mat or partner),
  (b) a verbal yield,
  (c) the partner being put to sleep, OR
  (d) a RESET signal (pair stops, separates, fist bump, both stand up). The reset is a valid proxy for a finished interaction.

CRITICAL DISTINCTION:
You must explicitly distinguish between tactical submission attempts and neutral end-of-round interactions (e.g., separations, fist-bumps, resets). A neutral interaction only counts as a 'submission' if it indicates the end of a round sequence where one party held dominant positional control.

Attribute the submission to whoever was applying pressure or held dominant positional control in the final 3-5 seconds before the reset/tap.

Only return is_submission=false if the clip shows continuous, active grappling the entire {window_sec} seconds with NO submission evidence and NO neutral reset/end-of-round behaviour.