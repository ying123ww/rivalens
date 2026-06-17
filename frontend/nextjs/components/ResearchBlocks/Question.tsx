import React from 'react';
import Image from "next/image";

interface QuestionProps {
  question: string;
  homeAction?: {
    label?: string;
    title?: string;
    onClick: () => void;
  };
}

const Question: React.FC<QuestionProps> = ({ question, homeAction }) => {
  return (
    <div className="container w-full flex flex-col sm:flex-row items-start gap-3 pt-5 mb-5 px-4 sm:px-6 py-4 rounded-lg border border-gray-700/30 backdrop-blur-sm bg-gray-950/50 mt-5">
      <div className="flex items-center gap-2 sm:gap-4">
        <img
          src={"/img/message-question-circle.svg"}
          alt="message"
          width={24}
          height={24}
          className="w-6 h-6"
        />
        {/*<p className="font-bold uppercase leading-[152%] text-teal-200">
          Research Task:
        </p>*/}
      </div>
      <div className="grow text-white break-words max-w-full log-message mt-1 sm:mt-0 font-medium">{question}</div>
      {homeAction && (
        <button
          type="button"
          onClick={homeAction.onClick}
          title={homeAction.title || "Back to Home"}
          className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-gray-700/60 bg-gray-900/80 px-3 py-1.5 text-xs font-medium text-gray-300 shadow-lg shadow-black/10 transition-all duration-200 hover:border-gray-600 hover:bg-gray-800 hover:text-white focus:outline-none focus:ring-2 focus:ring-teal-500"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          {homeAction.label || "Home"}
        </button>
      )}
    </div>
  );
};

export default Question;
