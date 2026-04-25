import React, { useState } from 'react';
import type { PersonaConfig } from '../services/anamService';
import { PERSONAS } from '../services/personas';

interface PersonaChangerProps {
  currentPersona: PersonaConfig;
  onPersonaChange: (persona: PersonaConfig) => void;
  disabled?: boolean;
  personaStatus?: 'inactive' | 'loading' | 'ready' | 'error';
}

export const PersonaChanger: React.FC<PersonaChangerProps> = ({ 
  currentPersona, 
  onPersonaChange, 
  disabled = false,
  personaStatus = 'inactive'
}) => {
  const [isOpen, setIsOpen] = useState(false);

  const handlePersonaSelect = (persona: PersonaConfig) => {
    onPersonaChange(persona);
    setIsOpen(false);
  };

  const getButtonTitle = () => {
    if (disabled) return 'Persona changer disabled';
    if (personaStatus === 'loading') return 'Switching personas...';
    return 'Change AI Persona (live switching enabled)';
  };

  const isLoading = personaStatus === 'loading';

  return (
    <div className="fixed top-4 right-20 z-50">
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={disabled || isLoading}
        className={`w-12 h-12 bg-[#C0C0C0] border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 shadow-lg flex items-center justify-center text-2xl hover:bg-[#D0D0D0] transition-colors ${
          disabled || isLoading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
        } ${isLoading ? 'animate-pulse' : ''}`}
        title={getButtonTitle()}
      >
        🎭
      </button>
      
      {isOpen && (
        <div className="absolute top-14 right-0 bg-[#C0C0C0] border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 shadow-lg min-w-[200px]">
          <div className="bg-[#355E3B] text-white font-display text-sm px-3 py-1">
            SELECT PERSONA
          </div>
          
          {PERSONAS.map((persona, index) => (
            <button
              key={index}
              onClick={() => handlePersonaSelect(persona)}
              className={`w-full px-3 py-2 text-left hover:bg-[#B0B0B0] transition-colors font-display text-sm border-b border-gray-400 last:border-b-0 ${
                currentPersona.name === persona.name ? 'bg-[#A0A0A0] font-bold' : ''
              }`}
            >
              <div className="flex items-center gap-2">
                <span>
                  {persona.name === 'Joe Rogan' ? '🎙️' : 
                   persona.name === 'Oprah Winfrey' ? '👑' :
                   persona.name === 'Rick Sanchez' ? '🧪' : '🏆'}
                </span>
                <div>
                  <div className="font-bold">{persona.name}</div>
                  <div className="text-xs text-gray-600">
                    {persona.description || persona.category}
                  </div>
                </div>
              </div>
            </button>
          ))}
          
          <div className="px-3 py-2 text-xs text-gray-600 border-t border-gray-400">
            {personaStatus === 'ready' && (
              <div className="text-green-600 mb-1">
                ✅ {currentPersona.name} is active
              </div>
            )}
            {personaStatus === 'loading' && (
              <div className="text-orange-600 mb-1">
                ⏳ Switching persona...
              </div>
            )}
            💡 Live switching enabled!
          </div>
        </div>
      )}
    </div>
  );
};