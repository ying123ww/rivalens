"use client";

import React, { useRef, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useWebSocket } from '@/hooks/useWebSocket';
import { useResearchHistoryContext } from '@/hooks/ResearchHistoryContext';
import { useScrollHandler } from '@/hooks/useScrollHandler';
import {
  AnalysisDirection,
  Data,
  ChatBoxSettings,
  IndustryDirectionPlan,
  QuestionData,
  ChatMessage,
  ChatData
} from '../types/data';
import { preprocessOrderedData } from '../utils/dataProcessing';
import { toast } from "react-hot-toast";

import Hero from "@/components/Hero";
import ResearchPageLayout from "@/components/layouts/ResearchPageLayout";
import CopilotLayout from "@/components/layouts/CopilotLayout";
import ResearchContent from "@/components/research/ResearchContent";
import CopilotResearchContent from "@/components/research/CopilotResearchContent";
import HumanFeedback from "@/components/HumanFeedback";
import ResearchSidebar from "@/components/ResearchSidebar";
import { getAppropriateLayout } from "@/utils/getLayout";

// Import the mobile components
import MobileHomeScreen from "@/components/mobile/MobileHomeScreen";
import MobileResearchContent from "@/components/mobile/MobileResearchContent";

export default function Home() {
  const router = useRouter();
  const [promptValue, setPromptValue] = useState("");
  const [chatPromptValue, setChatPromptValue] = useState("");
  const [showResult, setShowResult] = useState(false);
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [isInChatMode, setIsInChatMode] = useState(false);
  const [chatBoxSettings, setChatBoxSettings] = useState<ChatBoxSettings>(() => {
    // Default settings
    const defaultSettings = {
      report_type: "rivalens",
      report_source: "web",
      tone: "Objective",
      domains: [],
      defaultReportType: "rivalens",
      layoutType: 'copilot',
      mcp_enabled: false,
      mcp_configs: [],
      mcp_strategy: "fast",
      industry_direction_plan: undefined,
    };

    // Try to load all settings from localStorage
    if (typeof window !== 'undefined') {
      const savedSettings = localStorage.getItem('chatBoxSettings');
      if (savedSettings) {
        try {
          const parsedSettings = JSON.parse(savedSettings);
          return {
            ...defaultSettings,
            ...parsedSettings, // Override defaults with saved settings
            report_type: "rivalens",
            defaultReportType: "rivalens",
          };
        } catch (e) {
          console.error('Error parsing saved settings:', e);
        }
      }
    }
    return defaultSettings;
  });
  const [question, setQuestion] = useState("");
  const [orderedData, setOrderedData] = useState<Data[]>([]);
  const [showHumanFeedback, setShowHumanFeedback] = useState(false);
  const [questionForHuman, setQuestionForHuman] = useState<true | false>(false);
  const [allLogs, setAllLogs] = useState<any[]>([]);
  const [isStopped, setIsStopped] = useState(false);
  const mainContentRef = useRef<HTMLDivElement>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [currentResearchId, setCurrentResearchId] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [isProcessingChat, setIsProcessingChat] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [industryDirectionPlan, setIndustryDirectionPlan] = useState<IndustryDirectionPlan | null>(null);
  const [customDirectionText, setCustomDirectionText] = useState("");
  const [showCustomDirections, setShowCustomDirections] = useState(false);
  const [isPreparingPlan, setIsPreparingPlan] = useState(false);

  // Use our custom scroll handler
  const { showScrollButton, scrollToBottom } = useScrollHandler(mainContentRef);

  // Check if we're on mobile
  useEffect(() => {
    const checkIfMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };
    
    // Initial check
    checkIfMobile();
    
    // Add event listener for window resize
    window.addEventListener('resize', checkIfMobile);
    
    // Cleanup
    return () => window.removeEventListener('resize', checkIfMobile);
  }, []);

  const { 
    history, 
    saveResearch, 
    updateResearch,
    getResearchById, 
    deleteResearch,
    addChatMessage,
    getChatMessages
  } = useResearchHistoryContext();

  // Initialize the WebSocket hook without connecting until a run starts.
  const { socket, initializeWebSocket } = useWebSocket(
    setOrderedData,
    setAnswer,
    setLoading,
    setShowHumanFeedback,
    setQuestionForHuman,
    setCurrentResearchId
  );

  const handleFeedbackSubmit = (feedback: string | null) => {
    if (socket) {
      socket.send(JSON.stringify({ type: 'human_feedback', content: feedback }));
    }
    setShowHumanFeedback(false);
  };

  const handleChat = async (message: string) => {
    if (!currentResearchId && !answer) {
      // On mobile, if there's no research yet, treat this as a new research request
      if (isMobile) {
        // Show immediate feedback for better UX
        setShowResult(true);
        setPromptValue(message); // Keep the message visible
        
        // Start the research with the chat message
        handleDisplayResult(message);
        return;
      }
    }
    
    setShowResult(true);
    setIsProcessingChat(true);
    setChatPromptValue("");
    
    // Create a user message
    const userMessage: ChatMessage = {
      role: 'user',
      content: message,
      timestamp: Date.now()
    };
    
    // Add question to display in research results immediately
    const questionData: QuestionData = { type: 'question', content: message };
    setOrderedData(prevOrder => [...prevOrder, questionData]);
    
    // Add user message to history asynchronously
    if (currentResearchId) {
      addChatMessage(currentResearchId, userMessage).catch(error => {
        console.error('Error adding chat message to history:', error);
      });
    }
    
    // Mobile implementation - simplified for chat only
    if (isMobile) {
      try {
        // Direct API call instead of websockets
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            messages: [{ role: 'user', content: message }],
            report: answer || '',
          }),
        });
        
        if (!response.ok) {
          throw new Error(`API error: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.response && data.response.content) {
          // Add AI response to chat history asynchronously
          if (currentResearchId) {
            addChatMessage(currentResearchId, data.response).catch(error => {
              console.error('Error adding AI response to history:', error);
            });
            
            // Also update the research with the new messages
            const chatData: ChatData = { 
              type: 'chat', 
              content: data.response.content,
              metadata: data.response.metadata 
            };
            
            setOrderedData(prevOrder => [...prevOrder, chatData]);
            
            // Get current ordered data and add new messages
            const updatedOrderedData = [...orderedData, questionData, chatData];
            
            // Update research in history
            updateResearch(
              currentResearchId, 
              answer, 
              updatedOrderedData
            ).catch(error => {
              console.error('Error updating research:', error);
            });
          } else {
            // If no research ID, just update the UI
            setOrderedData(prevOrder => [...prevOrder, { 
              type: 'chat', 
              content: data.response.content,
              metadata: data.response.metadata
            } as ChatData]);
          }
        } else {
          // Show error message
          setOrderedData(prevOrder => [...prevOrder, { 
            type: 'chat', 
            content: 'Sorry, something went wrong. Please try again.' 
          } as ChatData]);
        }
      } catch (error) {
        console.error('Error during chat:', error);
        
        // Add error message
        setOrderedData(prevOrder => [...prevOrder, { 
          type: 'chat', 
          content: 'Sorry, there was an error processing your request. Please try again.' 
        } as ChatData]);
      } finally {
        setIsProcessingChat(false);
      }
      return;
    }
    
    // Desktop implementation (unchanged)
    try {
      // Fetch all chat messages for this research
      let chatMessages: { role: string; content: string }[] = [];
      
      if (currentResearchId) {
        // If we have a research ID, get all messages from history
        chatMessages = getChatMessages(currentResearchId);
      }
      
      // Format messages to ensure they only contain role and content properties
      const formattedMessages = [...chatMessages, userMessage].map(msg => ({
        role: msg.role,
        content: msg.content
      }));
      
      // Call the chat API
      const response = await fetch(`/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          report: answer || "",
          messages: formattedMessages
        }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to get chat response: ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.response) {
        // Check if response contains valid content
        if (!data.response.content) {
          console.error('Response content is null or empty');
          // Show error message in results
          setOrderedData(prevOrder => [...prevOrder, { 
            type: 'chat', 
            content: 'I apologize, but I couldn\'t generate a proper response. Please try asking your question again.' 
          }]);
        } else {
          // Add AI response to chat history asynchronously
          if (currentResearchId) {
            addChatMessage(currentResearchId, data.response).catch(error => {
              console.error('Error adding AI response to history:', error);
            });
          }
          
          // Add response to display in research results
          setOrderedData(prevOrder => {
            return [...prevOrder, { 
              type: 'chat', 
              content: data.response.content,
              metadata: data.response.metadata
            }];
          });
        }
        
        // Explicitly enable chat mode after getting a response
        if (!isInChatMode) {
          setIsInChatMode(true);
        }
      } else {
        // Show error message
        setOrderedData(prevOrder => [...prevOrder, { 
          type: 'chat', 
          content: 'Sorry, something went wrong. Please try again.' 
        }]);
      }
    } catch (error) {
      console.error('Error during chat:', error);
      
      // Add error message to display
      setOrderedData(prevOrder => [...prevOrder, { 
        type: 'chat', 
        content: 'Sorry, there was an error processing your request. Please try again.' 
      }]);
    } finally {
      setLoading(false);
      setIsProcessingChat(false);
    }
  };

  const previewIndustryDirections = async (
    newQuestion: string,
    customDirections: string[] = [],
    selectedDirectionIds?: string[],
    confirmed = false
  ) => {
    const response = await fetch('/api/industry-directions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task: newQuestion,
        custom_directions: customDirections,
        selected_direction_ids: selectedDirectionIds,
        confirmed
      }),
    });

    if (!response.ok) {
      let detail = `Failed to prepare analysis directions: ${response.status}`;
      try {
        const body = await response.json();
        if (body.detail) detail = body.detail;
      } catch {}
      throw new Error(detail);
    }

    const data = await response.json();
    return data.plan as IndustryDirectionPlan;
  };

  const parseCustomDirections = (value: string) => {
    return value
      .split(/\n|,|，|;|；|以及|还有|和|与|、/)
      .map((item) => item.trim())
      .filter(Boolean);
  };

  const startResearchWithPlan = (
    newQuestion: string,
    plan?: IndustryDirectionPlan
  ) => {
    // Exit chat mode when starting a new research
    setIsInChatMode(false);
    setShowResult(true);
    setLoading(true);
    setQuestion(newQuestion);
    setPromptValue("");
    setAnswer("");
    setCurrentResearchId(null); // Reset current research ID for new research
    setOrderedData((prevOrder) => [...prevOrder, { type: 'question', content: newQuestion }]);

    const rivalensSettings = {
      ...chatBoxSettings,
      report_type: 'rivalens',
      defaultReportType: 'rivalens',
      industry_direction_plan: plan,
    };
    setChatBoxSettings(rivalensSettings);
    initializeWebSocket(newQuestion, rivalensSettings);
  };

  const handleDisplayResult = async (newQuestion: string) => {
    if (!newQuestion.trim()) return;

    setIsPreparingPlan(true);
    try {
      const plan = await previewIndustryDirections(newQuestion);
      setPendingQuestion(newQuestion);
      setIndustryDirectionPlan(plan);
      setCustomDirectionText("");
      setShowCustomDirections(false);
    } catch (error) {
      console.error('Error preparing industry directions:', error);
      const message = error instanceof Error ? error.message : 'Could not prepare analysis directions.';
      toast.error(message);
      // Don't fall through to research — let the user correct their query.
    } finally {
      setIsPreparingPlan(false);
    }
  };

  const handleConfirmIndustryDirections = async (selectedDirectionIds?: string[]) => {
    if (!pendingQuestion) return;

    setIsPreparingPlan(true);
    try {
      const customDirections = parseCustomDirections(customDirectionText);
      const finalPlan = await previewIndustryDirections(
        pendingQuestion,
        customDirections,
        selectedDirectionIds,
        true
      );
      setIndustryDirectionPlan(null);
      setPendingQuestion(null);
      setShowCustomDirections(false);
      setCustomDirectionText("");
      startResearchWithPlan(pendingQuestion, finalPlan);
    } catch (error) {
      console.error('Error confirming industry directions:', error);
      toast.error('Could not confirm analysis directions. Please try again.');
    } finally {
      setIsPreparingPlan(false);
    }
  };

  const handleCancelIndustryDirections = () => {
    setIndustryDirectionPlan(null);
    setPendingQuestion(null);
    setShowCustomDirections(false);
    setCustomDirectionText("");
  };

  // Mobile-specific implementation for research
  const handleMobileDisplayResult = async (newQuestion: string) => {
    await handleDisplayResult(newQuestion);
  };

  // Mobile-specific chat handler
  const handleMobileChat = async (message: string) => {
    // Set states for UI feedback
    setIsProcessingChat(true);
    
    // Format user message
    const userMessage = {
      role: 'user',
      content: message
    };
    
    // Add question to UI immediately
    const questionData: QuestionData = { 
      type: 'question', 
      content: message 
    };
    
    setOrderedData(prevOrder => [...prevOrder, questionData]);
    
    try {
      // Direct API call instead of websockets
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          messages: [userMessage],
          report: answer || '',
          report_source: chatBoxSettings.report_source || 'web',
          tone: chatBoxSettings.tone || 'Objective'
        }),
        // Set reasonable timeout
        signal: AbortSignal.timeout(20000) // 20-second timeout
      });
      
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.response && data.response.content) {
        // Add AI response to chat history asynchronously
        if (currentResearchId) {
          addChatMessage(currentResearchId, data.response).catch(error => {
            console.error('Error adding AI response to history:', error);
          });
          
          // Also update the research with the new messages
          const chatData: ChatData = { 
            type: 'chat', 
            content: data.response.content,
            metadata: data.response.metadata 
          };
          
          setOrderedData(prevOrder => [...prevOrder, chatData]);
          
          // Get current ordered data and add new messages
          const updatedOrderedData = [...orderedData, questionData, chatData];
          
          // Update research in history
          updateResearch(
            currentResearchId, 
            answer, 
            updatedOrderedData
          ).catch(error => {
            console.error('Error updating research:', error);
          });
        } else {
          // If no research ID, just update the UI
          setOrderedData(prevOrder => [...prevOrder, { 
            type: 'chat', 
            content: data.response.content,
            metadata: data.response.metadata
          } as ChatData]);
        }
      } else {
        // Show error message
        setOrderedData(prevOrder => [...prevOrder, { 
          type: 'chat', 
          content: 'Sorry, something went wrong. Please try again.' 
        } as ChatData]);
      }
    } catch (error) {
      console.error('Error during mobile chat:', error);
      
      // Add error message
      setOrderedData(prevOrder => [...prevOrder, { 
        type: 'chat', 
        content: 'Sorry, there was an error processing your request. Please try again.' 
      } as ChatData]);
    } finally {
      setIsProcessingChat(false);
      setChatPromptValue('');
    }
  };

  const reset = () => {
    // Reset UI states
    setShowResult(false);
    setPromptValue("");
    setIsStopped(false);
    setIsInChatMode(false);
    setCurrentResearchId(null); // Reset research ID
    setIsProcessingChat(false);
    
    // Clear previous research data
    setQuestion("");
    setAnswer("");
    setOrderedData([]);
    setAllLogs([]);

    // Reset feedback states
    setShowHumanFeedback(false);
    setQuestionForHuman(false);
    
    // Clean up connections
    if (socket) {
      socket.close();
    }
    setLoading(false);
  };

  const handleClickSuggestion = (value: string) => {
    setPromptValue(value);
    const element = document.getElementById('input-area');
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' });
    }
  };

  /**
   * Handles stopping the current research
   * - Closes WebSocket connection
   * - Stops loading state
   * - Marks research as stopped
   * - Preserves current results
   * - Reloads the page to fully reset the connection
   */
  const handleStopResearch = () => {
    if (socket) {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send("stop");
        window.setTimeout(() => socket.close(1000, "User stopped research"), 50);
      } else {
        socket.close();
      }
    }
    setLoading(false);
    setIsStopped(true);
    
    // Reload the page to completely reset the socket connection
    window.setTimeout(() => window.location.reload(), 100);
  };

  /**
   * Handles starting a new research
   * - Clears all previous research data and states
   * - Resets UI to initial state
   * - Closes any existing WebSocket connections
   */
  const handleStartNewResearch = () => {
    reset();
    setSidebarOpen(false);
  };

  const handleCopyUrl = () => {
    if (!currentResearchId) return;
    
    const url = `${window.location.origin}/research/${currentResearchId}`;
    navigator.clipboard.writeText(url)
      .then(() => {
        toast.success("URL copied to clipboard!");
      })
      .catch(() => {
        toast.error("Failed to copy URL");
      });
  };

  // Add a ref to track if an update is in progress to prevent infinite loops
  const isUpdatingRef = useRef(false);

  // Save or update research in history based on mode
  useEffect(() => {
    // Define an async function inside the effect
    const saveOrUpdateResearch = async () => {
      // Prevent infinite loops by checking if we're already updating
      if (isUpdatingRef.current) return;
      
      if (showResult && !loading && answer && question && orderedData.length > 0) {
        if (isInChatMode && currentResearchId) {
          // Prevent redundant updates by checking if data has changed
          try {
            const currentResearch = await getResearchById(currentResearchId);
            if (currentResearch && (currentResearch.answer !== answer || JSON.stringify(currentResearch.orderedData) !== JSON.stringify(orderedData))) {
              isUpdatingRef.current = true;
              await updateResearch(currentResearchId, answer, orderedData);
              // Reset the flag after a short delay to allow state updates to complete
              setTimeout(() => {
                isUpdatingRef.current = false;
              }, 100);
            }
          } catch (error) {
            console.error('Error updating research:', error);
            isUpdatingRef.current = false;
          }
        } else if (!isInChatMode) {
          // Check if this is a new research (not loaded from history)
          const isNewResearch = !history.some(item => 
            item.question === question && item.answer === answer
          );
          
          if (isNewResearch) {
            isUpdatingRef.current = true;
            try {
              const newId = await saveResearch(question, answer, orderedData);
              setCurrentResearchId(newId);
              
              // Don't navigate to the research page URL anymore
              // Just save the ID for sharing purposes
              
            } catch (error) {
              console.error('Error saving research:', error);
            } finally {
              // Reset the flag after a short delay to allow state updates to complete
              setTimeout(() => {
                isUpdatingRef.current = false;
              }, 100);
            }
          }
        }
      }
    };
    
    // Call the async function
    saveOrUpdateResearch();
  }, [showResult, loading, answer, question, orderedData, history, saveResearch, updateResearch, isInChatMode, currentResearchId, getResearchById]);

  // Handle selecting a research from history
  const handleSelectResearch = async (id: string) => {
    try {
      const research = await getResearchById(id);
      if (research) {
        // Navigate to the research page instead of loading it here
        router.push(`/research/${id}`);
      }
    } catch (error) {
      console.error('Error selecting research:', error);
      toast.error('Could not load the selected research');
    }
  };

  // Toggle sidebar
  const toggleSidebar = () => {
    setSidebarOpen(!sidebarOpen);
  };

  /**
   * Processes ordered data into logs for display
   * Updates whenever orderedData changes
   */
  useEffect(() => {
    const groupedData = preprocessOrderedData(orderedData);
    const statusReports = [
      "agent_generated",
      "starting_research",
      "planning_research",
      "run_started",
      "heartbeat",
      "log_batch",
      "websocket_disconnected",
      "run_cancelled",
      "error",
    ];
    const logText = (data: any) => {
      if (data.content !== "log_batch") {
        return data.output;
      }
      const latest = data.metadata?.latest;
      if (!Array.isArray(latest) || latest.length === 0) {
        return data.output;
      }
      return latest
        .map((item: any) => `${item.content || "log"}: ${item.output || ""}`)
        .join("\n");
    };
    
    const newLogs = groupedData.reduce((acc: any[], data) => {
      // Process accordion blocks (grouped data)
      if (data.type === 'accordionBlock') {
        const logs = data.items.map((item: any, subIndex: any) => ({
          header: item.content,
          text: item.output,
          metadata: item.metadata,
          key: `${item.type}-${item.content}-${subIndex}`,
        }));
        return [...acc, ...logs];
      } 
      // Process status reports
      else if (statusReports.includes(data.content)) {
        return [...acc, {
          header: data.content,
          text: logText(data),
          metadata: data.metadata,
          key: `${data.type}-${data.content}`,
        }];
      }
      return acc;
    }, []);
    
    setAllLogs(newLogs);
  }, [orderedData]);

  // Save chatBoxSettings to localStorage when they change
  useEffect(() => {
    localStorage.setItem('chatBoxSettings', JSON.stringify(chatBoxSettings));
  }, [chatBoxSettings]);

  // Set chat mode when a report is complete
  useEffect(() => {
    if (showResult && !loading && answer && !isInChatMode) {
      setIsInChatMode(true);
    }
  }, [showResult, loading, answer, isInChatMode]);

  // Update the renderMobileContent function to use both mobile-specific functions
  const renderMobileContent = () => {
    if (!showResult) {
      return (
        <MobileHomeScreen
          promptValue={promptValue}
          setPromptValue={setPromptValue}
          handleDisplayResult={handleMobileDisplayResult}
          isLoading={loading}
        />
      );
    } else {
      return (
        <MobileResearchContent
          orderedData={orderedData}
          answer={answer}
          loading={loading}
          isStopped={isStopped}
          chatPromptValue={chatPromptValue}
          setChatPromptValue={setChatPromptValue}
          handleChat={handleMobileChat} // Use mobile-specific chat handler
          isProcessingChat={isProcessingChat}
          onNewResearch={handleStartNewResearch}
          currentResearchId={currentResearchId || undefined}
          onShareClick={currentResearchId ? handleCopyUrl : undefined}
        />
      );
    }
  };

  return (
    <>
      {isMobile ? (
        // Mobile view - simplified layout with focus on chat
        getAppropriateLayout({
          loading,
          isStopped,
          showResult,
          onStop: handleStopResearch,
          onNewResearch: handleStartNewResearch,
          chatBoxSettings,
          setChatBoxSettings,
          mainContentRef,
          toggleSidebar,
          isProcessingChat,
          children: renderMobileContent()
        })
      ) : !showResult ? (
        // Desktop view - home page
        getAppropriateLayout({
          loading,
          isStopped,
          showResult,
          onStop: handleStopResearch,
          onNewResearch: handleStartNewResearch,
          chatBoxSettings,
          setChatBoxSettings,
          mainContentRef,
          showScrollButton,
          onScrollToBottom: scrollToBottom,
          children: (
            <>
              <ResearchSidebar
                history={history}
                onSelectResearch={handleSelectResearch}
                onNewResearch={handleStartNewResearch}
                onDeleteResearch={deleteResearch}
                isOpen={sidebarOpen}
                toggleSidebar={toggleSidebar}
              />
              
              <Hero
                promptValue={promptValue}
                setPromptValue={setPromptValue}
                handleDisplayResult={handleDisplayResult}
              />
            </>
          )
        })
      ) : (
        // Desktop view - research results
        getAppropriateLayout({
          loading,
          isStopped,
          showResult,
          onStop: handleStopResearch,
          onNewResearch: handleStartNewResearch,
          chatBoxSettings,
          setChatBoxSettings,
          mainContentRef,
          children: (
            <div className="relative">
              <ResearchSidebar
                history={history}
                onSelectResearch={handleSelectResearch}
                onNewResearch={handleStartNewResearch}
                onDeleteResearch={deleteResearch}
                isOpen={sidebarOpen}
                toggleSidebar={toggleSidebar}
              />
              
              {chatBoxSettings.layoutType === 'copilot' ? (
                <CopilotResearchContent
                  orderedData={orderedData}
                  answer={answer}
                  allLogs={allLogs}
                  chatBoxSettings={chatBoxSettings}
                  loading={loading}
                  isStopped={isStopped}
                  promptValue={promptValue}
                  chatPromptValue={chatPromptValue}
                  setPromptValue={setPromptValue}
                  setChatPromptValue={setChatPromptValue}
                  handleDisplayResult={handleDisplayResult}
                  handleChat={handleChat}
                  handleClickSuggestion={handleClickSuggestion}
                  currentResearchId={currentResearchId || undefined}
                  onShareClick={currentResearchId ? handleCopyUrl : undefined}
                  reset={reset}
                  isProcessingChat={isProcessingChat}
                  onNewResearch={handleStartNewResearch}
                  toggleSidebar={toggleSidebar}
                />
              ) : (
                <ResearchContent
                  showResult={showResult}
                  orderedData={orderedData}
                  answer={answer}
                  allLogs={allLogs}
                  chatBoxSettings={chatBoxSettings}
                  loading={loading}
                  isInChatMode={isInChatMode}
                  isStopped={isStopped}
                  promptValue={promptValue}
                  chatPromptValue={chatPromptValue}
                  setPromptValue={setPromptValue}
                  setChatPromptValue={setChatPromptValue}
                  handleDisplayResult={handleDisplayResult}
                  handleChat={handleChat}
                  handleClickSuggestion={handleClickSuggestion}
                  currentResearchId={currentResearchId || undefined}
                  onShareClick={currentResearchId ? handleCopyUrl : undefined}
                  reset={reset}
                  isProcessingChat={isProcessingChat}
                />
              )}
              
              {showHumanFeedback && false && (
                <HumanFeedback
                  questionForHuman={questionForHuman}
                  websocket={socket}
                  onFeedbackSubmit={handleFeedbackSubmit}
                />
              )}
            </div>
          )
        })
      )}
      {industryDirectionPlan && pendingQuestion && (
        <IndustryDirectionDialog
          plan={industryDirectionPlan}
          customDirectionText={customDirectionText}
          setCustomDirectionText={setCustomDirectionText}
          showCustomDirections={showCustomDirections}
          setShowCustomDirections={setShowCustomDirections}
          isPreparingPlan={isPreparingPlan}
          onConfirm={handleConfirmIndustryDirections}
          onCancel={handleCancelIndustryDirections}
        />
      )}
    </>
  );
}

