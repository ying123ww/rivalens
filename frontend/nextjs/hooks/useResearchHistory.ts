import { useState, useEffect, useRef } from 'react';
import { toast } from 'react-hot-toast';
import { v4 as uuidv4 } from 'uuid';
import { ResearchHistoryItem, Data, ChatMessage } from '../types/data';

const RESEARCH_HISTORY_STORAGE_KEY = 'researchHistory';
const RESEARCH_HISTORY_META_KEY = 'researchHistoryMeta';  // 仅存轻量元数据
const DELETED_RESEARCH_IDS_STORAGE_KEY = 'deletedResearchIds';
const LOCALSTORAGE_MAX_ITEMS = 20;  // 最多保留最近 20 条

const loadDeletedResearchIdsFromStorage = () => {
  const deletedIdsStr = localStorage.getItem(DELETED_RESEARCH_IDS_STORAGE_KEY);
  if (!deletedIdsStr) {
    return new Set<string>();
  }

  try {
    const parsedIds = JSON.parse(deletedIdsStr);
    if (Array.isArray(parsedIds)) {
      return new Set(parsedIds.filter((id): id is string => typeof id === 'string'));
    }
  } catch (error) {
    console.error('Error parsing deleted research IDs:', error);
  }

  return new Set<string>();
};

const saveDeletedResearchIdsToStorage = (deletedIds: Set<string>) => {
  localStorage.setItem(
    DELETED_RESEARCH_IDS_STORAGE_KEY,
    JSON.stringify(Array.from(deletedIds))
  );
};

const rememberDeletedResearchId = (id: string) => {
  const deletedIds = loadDeletedResearchIdsFromStorage();
  deletedIds.add(id);
  saveDeletedResearchIdsToStorage(deletedIds);
};

// 从完整 history item 提取仅含标识信息的轻量元数据
const toMeta = (item: ResearchHistoryItem) => ({
  id: item.id,
  question: item.question,
  timestamp: item.timestamp,
  status: item.status,
});

const safeSetItem = (key: string, value: string): boolean => {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch (e) {
    if (e instanceof DOMException && e.name === 'QuotaExceededError') {
      console.warn(`localStorage quota exceeded for "${key}", attempting cleanup...`);
      // 清掉旧的历史数据腾空间
      localStorage.removeItem(RESEARCH_HISTORY_STORAGE_KEY);
      localStorage.removeItem(RESEARCH_HISTORY_META_KEY);
      try {
        localStorage.setItem(key, value);
        return true;
      } catch {
        console.error('localStorage still full after cleanup');
        return false;
      }
    }
    console.error(`localStorage.setItem("${key}") failed:`, e);
    return false;
  }
};

// 本地删除优先于服务端同步，避免重启后旧报告重新出现。
const filterDeletedResearch = (
  items: ResearchHistoryItem[],
  deletedIds: Set<string>
) => items.filter(item => item.id && !deletedIds.has(item.id));

