"use client";

import React, { FC, useEffect, useState } from "react";
import InputArea from "./ResearchBlocks/elements/InputArea";
import { motion } from "framer-motion";

type THeroProps = {
  promptValue: string;
  setPromptValue: React.Dispatch<React.SetStateAction<string>>;
  handleDisplayResult: (query: string) => void;
};

const Hero: FC<THeroProps> = ({
  promptValue,
  setPromptValue,
  handleDisplayResult,
}) => {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    setIsVisible(true);
  }, []);

  const handleClickSuggestion = (value: string) => {
    setPromptValue(value);
    const element = document.getElementById("input-area");
    if (element) {
      element.scrollIntoView({ behavior: "smooth" });
    }
  };

  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-gray-950 px-5 py-20">
      {/* Single pastel color block — Figma poster-on-black-wall */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute right-[-120px] top-[55%] -translate-y-1/2 h-[500px] w-[500px] rotate-[-12deg] rounded-[32px] bg-[#c5b0f4] opacity-[0.08]" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={isVisible ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.8 }}
        className="relative z-10 flex w-full max-w-[1280px] flex-col items-center text-center"
      >
        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={isVisible ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.06 }}
          className="max-w-3xl text-[48px] font-light leading-[1.05] -tracking-[0.96px] text-white sm:text-[64px] md:text-[80px] md:-tracking-[1.44px]"
        >
          What would you like to research next?
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 12 }}
          animate={isVisible ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.12 }}
          className="mt-6 text-[18px] font-light leading-[1.45] -tracking-[0.26px] text-white/40"
        >
          Rivalens may make mistakes. Verify important information and check sources.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={isVisible ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="relative mt-14 w-full max-w-[680px]"
          id="input-area"
        >
          <div className="absolute -inset-4 -z-10 rounded-[40px] bg-[#c5b0f4] opacity-[0.06] blur-2xl" />

          <InputArea
            promptValue={promptValue}
            setPromptValue={setPromptValue}
            handleSubmit={handleDisplayResult}
          />
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={isVisible ? { opacity: 1 } : {}}
          transition={{ duration: 0.5, delay: 0.35 }}
          className="mt-10 flex flex-wrap items-center justify-center gap-3"
        >
          {suggestions.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => handleClickSuggestion(item.name)}
              className="flex items-center gap-2 rounded-[50px] px-5 py-[10px] text-[16px] font-[480] leading-[1.40] -tracking-[0.10px] transition-all active:scale-[0.97]"
              style={{
                backgroundColor: item.color,
                color: "#000000",
              }}
            >
              <img
                src={item.icon}
                alt=""
                width={18}
                height={18}
                className="w-[18px] opacity-70"
                style={{ filter: "brightness(0)" }}
              />
              <span>{item.name}</span>
            </button>
          ))}
        </motion.div>
      </motion.div>
    </main>
  );
};

type Suggestion = {
  id: number;
  name: string;
  icon: string;
  color: string;
};

const suggestions: Suggestion[] = [
  { id: 1, name: "DingTalk vs Feishu ", icon: "/img/stock2.svg", color: "#dceeb1" },
  { id: 2, name: "Analyze Stripe pricing ", icon: "/img/hiker.svg", color: "#c5b0f4" },
  { id: 3, name: "Tesla in China market ", icon: "/img/news.svg", color: "#efd4d4" },
];

export default Hero;
