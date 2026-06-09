"use client";

import React, { FC, useRef, useState, useEffect } from "react";
import TypeAnimation from "../../TypeAnimation";

type TInputAreaProps = {
  promptValue: string;
  setPromptValue: React.Dispatch<React.SetStateAction<string>>;
  handleSubmit: (query: string) => void;
  handleSecondary?: (query: string) => void;
  disabled?: boolean;
  reset?: () => void;
  isStopped?: boolean;
};

const InputArea: FC<TInputAreaProps> = ({
  promptValue,
  setPromptValue,
  handleSubmit,
  handleSecondary,
  disabled,
  reset,
  isStopped,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [isFocused, setIsFocused] = useState(false);
  const placeholder = "Enter your topic, question, or area of interest...";

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
  }, []);

  const resetHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "3em";
    }
  };

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    adjustHeight();
    setPromptValue(e.target.value);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && promptValue.trim()) {
        if (reset) reset();
        handleSubmit(promptValue);
        setPromptValue("");
        resetHeight();
      }
    }
  };

  const submitForm = () => {
    if (disabled || !promptValue.trim()) return;
    if (reset) reset();
    handleSubmit(promptValue);
    setPromptValue("");
    resetHeight();
  };

  if (isStopped) return null;

  return (
    <form
        className={`flex w-full items-center gap-4 rounded-[50px] border bg-white/[0.04] px-6 py-[12px] backdrop-blur-sm transition-all duration-300 ${
          isFocused
            ? "border-[#0cdbb6]/70 shadow-[0_0_40px_rgba(12,219,182,0.35)]"
            : "border-white/[0.06]"
        }`}
        onSubmit={(e) => {
          e.preventDefault();
          submitForm();
        }}
      >
      <textarea
        ref={textareaRef}
        placeholder={placeholder}
        className="my-0.5 min-h-[3em] w-full resize-none bg-transparent pl-1 pr-2 text-[18px] font-[320] leading-[1.45] -tracking-[0.26px] text-white placeholder-white/25 outline-none"
        disabled={disabled}
        value={promptValue}
        required
        rows={3}
        onKeyDown={handleKeyDown}
        onChange={handleTextareaChange}
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
      />

      <button
        disabled={disabled || !promptValue.trim()}
        type="submit"
        className="flex h-[40px] w-[40px] shrink-0 items-center justify-center rounded-full bg-white transition-all active:scale-[0.95] disabled:cursor-not-allowed disabled:bg-white/10"
      >
        {disabled ? (
          <div className="flex h-full w-full items-center justify-center">
            <TypeAnimation />
          </div>
        ) : (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-[18px] w-[18px] text-black"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M5 12h14M12 5l7 7-7 7"
            />
          </svg>
        )}
      </button>
    </form>
  );
};

export default InputArea;
