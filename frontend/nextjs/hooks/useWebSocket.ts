import { Dispatch, SetStateAction, useRef, useState, useEffect, useCallback } from 'react';
import { Data, ChatBoxSettings, ResearchHistoryItem } from '../types/data';
import { getHost } from '../helpers/getHost';

export const useWebSocket = (
  setOrderedData: Dispatch<SetStateAction<Data[]>>,
  setAnswer: Dispatch<SetStateAction<string>>, 
  setLoading: Dispatch<SetStateAction<boolean>>,
  setShowHumanFeedback: Dispatch<SetStateAction<boolean>>,
  setQuestionForHuman: Dispatch<SetStateAction<boolean | true>>,
  setCurrentResearchId?: Dispatch<SetStateAction<string | null>>,
  setReportContext?: Dispatch<SetStateAction<Partial<ResearchHistoryItem> | Record<string, any> | null>>
) => {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const heartbeatInterval = useRef<number>();
  const recoveryPollTimeout = useRef<number>();
  const researchActiveRef = useRef(false);
  const activeResearchIdRef = useRef<string | null>(null);

  const stopRecoveryPolling = useCallback(() => {
    if (recoveryPollTimeout.current) {
      clearTimeout(recoveryPollTimeout.current);
      recoveryPollTimeout.current = undefined;
    }
  }, []);

  const appendLog = useCallback((content: string, output: string, metadata?: any) => {
    setOrderedData((prevOrder) => [
      ...prevOrder,
      {
        type: 'logs',
        content,
        output,
        metadata,
        contentAndType: `${content}-logs`
      } as unknown as Data
    ]);
  }, [setOrderedData]);

  const applyRecoveredReport = useCallback((report: any): boolean => {
    if (!report) return false;
    const status = report.status;

    if (report.id) {
      activeResearchIdRef.current = report.id;
      setCurrentResearchId?.(report.id);
    }
    setReportContext?.(report);

    if (status === 'running') {
      if (Array.isArray(report.orderedData)) {
        setOrderedData(report.orderedData as Data[]);
      }
      if (typeof report.answer === 'string' && report.answer) {
        setAnswer(report.answer);
      }
      researchActiveRef.current = true;
      setLoading(true);
      return false;
    }

    if (status === 'completed' || status === 'error' || status === 'cancelled') {
      if (Array.isArray(report.orderedData)) {
        setOrderedData(report.orderedData as Data[]);
      }
      if (typeof report.answer === 'string') {
        setAnswer(report.answer);
      }
    }

    if (status === 'completed') {
      researchActiveRef.current = false;
      setLoading(false);
      localStorage.removeItem('activeResearchId');
      stopRecoveryPolling();
      return true;
    }

    if (status === 'error') {
      researchActiveRef.current = false;
      setLoading(false);
      appendLog(
        'run_error',
        report.error ? `Run failed: ${report.error}` : 'Run failed before a final report was available.',
        { research_id: report.id }
      );
      localStorage.removeItem('activeResearchId');
      stopRecoveryPolling();
      return true;
    }

    if (status === 'cancelled') {
      researchActiveRef.current = false;
      setLoading(false);
      localStorage.removeItem('activeResearchId');
      stopRecoveryPolling();
      return true;
    }

    return false;
  }, [appendLog, setAnswer, setCurrentResearchId, setLoading, setOrderedData, setReportContext, stopRecoveryPolling]);

  const pollRecoveredReport = useCallback((researchId: string, attempt = 0) => {
    stopRecoveryPolling();
    recoveryPollTimeout.current = window.setTimeout(async () => {
      try {
        const response = await fetch(`${getHost()}/api/reports/${researchId}`);
        if (response.ok) {
          const data = await response.json();
          if (applyRecoveredReport(data.report)) {
            return;
          }
        }
      } catch (error) {
        console.error('Error polling recovered report:', error);
      }

      const nextDelay = Math.min(15000, 3000 + attempt * 1000);
      recoveryPollTimeout.current = window.setTimeout(
        () => pollRecoveredReport(researchId, attempt + 1),
        nextDelay
      );
    }, attempt === 0 ? 1000 : 0);
  }, [applyRecoveredReport, stopRecoveryPolling]);

  // Cleanup function for heartbeat and socket on unmount
  useEffect(() => {
    return () => {
      // Clear heartbeat interval
      if (heartbeatInterval.current) {
        clearInterval(heartbeatInterval.current);
      }
      stopRecoveryPolling();
      
      // Close socket on unmount if it exists and is open
      if (socket && socket.readyState === WebSocket.OPEN) {
        console.log('Closing WebSocket due to component unmount');
        researchActiveRef.current = false;
        socket.close(1000, "Component unmounted");
      }
    };
  }, [socket, stopRecoveryPolling]);

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
    stopRecoveryPolling();
    activeResearchIdRef.current = null;
    localStorage.removeItem('activeResearchId');
    setCurrentResearchId?.(null);
    setReportContext?.(null);

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
          const researchId = `task_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
          const dataToSend = { 
            research_id: researchId,
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
          activeResearchIdRef.current = researchId;
          localStorage.setItem('activeResearchId', researchId);
          setCurrentResearchId?.(researchId);
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
            const researchId = data.metadata?.research_id || data.output?.research_id || data.research_id;
            if (researchId) {
              activeResearchIdRef.current = researchId;
              localStorage.setItem('activeResearchId', researchId);
              setCurrentResearchId?.(researchId);
            }
            const contentAndType = `${data.content}-${data.type}`;
            setOrderedData((prevOrder) => [...prevOrder, { ...data, contentAndType }]);

            if (data.type === 'report') {
              setAnswer((prev: string) => prev + data.output);
            } else if (data.type === 'report_complete') {
              // Replace entire report with the complete version (includes images)
              console.log('Received complete report with images');
              setAnswer(data.output);
              const reportContext = data.metadata?.report_context;
              if (reportContext && typeof reportContext === 'object') {
                setReportContext?.({
                  ...reportContext,
                  id: activeResearchIdRef.current || researchId || undefined,
                  answer: data.output,
                });
              }
              // Report is complete — stop loading even if the "path" message hasn't arrived yet.
              researchActiveRef.current = false;
              setLoading(false);
              localStorage.removeItem('activeResearchId');
            } else if (data.type === 'path') {
              if (data.output && typeof data.output === 'object') {
                setReportContext?.((current: any) => ({
                  ...(current || {}),
                  artifacts: data.output,
                  report_artifacts: {
                    ...((current || {}).report_artifacts || {}),
                    ...data.output,
                  },
                  id: data.output.research_id || activeResearchIdRef.current || undefined,
                }));
              }
              researchActiveRef.current = false;
              setLoading(false);
              localStorage.removeItem('activeResearchId');
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
          const recoveryId = activeResearchIdRef.current || localStorage.getItem('activeResearchId');
          const output = (
            `WebSocket disconnected while research was still running ` +
            `(code: ${event.code || 'unknown'}${reason}). ` +
            (
              recoveryId
                ? `Live report streaming was interrupted; the page will keep polling for the final report.`
                : `Live report streaming was interrupted; please restart this run.`
            )
          );
          appendLog('websocket_disconnected', output, { research_id: recoveryId });
          if (recoveryId) {
            setLoading(true);
            pollRecoveredReport(recoveryId);
          } else {
            setLoading(false);
          }
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
  }, [
    socket,
    setOrderedData,
    setAnswer,
    setLoading,
    setShowHumanFeedback,
    setQuestionForHuman,
    setCurrentResearchId,
    setReportContext,
    appendLog,
    pollRecoveredReport,
    stopRecoveryPolling,
  ]);

  return { socket, setSocket, initializeWebSocket };
};
