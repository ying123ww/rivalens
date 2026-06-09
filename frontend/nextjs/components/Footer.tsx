import React, { useState } from 'react';
import Image from "next/image";
import Link from "next/link";
import Modal from './Settings/Modal';
import { ChatBoxSettings } from '@/types/data';

interface FooterProps {
  chatBoxSettings: ChatBoxSettings;
  setChatBoxSettings: React.Dispatch<React.SetStateAction<ChatBoxSettings>>;
}

const Footer: React.FC<FooterProps> = ({ chatBoxSettings, setChatBoxSettings }) => {
  const [showPhone, setShowPhone] = useState(false);

  // Add domain filtering from URL parameters
  if (typeof window !== 'undefined') {
    const urlParams = new URLSearchParams(window.location.search);
    const urlDomains = urlParams.get("domains");
    if (urlDomains) {
      // Split domains by comma if multiple domains are provided
      const domainArray = urlDomains.split(',').map(domain => ({
        value: domain.trim()
      }));
      localStorage.setItem('domainFilters', JSON.stringify(domainArray));
    }
  }

  return (
    <>
      <div className="container flex flex-col sm:flex-row min-h-[60px] sm:min-h-[72px] mt-2 items-center justify-center sm:justify-between border-t border-gray-700/30 px-4 pb-3 pt-4 sm:py-5 lg:px-0 bg-transparent backdrop-blur-sm gap-3 sm:gap-0">
        <Modal setChatBoxSettings={setChatBoxSettings} chatBoxSettings={chatBoxSettings} />
        <div className="text-xs sm:text-sm text-gray-100 text-center sm:text-left order-2 sm:order-1">
            © {new Date().getFullYear()} Rivalens. All rights reserved.
        </div>
        <div className="flex items-center gap-4 order-1 sm:order-2 mb-2 sm:mb-0">
          <Link href={"https://github.com/ying123ww/rivalens"} target="_blank" className="p-1">
              <svg 
                xmlns="http://www.w3.org/2000/svg" 
                viewBox="0 0 24 24" 
                fill="none" 
                stroke="currentColor" 
                strokeWidth="2" 
                strokeLinecap="round" 
                strokeLinejoin="round" 
                className="w-6 h-6 sm:w-7 sm:h-7 text-white hover:text-teal-400 transition-colors duration-300"
              >
                <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                <polyline points="9 22 9 12 15 12 15 22" />
              </svg>
          </Link>
          <Link href={"https://github.com/ying123ww/rivalens"} target="_blank" className="p-1">
            <img
              src={"/img/github.svg"}
              alt="github"
              width={24}
              height={24}
              className="w-6 h-6 sm:w-7 sm:h-7"
            />{" "}
          </Link>
          <div className="relative">
            <button
              onClick={() => setShowPhone(!showPhone)}
              className="p-1"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="w-6 h-6 sm:w-7 sm:h-7 text-white hover:text-[#0cdbb6] transition-colors duration-300"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"
                />
              </svg>
            </button>
            {showPhone && (
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 whitespace-nowrap rounded-[50px] bg-white px-5 py-2.5 text-[16px] font-[480] leading-[1.40] -tracking-[0.10px] text-black shadow-lg">
                +86 15312339659
              </div>
            )}
          </div>
          <Link href={"https://hub.docker.com/r/rivalens/rivalens"} target="_blank" className="p-1">
              <img
                src={"/img/docker.svg"}
                alt="docker"
                width={24}
                height={24}
                className="w-6 h-6 sm:w-7 sm:h-7"
              />{" "}
          </Link>
        </div>
      </div>
    </>
  );
};

export default Footer;