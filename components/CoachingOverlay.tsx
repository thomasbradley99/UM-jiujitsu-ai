import React from 'react';

export interface DrawingInstruction {
  type: 'arrow' | 'circle' | 'text';
  color: string;
  description: string;
  start?: { x: number; y: number };
  end?: { x: number; y: number };
  center?: { x: number; y: number };
  radius?: number;
  position?: { x: number; y: number };
  content?: string;
}

interface CoachingOverlayProps {
  instructions: DrawingInstruction[];
  videoDimensions: { width: number; height: number };
}

export const CoachingOverlay: React.FC<CoachingOverlayProps> = ({ instructions, videoDimensions }) => {
  const { width, height } = videoDimensions;

  if (!width || !height || instructions.length === 0) {
    return null;
  }
  
  // Use a consistent stroke width relative to video size
  const strokeWidth = Math.max(2, Math.min(width, height) * 0.005);
  const fontSize = Math.max(12, Math.min(width, height) * 0.03);

  return (
    <svg 
        className="absolute top-0 left-0 w-full h-full pointer-events-none"
        viewBox={`0 0 ${width} ${height}`}
        style={{ filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.7))' }}
    >
      <defs>
        <marker
          id="arrowhead"
          markerWidth="10"
          markerHeight="7"
          refX="0"
          refY="3.5"
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill="currentColor" />
        </marker>
      </defs>

      {instructions.map((instr, index) => {
        const key = `instr-${index}`;
        switch (instr.type) {
          case 'arrow':
            if (!instr.start || !instr.end) return null;
            return (
              <line
                key={key}
                x1={instr.start.x * width}
                y1={instr.start.y * height}
                x2={instr.end.x * width}
                y2={instr.end.y * height}
                stroke={instr.color}
                strokeWidth={strokeWidth}
                markerEnd="url(#arrowhead)"
                strokeLinecap="round"
                style={{ color: instr.color }}
              />
            );
          case 'circle':
            if (!instr.center || !instr.radius) return null;
            return (
              <circle
                key={key}
                cx={instr.center.x * width}
                cy={instr.center.y * height}
                r={instr.radius * width} // Radius relative to width for consistency
                stroke={instr.color}
                strokeWidth={strokeWidth}
                fill="none"
              />
            );
          case 'text':
             if (!instr.position || !instr.content) return null;
             return (
                <text
                    key={key}
                    x={instr.position.x * width}
                    y={instr.position.y * height}
                    fill={instr.color}
                    fontSize={fontSize}
                    fontWeight="bold"
                    textAnchor="middle"
                    dominantBaseline="middle"
                    stroke="black"
                    strokeWidth={strokeWidth / 2}
                    paintOrder="stroke"
                >
                    {instr.content}
                </text>
             );
          default:
            return null;
        }
      })}
    </svg>
  );
};