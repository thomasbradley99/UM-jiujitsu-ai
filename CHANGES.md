# Changes to Implement

## 1. Layout Restructure
- **Move all interactive user controls to left sidebar**
  - Video upload
  - Analysis button
  - Frame capture
  - Coaching prompt input
  - Background changer
  - Persona selector
  - Video controls (play/pause/rewind/etc)
  - Progress bar
  - Analysis results/timestamps

- **Move AI coach to right sidebar**
  - Anam AI persona video window
  - Microphone toggle
  - Coach activation button
  - Persona status indicators

- **Center remains video player**
  - Main video display
  - Coaching overlays/annotations

## 2. Fighter Profile Context Step
- **Add pre-analysis step before Gemini analysis**
  - Prompt user to input fighter profiles
  - Two fighter input fields (name, fighting style, experience level, etc.)
  - Store fighter context to pass to Gemini
  - Include fighter profiles in analysis prompt for better context

- **Fighter profile fields:**
  - Fighter 1 & 2 names
  - Fighting styles (BJJ, Wrestling, MMA, etc.)
  - Experience levels
  - Notable techniques/strengths
  - Any other relevant context

## 3. Training Video Recommendations (Nice to Have)
- **After analysis is complete**
  - Generate training recommendations based on identified techniques
  - Suggest specific drills or training videos
  - Link recommendations to techniques found in analysis
  - Display in sidebar or separate section

## Implementation Priority
1. Layout restructure (left/right sidebars)
2. Fighter profile input step
3. Training recommendations (if time permits)