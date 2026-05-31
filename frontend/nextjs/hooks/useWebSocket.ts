import { useRef, useState, useEffect, useCallback } from 'react';
import { Data, ChatBoxSettings, QuestionData } from '../types/data';
import { getHost } from '../helpers/getHost';

export const useWebSocket = (
  setOrderedData: React.Dispatch<React.SetStateAction<Data[]>>,
  setAnswer: React.Dispatch<React.SetStateAction<string>>, 
  setLoading: React.Dispatch<React.SetStateAction<boolean>>,
  setShowHumanFeedback: React.Dispatch<React.SetStateAction<boolean>>,
  setQuestionForHuman: React.Dispatch<React.SetStateAction<boolean | true>>
) => {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const heartbeatInterval = useRef<number>();
  const researchActiveRef = useRef(false);

  // Cleanup function for heartbeat and socket on unmount
  useEffect(() => {
    return () => {
      // Clear heartbeat interval
      if (heartbeatInterval.current) {
        clearInterval(heartbeatInterval.current);
      }
      
      // Close socket on unmount if it exists and is open
      if (socket && socket.readyState === WebSocket.OPEN) {
        console.log('Closing WebSocket due to component unmount');
        researchActiveRef.current = false;
        socket.close(1000, "Component unmounted");
      }
    };
  }, [socket]);

  const startHeartbeat = (ws: WebSocket) => {
    // Clear any existing heartbeat
    if (heartbeatInterval.current) {
      clearInterval(heartbeatInterval.current);
    }
    
    // Start new heartbeat
    heartbeatInterval.current = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 30000); // Send ping every 30 seconds
  };

  const initializeWebSocket = useCallback((
    promptValue: string, 
    chatBoxSettings: ChatBoxSettings
  ) => {
    // Close existing socket if any
    if (socket && socket.readyState === WebSocket.OPEN) {
      console.log('Closing existing WebSocket connection');
      researchActiveRef.current = false;
      socket.close(1000, "New connection requested");
    }

    const storedConfig = localStorage.getItem('apiVariables');
    const apiVariables = storedConfig ? JSON.parse(storedConfig) : {};

    if (typeof window !== 'undefined') {
      
      let fullHost = getHost()
      const protocol = fullHost.includes('https') ? 'wss:' : 'ws:'
      const cleanHost = fullHost.replace('http://', '').replace('https://', '')
      const ws_uri = `${protocol}//${cleanHost}/ws`

      console.log(`Creating new WebSocket connection to ${ws_uri}`);
      const newSocket = new WebSocket(ws_uri);
      setSocket(newSocket);

      // WebSocket connection opened handler
      newSocket.onopen = () => {
        console.log('WebSocket connection opened');
        
        const domainFilters = JSON.parse(localStorage.getItem('domainFilters') || '[]');
        const domains = domainFilters ? domainFilters.map((domain: any) => domain.value) : [];
        const {
          report_type,
          report_source,
          tone,
          mcp_enabled,
          mcp_configs,
          mcp_strategy,
          industry_direction_plan
        } = chatBoxSettings;
        
        // Start a new research
        try {
          console.log(`Starting new research for: ${promptValue}`);
          const dataToSend = { 
            task: promptValue,
            report_type, 
            report_source, 
            tone,
            query_domains: domains,
            mcp_enabled: mcp_enabled || false,
            mcp_strategy: mcp_strategy || "fast",
            mcp_configs: mcp_configs || [],
            industry_direction_plan
          };
          
          // Make sure we have a properly formatted command with a space after start
          const message = `start ${JSON.stringify(dataToSend)}`;
          console.log(`Sending start message, length: ${message.length}`);
          researchActiveRef.current = true;
          newSocket.send(message);
        } catch (error) {
          console.error("Error preparing start message:", error);
          researchActiveRef.current = false;
        }
        
        startHeartbeat(newSocket);
      };

      newSocket.onmessage = (event) => {
        try {
          // Handle ping response
          if (event.data === 'pong') return;

          // Try to parse JSON data
          console.log(`Received WebSocket message: ${event.data.substring(0, 100)}...`);
          const data = JSON.parse(event.data);
          
          if (data.type === 'error') {
            console.error(`Server error: ${data.output}`);
          } else if (data.type === 'human_feedback' && data.content === 'request') {
            setQuestionForHuman(data.output);
            setShowHumanFeedback(true);
          } else {
            const contentAndType = `${data.content}-${data.type}`;
            setOrderedData((prevOrder) => [...prevOrder, { ...data, contentAndType }]);

            if (data.type === 'report') {
              setAnswer((prev: string) => prev + data.output);
            } else if (data.type === 'report_complete') {
              // Replace entire report with the complete version (includes images)
              console.log('Received complete report with images');
              setAnswer(data.output);
            } else if (data.type === 'path') {
              researchActiveRef.current = false;
              setLoading(false);
            }
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error, event.data);
        }
      };

      newSocket.onclose = (event) => {
        console.log(`WebSocket connection closed: code=${event.code}, reason=${event.reason}`);
        const wasResearchActive = researchActiveRef.current;
        researchActiveRef.current = false;
        if (heartbeatInterval.current) {
          clearInterval(heartbeatInterval.current);
        }
        if (wasResearchActive) {
          const reason = event.reason ? `, reason: ${event.reason}` : '';
          const output = (
            `WebSocket disconnected while research was still running ` +
            `(code: ${event.code || 'unknown'}${reason}). ` +
            `Live report streaming was interrupted; please restart this run.`
          );
          const disconnectData = {
            type: 'logs',
            content: 'websocket_disconnected',
            output,
            contentAndType: 'websocket_disconnected-logs'
          } as unknown as Data;

          setOrderedData((prevOrder) => [...prevOrder, disconnectData]);
          setLoading(false);
        }
        setSocket(null);
      };

      newSocket.onerror = (error) => {
        console.error('WebSocket error:', error);
        if (heartbeatInterval.current) {
          clearInterval(heartbeatInterval.current);
        }
      };
    }
  }, [socket, setOrderedData, setAnswer, setLoading, setShowHumanFeedback, setQuestionForHuman]);

  return { socket, setSocket, initializeWebSocket };
};