export const useResearchHistory = () => {
  const [history, setHistory] = useState<ResearchHistoryItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const dataLoadedRef = useRef(false); // Track if data has been loaded
  
  // Fetch all research history on mount
  useEffect(() => {
    // Skip if data is already loaded to prevent excessive API calls
    if (dataLoadedRef.current) {
      return;
    }

    const fetchHistory = async () => {
      try {
        console.log('Fetching research history from server...');
        // First, load data from localStorage for immediate display
        const localHistory = loadFromLocalStorage();
        const deletedIds = loadDeletedResearchIdsFromStorage();
        const visibleLocalHistory = filterDeletedResearch(localHistory || [], deletedIds);
        
        // Set local history immediately to show something to user
        if (visibleLocalHistory.length > 0) {
          setHistory(visibleLocalHistory);
        }
        
        // Always fetch server history so refreshed browsers can recover runs
        // that were completed by the backend after the page was closed.
        const response = await fetch('/api/reports');
        if (response.ok) {
          const data = await response.json();

          if (data.reports && Array.isArray(data.reports)) {
            console.log('Loaded research history from server:', data.reports.length, 'items');
            await syncLocalHistoryWithServer(visibleLocalHistory, data.reports, deletedIds);
          } else {
            console.warn('Server response did not contain reports array', data);
          }
        } else {
          console.warn('Failed to load history from server, status:', response.status);
        }
      } catch (error) {
        console.error('Error fetching research history:', error);
        // We're already using local history from above
      } finally {
        dataLoadedRef.current = true; // Mark data as loaded
        setLoading(false);
      }
    };
    
    // Helper to load from localStorage（仅元数据，完整内容走服务端）
    const loadFromLocalStorage = (): ResearchHistoryItem[] => {
      // 优先读轻量元数据
      const metaStr = localStorage.getItem(RESEARCH_HISTORY_META_KEY);
      if (metaStr) {
        try {
          const metaList = JSON.parse(metaStr);
          if (Array.isArray(metaList)) {
            console.log('Loaded research history meta from localStorage:', metaList.length, 'items');
            return metaList.slice(0, LOCALSTORAGE_MAX_ITEMS);
          }
        } catch { /* fall through */ }
      }
      // 兼容旧格式（完整对象存储）
      const localHistoryStr = localStorage.getItem(RESEARCH_HISTORY_STORAGE_KEY);
      if (localHistoryStr) {
        try {
          const parsedHistory = JSON.parse(localHistoryStr);
          if (Array.isArray(parsedHistory)) {
            console.log('Loaded research history (legacy) from localStorage:', parsedHistory.length, 'items');
            // 迁移到轻量格式
            const metas = parsedHistory.slice(0, LOCALSTORAGE_MAX_ITEMS).map(toMeta);
            safeSetItem(RESEARCH_HISTORY_META_KEY, JSON.stringify(metas));
            // 清除旧格式的大数据
            localStorage.removeItem(RESEARCH_HISTORY_STORAGE_KEY);
            return parsedHistory.slice(0, LOCALSTORAGE_MAX_ITEMS);
          }
        } catch { /* fall through */ }
      }
      return [];
    };

    // Helper to sync local history with server
    const syncLocalHistoryWithServer = async (
      localHistory: ResearchHistoryItem[],
      serverHistory: ResearchHistoryItem[],
      deletedIds: Set<string>
    ) => {
      console.log('Syncing local history with server...');
      const visibleServerHistory = filterDeletedResearch(serverHistory, deletedIds);
      
      // Create a map of server history IDs for quick lookup
      const serverIds = new Set(visibleServerHistory.map(item => item.id));
      
      // Find local reports that aren't on the server
      const localOnlyReports = localHistory.filter(item => !serverIds.has(item.id));
      console.log('Found local-only reports:', localOnlyReports.length);
      
      // Upload local-only reports to server
      for (const report of localOnlyReports) {
        try {
          // Skip reports without questions or answers
          if (!report.question || !report.answer) continue;
          
          console.log(`Uploading local report to server: ${report.id}`);
          
          const response = await fetch('/api/reports', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              id: report.id,
              question: report.question,
              answer: report.answer,
              orderedData: report.orderedData || [],
              chatMessages: report.chatMessages || []
            }),
          });
          
          if (!response.ok) {
            console.warn(`Failed to upload local report ${report.id} to server:`, response.status);
          }
        } catch (error) {
          console.error(`Error uploading local report ${report.id} to server:`, error);
        }
      }
      
      // Create a unified history with server data prioritized
      const combinedHistory = [...visibleServerHistory];
      
      // Add local-only reports to the combined history
      for (const report of localOnlyReports) {
        if (!serverIds.has(report.id)) {
          combinedHistory.push(report);
        }
      }
      
      // Sort by timestamp if available, newest first
      const sortedHistory = combinedHistory.sort((a, b) => {
        const timeA = a.timestamp || 0;
        const timeB = b.timestamp || 0;
        return timeB - timeA;
      });
      
      setHistory(sortedHistory);

      // 只存轻量元数据到 localStorage，避免 QuotaExceededError
      const metas = sortedHistory.slice(0, LOCALSTORAGE_MAX_ITEMS).map(toMeta);
      safeSetItem(RESEARCH_HISTORY_META_KEY, JSON.stringify(metas));
      
      console.log('History sync complete, total items:', sortedHistory.length);
    };
    
    fetchHistory();
  }, []); // Empty dependency array - only run once on mount
  
  // Save new research
  const saveResearch = async (question: string, answer: string, orderedData: Data[]) => {
    try {
      // Generate a unique ID
      const id = uuidv4();
      
      // Save to backend
      const response = await fetch('/api/reports', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          id,
          question,
          answer,
          orderedData,
          chatMessages: []
        }),
      });
      
      if (response.ok) {
        const data = await response.json();
        const newId = data.id;
        
        // Update local state
        const newResearch = {
          id: newId,
          question,
          answer,
          orderedData,
          chatMessages: [],
          timestamp: Date.now(),
        };
        
        setHistory(prev => [newResearch, ...prev]);

        // 仅存轻量元数据
        const metas = [newResearch, ...prev].slice(0, LOCALSTORAGE_MAX_ITEMS).map(toMeta);
        safeSetItem(RESEARCH_HISTORY_META_KEY, JSON.stringify(metas));

        return newId;
      } else {
        throw new Error(`API error: ${response.status}`);
      }
    } catch (error) {
      console.error('Error saving research:', error);
      toast.error('Failed to save research to server. Saved locally only.');

      // Fallback: save to localStorage only
      const newResearch = {
        id: uuidv4(),
        question,
        answer,
        orderedData,
        chatMessages: [],
        timestamp: Date.now(),
      };

      setHistory(prev => [newResearch, ...prev]);

      const metaStr = localStorage.getItem(RESEARCH_HISTORY_META_KEY);
      const existingMetas = metaStr ? (() => { try { return JSON.parse(metaStr); } catch { return []; } })() : [];
      const metas = [newResearch, ...existingMetas].slice(0, LOCALSTORAGE_MAX_ITEMS).map(toMeta);
      safeSetItem(RESEARCH_HISTORY_META_KEY, JSON.stringify(metas));

      return newResearch.id;
    }
  };
  
  // Update existing research
  const updateResearch = async (id: string, answer: string, orderedData: Data[]) => {
    try {
      // Update in backend
      const response = await fetch(`/api/reports/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          answer,
          orderedData
        }),
      });
      
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }
      
      // Update local state
      setHistory(prev =>
        prev.map(item =>
          item.id === id ? { ...item, answer, orderedData, timestamp: Date.now() } : item
        )
      );

      // 仅更新元数据的时间戳
      const metaStr = localStorage.getItem(RESEARCH_HISTORY_META_KEY);
      if (metaStr) {
        try {
          const metas = JSON.parse(metaStr);
          const updated = metas.map((m: any) =>
            m.id === id ? { ...m, timestamp: Date.now() } : m
          );
          safeSetItem(RESEARCH_HISTORY_META_KEY, JSON.stringify(updated));
        } catch { /* ignore */ }
      }

      return true;
    } catch (error) {
      console.error('Error updating research:', error);

      // Update local state anyway
      setHistory(prev =>
        prev.map(item =>
          item.id === id ? { ...item, answer, orderedData, timestamp: Date.now() } : item
        )
      );

      return false;
    }
  };

  // Get research by ID
  const getResearchById = async (id: string) => {
    if (loadDeletedResearchIdsFromStorage().has(id)) {
      return null;
    }

    try {
      const response = await fetch(`/api/reports/${id}`);
      if (response.ok) {
        const data = await response.json();
        return data.report;
      } else if (response.status === 404) {
        return null;
      } else {
        throw new Error(`API error: ${response.status}`);
      }
    } catch (error) {
      console.error('Error getting research by ID:', error);
      return null;
    }
  };

  // Delete research
  const deleteResearch = async (id: string) => {
    rememberDeletedResearchId(id);
    setHistory(prev => prev.filter(item => item.id !== id));

    const metaStr = localStorage.getItem(RESEARCH_HISTORY_META_KEY);
    if (metaStr) {
      try {
        const metas = JSON.parse(metaStr);
        safeSetItem(RESEARCH_HISTORY_META_KEY, JSON.stringify(metas.filter((m: any) => m.id !== id)));
      } catch { /* ignore */ }
    }

    try {
      const response = await fetch(`/api/reports/${id}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      return true;
    } catch (error) {
      console.error('Error deleting research:', error);
      toast.error('已从侧边栏隐藏；后端删除失败，稍后会继续被本地过滤。');
      return false;
    }
  };

  // Add chat message
  const addChatMessage = async (id: string, message: ChatMessage) => {
    try {
      const response = await fetch(`/api/reports/${id}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(message),
      });
      
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }
      
      // Update local state (localStorage 不再存 chatMessages 全量，仅服务端持久化)
      setHistory(prev =>
        prev.map(item => {
          if (item.id === id) {
            const chatMessages = item.chatMessages || [];
            return { ...item, chatMessages: [...chatMessages, message] };
          }
          return item;
        })
      );

      return true;
    } catch (error) {
      console.error('Error adding chat message:', error);

      // Update local state anyway
      setHistory(prev =>
        prev.map(item => {
          if (item.id === id) {
            const chatMessages = item.chatMessages || [];
            return { ...item, chatMessages: [...chatMessages, message] };
          }
          return item;
        })
      );

      return false;
    }
  };

  // Get chat messages
  const getChatMessages = (id: string) => {
    // 从内存中的 history 获取（完整数据来自服务端，localStorage 不再存全量）
    if (Array.isArray(history)) {
      const research = history.find(item => item.id === id);
      if (research && research.chatMessages) {
        return research.chatMessages;
      }
    } else {
      console.warn('History is not an array when getting chat messages');
    }

    return [];
  };

  // Clear all history from local storage and server
  const clearHistory = async () => {
    try {
      const deletedIds = loadDeletedResearchIdsFromStorage();
      history.forEach(item => {
        if (item.id) {
          deletedIds.add(item.id);
        }
      });
      saveDeletedResearchIdsToStorage(deletedIds);
      
      // 清空本地列表，并用 tombstone 阻止服务端旧记录重新同步回来。
      setHistory([]);
      localStorage.removeItem(RESEARCH_HISTORY_META_KEY);
      localStorage.removeItem(RESEARCH_HISTORY_STORAGE_KEY);  // 清理旧格式
      
      return true;
    } catch (error) {
      console.error('Error clearing history:', error);
      return false;
    }
  };

  return {
    history,
    loading,
    saveResearch,
    updateResearch,
    getResearchById,
    deleteResearch,
    addChatMessage,
    getChatMessages,
    clearHistory
  };
}; 