type IndustryDirectionDialogProps = {
  plan: IndustryDirectionPlan;
  customDirectionText: string;
  setCustomDirectionText: React.Dispatch<React.SetStateAction<string>>;
  showCustomDirections: boolean;
  setShowCustomDirections: React.Dispatch<React.SetStateAction<boolean>>;
  isPreparingPlan: boolean;
  onConfirm: (selectedDirectionIds?: string[]) => void;
  onCancel: () => void;
};

function IndustryDirectionDialog({
  plan,
  customDirectionText,
  setCustomDirectionText,
  showCustomDirections,
  setShowCustomDirections,
  isPreparingPlan,
  onConfirm,
  onCancel,
}: IndustryDirectionDialogProps) {
  const scopeLimitedByQuery = Boolean(
    plan.final_analysis_plan?.scope_limited_by_query
  );
  const baseDirections = plan.suggested_directions?.length
    ? plan.suggested_directions
    : plan.default_directions;
  const visibleBaseDirections = scopeLimitedByQuery
    ? plan.final_directions
    : baseDirections;
  const plannerAddedDirections = scopeLimitedByQuery
    ? []
    : plan.planner_added_directions || [];
  const directions = [...visibleBaseDirections, ...plannerAddedDirections];
  const [isEditingDirections, setIsEditingDirections] = useState(false);
  const [selectedDirectionIds, setSelectedDirectionIds] = useState<string[]>(
    directions.map((direction) => direction.direction_id)
  );
  const finalDirectionIds = [
    ...selectedDirectionIds,
    ...customDirectionText
      .replace(/^我还想重点看|^还想重点看|^重点看|^我还想看/, "")
      .split(/\n|,|，|;|；|以及|还有|和|与|、/)
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item, index) => customDirectionPreviewId(item, index)),
  ];
  const detectedCompetitors = plan.detected_competitors || [];
  const suggestedCompetitors = plan.suggested_competitors || [];
  const shouldSuggestCompetitors = detectedCompetitors.length < 2;
  const requiredDirectionIds = visibleBaseDirections
    .filter((direction) => direction.required)
    .map((direction) => direction.direction_id);
  const plannerAddedDirectionIds = plannerAddedDirections.map(
    (direction) => direction.direction_id
  );

  const toggleDirection = (directionId: string) => {
    const direction = directions.find(
      (item) => item.direction_id === directionId
    );
    if (direction?.required) return;

    setSelectedDirectionIds((current) =>
      current.includes(directionId)
        ? current.filter((item) => item !== directionId)
        : [...current, directionId]
    );
  };

  const renderDirectionCards = (
    items: AnalysisDirection[],
    title: string,
    description?: string
  ) => (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-gray-100">{title}</h3>
        {description && (
          <p className="mt-1 text-xs leading-5 text-gray-400">{description}</p>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((direction: AnalysisDirection) => (
          <div
            key={direction.direction_id}
            className="rounded-md border border-gray-800 bg-gray-950/40 p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <label className="flex min-w-0 items-start gap-2">
                {isEditingDirections && (
                  <input
                    type="checkbox"
                    checked={selectedDirectionIds.includes(
                      direction.direction_id
                    )}
                    disabled={direction.required}
                    onChange={() =>
                      toggleDirection(direction.direction_id)
                    }
                    className="mt-1 h-4 w-4 rounded border-gray-600 bg-gray-950 text-teal-500 disabled:opacity-50"
                  />
                )}
                <span className="text-sm font-semibold text-gray-100">
                  {direction.name}
                </span>
              </label>
              <span className="shrink-0 rounded-sm bg-gray-800 px-2 py-1 text-[11px] text-gray-300">
                {direction.direction_id}
              </span>
              <span className="shrink-0 rounded-sm bg-gray-800 px-2 py-1 text-[11px] text-gray-300">
                {direction.origin === "planner_suggested"
                  ? "Planner补充"
                  : direction.required
                    ? "必选"
                    : "可选"}
              </span>
            </div>
            <p className="mt-2 text-sm leading-6 text-gray-300">
              {direction.reason || direction.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-gray-950/80 px-4 py-6 backdrop-blur-sm">
      <div className="w-full max-w-3xl rounded-lg border border-gray-700 bg-gray-900 shadow-2xl shadow-black/40">
        <div className="border-b border-gray-800 px-5 py-4 sm:px-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-teal-300">
                PlanningAgent / IndustryDirectionSkill
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-100">
                确认行业与搜索方向
              </h2>
            </div>
            <div className="rounded-md border border-teal-500/30 bg-teal-500/10 px-3 py-2 text-sm text-teal-100">
              {plan.detected_industry || plan.industry.name}
              <span className="ml-2 text-teal-300">
                {Math.round((plan.industry.confidence || 0) * 100)}%
              </span>
            </div>
          </div>
        </div>

        <div className="max-h-[64vh] space-y-5 overflow-y-auto px-5 py-4 sm:px-6">
          {shouldSuggestCompetitors && suggestedCompetitors.length > 0 && (
            <section className="rounded-md border border-amber-500/30 bg-amber-500/10 p-4">
              <h3 className="text-sm font-semibold text-amber-100">
                还没有识别到明确的对比竞品
              </h3>
              <p className="mt-2 text-sm leading-6 text-amber-50/90">
                可以参考这些 {plan.detected_industry || plan.industry.name} 竞品：
                {suggestedCompetitors.slice(0, 6).join("、")}。你可以在问题里写明要对比的竞品后重新开始，也可以继续确认下方方向。
              </p>
            </section>
          )}

          <section className="rounded-md border border-gray-800 bg-gray-950/50 p-4">
            <h3 className="text-sm font-semibold text-gray-100">
              已分析出的行业与 direction_id
            </h3>
            <div className="mt-3 space-y-3 text-xs leading-5 text-gray-300">
              <p>
                <span className="text-gray-500">industry:</span>{" "}
                {plan.industry.industry_id} / {plan.detected_industry || plan.industry.name}
              </p>
              <p className="break-words font-mono">
                <span className="font-sans text-gray-500">必备 direction_id:</span>{" "}
                [{requiredDirectionIds.map((id) => `"${id}"`).join(", ")}]
              </p>
              <p className="break-words font-mono">
                <span className="font-sans text-gray-500">Agent 补充 direction_id:</span>{" "}
                [{plannerAddedDirectionIds.map((id) => `"${id}"`).join(", ")}]
              </p>
            </div>
          </section>

          {scopeLimitedByQuery && (
            <section className="rounded-md border border-teal-500/30 bg-teal-500/10 p-4">
              <h3 className="text-sm font-semibold text-teal-100">
                已按用户限定收窄
              </h3>
              <p className="mt-2 text-sm leading-6 text-teal-50/90">
                检测到只看/仅看/只关注等限定词，本次不会再自动补充其他方向。
              </p>
            </section>
          )}

          {renderDirectionCards(
            visibleBaseDirections,
            scopeLimitedByQuery ? "本次限定方向" : "行业原有方向"
          )}

          {plannerAddedDirections.length > 0 &&
            renderDirectionCards(
              plannerAddedDirections,
              "PlanningAgent 补充方向",
              "基于十个通用大方向对行业必备方向做覆盖检查，仅作为本次任务的补充建议。"
            )}

          {showCustomDirections && (
            <label className="mt-4 block">
              <span className="text-sm font-medium text-gray-200">
                还需要增加 direction_id 吗？需要的话直接输入方向即可。
              </span>
              <textarea
                value={customDirectionText}
                onChange={(event) => setCustomDirectionText(event.target.value)}
                placeholder="例如：我还想重点看 AI 写作能力和私有化部署能力。"
                className="mt-2 min-h-[108px] w-full resize-y rounded-md border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none transition focus:border-teal-400"
              />
            </label>
          )}

          <div className="mt-4 rounded-md border border-gray-800 bg-gray-950/50 p-3">
            <p className="text-xs uppercase tracking-[0.16em] text-gray-500">
              final_directions
            </p>
            <p className="mt-2 break-words font-mono text-xs text-gray-300">
              [{finalDirectionIds.map((id) => `"${id}"`).join(", ")}]
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-3 border-t border-gray-800 px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
          <button
            type="button"
            onClick={() => setIsEditingDirections(true)}
            className="rounded-md border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 transition hover:border-gray-500 hover:text-gray-100"
            disabled={isPreparingPlan}
          >
            修改分析方向
          </button>
          <button
            type="button"
            onClick={() => setShowCustomDirections(true)}
            className="rounded-md border border-teal-500/40 px-4 py-2 text-sm font-medium text-teal-200 transition hover:border-teal-300 hover:text-teal-100"
            disabled={isPreparingPlan}
          >
            补充自定义方向
          </button>
          <button
            type="button"
            onClick={() => onConfirm(selectedDirectionIds)}
            className="rounded-md bg-teal-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-500 disabled:opacity-60"
            disabled={isPreparingPlan}
          >
            {isPreparingPlan ? "处理中..." : "确认并开始分析"}
          </button>
        </div>
      </div>
    </div>
  );
}

function customDirectionPreviewId(value: string, index: number) {
  const text = value.trim().replace(/[。.]/g, "");
  const lowered = text.toLowerCase();
  if (lowered.includes("ai") || text.includes("人工智能")) {
    return "ai_capability";
  }
  if (text.includes("私有化") || text.includes("私有部署")) {
    return "private_deployment";
  }
  const slug = text
    .split("")
    .map((character) => (/^[a-z0-9]$/i.test(character) ? character.toLowerCase() : "_"))
    .join("")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_");
  return slug || `user_direction_${index + 1}`;
}
