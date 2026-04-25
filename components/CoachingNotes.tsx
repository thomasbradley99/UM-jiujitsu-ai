import React from 'react';
import { DrawingInstruction } from './CoachingOverlay';

interface CoachingNotesProps {
  instructions: DrawingInstruction[];
}

export const CoachingNotes: React.FC<CoachingNotesProps> = ({ instructions }) => {
  if (!instructions || instructions.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 p-2 bg-black/80 text-white rounded-md text-sm border border-gray-500">
      <h4 className="font-display text-lg font-bold text-[#FFB000] mb-2">
        COACH'S NOTES:
      </h4>
      <ul className="space-y-2">
        {instructions.map((instr, index) => (
          <li key={index} className="flex items-start gap-2">
            <span style={{ color: instr.color }} className="font-bold text-xl leading-5">▪</span>
            <span className="text-gray-300">{instr.description}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};