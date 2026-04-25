import React from 'react';

interface ProVideoWindowProps {
  children: React.ReactNode;
}

export const ProVideoWindow: React.FC<ProVideoWindowProps> = ({ children }) => {
  return (
    <div className="bg-[#C0C0C0] border-t-2 border-l-2 border-[#F5F5DC] border-b-2 border-r-2 border-gray-500 p-1 w-full max-w-4xl shadow-2xl">
      <div 
        className="text-white p-1 flex justify-between items-center bg-[#000080]"
      >
        <div className="flex items-center gap-1.5">
           {/* Decorative elements */}
        </div>
        <h1 className="font-display tracking-widest text-2xl">PLAYER ONE CO.</h1>
      </div>
      <div className="p-1">
        {children}
      </div>
    </div>
  );
};
