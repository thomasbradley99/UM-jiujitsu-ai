import React, { useRef } from 'react';

interface BackgroundChangerProps {
    onBackgroundChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
}

export const BackgroundChanger: React.FC<BackgroundChangerProps> = ({ onBackgroundChange }) => {
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleClick = () => {
        fileInputRef.current?.click();
    };

    return (
        <div className="absolute top-4 right-4 z-50">
            <input
                type="file"
                ref={fileInputRef}
                className="hidden"
                accept="image/*"
                onChange={onBackgroundChange}
            />
            <button
                onClick={handleClick}
                title="Change Background"
                className="w-10 h-10 bg-[#C0C0C0] text-black border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 flex items-center justify-center hover:bg-gray-400 active:border-t-2 active:border-l-2 active:border-gray-500 active:border-b-2 active:border-r-2 active:border-[#F5F5DC]"
            >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
            </button>
        </div>
    );
};
