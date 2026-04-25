import React, { useState, useEffect } from 'react';

const LandingPage: React.FC = () => {
  const [typedText, setTypedText] = useState('');
  const [showEnterButton, setShowEnterButton] = useState(false);
  const [isMusicPlaying, setIsMusicPlaying] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);

  const welcomeText = `C:\> INITIALIZING PLAYER ONE CO. SYSTEM...
LOADING PROJECT: PLAYER ONE CO.
ACCESS GRANTED.
_
PROJECT: Player One Co.
CREATORS: Daniel Jiang & Thomas Bradley
DESCRIPTION: An AI assistant to help you become a better player — get coaching, analysis, and actionable feedback.
_
END OF FILE. PRESS ENTER TO BEGIN...`;

  // Typing effect
  useEffect(() => {
    if (currentIndex < welcomeText.length) {
      const timer = setTimeout(() => {
        setTypedText(prev => prev + welcomeText.charAt(currentIndex));
        setCurrentIndex(currentIndex + 1);
      }, 50);
      return () => clearTimeout(timer);
    } else {
      setShowEnterButton(true);
    }
  }, [currentIndex, welcomeText]);

  const handleMusicToggle = () => {
    const bgMusic = document.getElementById('bg-music') as HTMLAudioElement;
    if (isMusicPlaying) {
      bgMusic?.pause();
      setIsMusicPlaying(false);
    } else {
      bgMusic?.play().then(() => {
        setIsMusicPlaying(true);
      }).catch(error => {
        console.error('Autoplay was prevented:', error);
      });
    }
  };

  const handleEnterSystem = () => {
    document.body.classList.add('glitch-text');
    setTimeout(() => {
      window.location.href = '/'; // Redirect to main app
    }, 500);
  };

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && showEnterButton) {
      handleEnterSystem();
    }
  };

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [showEnterButton]);

  return (
    <>
      <style>{`
        :root {
            --primary-color: #1aff00; /* Neon Green */
            --secondary-color: #00ffff; /* Cyan */
            --accent-color: #ff00ff; /* Magenta */
            --bg-color: #121212; /* Dark Gray */
            --monitor-bg: #c0c0c0; /* Gray-ish background for the main screen */
            --ui-blue: #003366; /* Dark blue for UI headers */
        }

        .landing-body {
            font-family: 'Press Start 2P', monospace;
            background-color: var(--bg-color);
            color: var(--primary-color);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            overflow: hidden;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 9999;
        }

        /* CRT/Scanline Effect */
        .landing-body::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: repeating-linear-gradient(
                to bottom,
                transparent 0px,
                transparent 1px,
                rgba(0, 0, 0, 0.2) 2px,
                rgba(0, 0, 0, 0.2) 3px
            );
            pointer-events: none;
            opacity: 0.5;
            z-index: 10;
        }

        .screen {
            width: 90vw;
            max-width: 800px;
            height: 70vh;
            border: 4px solid var(--secondary-color);
            border-radius: 1rem;
            box-shadow: 0 0 20px var(--secondary-color),
                        0 0 40px rgba(0, 255, 255, 0.5) inset;
            background-color: var(--monitor-bg);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            position: relative;
            z-index: 20;
        }

        .header {
            background-color: var(--ui-blue);
            padding: 0.5rem 1rem;
            color: white;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--accent-color);
        }
        
        .main-content {
            flex-grow: 1;
            padding: 2rem;
            color: black;
            font-size: 0.75rem;
            white-space: pre-wrap;
            overflow-y: auto;
        }

        /* Typing cursor animation */
        .cursor {
            animation: blink 1s infinite;
        }

        @keyframes blink {
            50% { opacity: 0; }
        }

        .glitch-text {
            animation: glitch 1s infinite;
        }

        @keyframes glitch {
            0%   { text-shadow: 2px 2px var(--accent-color); }
            20%  { text-shadow: -2px -2px var(--secondary-color); }
            40%  { text-shadow: 1px -1px var(--primary-color); }
            60%  { text-shadow: -1px 2px var(--accent-color); }
            80%  { text-shadow: 2px -2px var(--secondary-color); }
            100% { text-shadow: -2px 2px var(--primary-color); }
        }

        .btn {
            background-color: var(--ui-blue);
            color: white;
            padding: 0.5rem 1rem;
            border: 2px solid var(--accent-color);
            border-radius: 0.5rem;
            cursor: pointer;
            transition: all 0.2s;
            text-shadow: 2px 2px black;
        }

        .btn:hover {
            box-shadow: 0 0 10px var(--accent-color);
            background-color: #004488;
        }

        .audio-controls {
            position: absolute;
            bottom: 1rem;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 1rem;
        }
      `}</style>

      <div className="landing-body">
        {/* Background music audio element */}
        <audio id="bg-music" loop>
          <source src="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3" type="audio/mpeg" />
          Your browser does not support the audio element.
        </audio>

        <div className="screen">
          {/* Header of the retro monitor */}
          <div className="header">
            <span className="text-sm">PLAYER ONE CO. INTERFACE V1.0</span>
            <span className="text-sm">STATUS: OK</span>
          </div>

          {/* Main content area for the typing text and player data */}
          <div className="main-content">
            <span>{typedText}</span>
            {!showEnterButton && <span className="cursor">_</span>}
            {showEnterButton && (
              <>
                <br /><br />
                <span>C:\&gt; <span className="cursor">_</span></span>
              </>
            )}
          </div>

          {/* UI controls and main button */}
          <div className="audio-controls">
            <button 
              onClick={handleMusicToggle}
              className="btn"
            >
              {isMusicPlaying ? 'Pause Music' : 'Play Music'}
            </button>
            <button 
              onClick={handleEnterSystem}
              className={`btn ${!showEnterButton ? 'hidden' : ''}`}
            >
              ENTER SYSTEM
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default LandingPage;