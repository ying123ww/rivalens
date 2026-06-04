"use client";

import { useState, useEffect, useCallback } from "react";

export type ChatSession = {
  session_id: string;
  user_id: string;
  title: string;
  memory: { role: string; content: string; timestamp?: number }[];
  created_at: string;
  updated_at: string;
};

export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/sessions");
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch (err) {
      console.error("Failed to fetch chat sessions:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const createSession = useCallback(async (title = "新对话") => {
    try {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        const data = await res.json();
        setSessions((prev) => [data.session, ...prev]);
        return data.session as ChatSession;
      }
    } catch (err) {
      console.error("Failed to create session:", err);
    }
    return null;
  }, []);

  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
        return true;
      }
    } catch (err) {
      console.error("Failed to delete session:", err);
    }
    return false;
  }, []);

  const renameSession = useCallback(async (sessionId: string, title: string) => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        setSessions((prev) =>
          prev.map((s) =>
            s.session_id === sessionId ? { ...s, title } : s
          )
        );
        return true;
      }
    } catch (err) {
      console.error("Failed to rename session:", err);
    }
    return false;
  }, []);

  const getSession = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        return data.session as ChatSession;
      }
    } catch (err) {
      console.error("Failed to get session:", err);
    }
    return null;
  }, []);

  const appendMessage = useCallback(
    async (sessionId: string, message: { role: string; content: string }) => {
      try {
        const res = await fetch(`/api/sessions/${sessionId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message }),
        });
        if (res.ok) {
          setSessions((prev) =>
            prev.map((s) =>
              s.session_id === sessionId
                ? { ...s, memory: [...s.memory, message], updated_at: new Date().toISOString() }
                : s
            )
          );
          return true;
        }
      } catch (err) {
        console.error("Failed to append message:", err);
      }
      return false;
    },
    []
  );

  return {
    sessions,
    loading,
    createSession,
    deleteSession,
    renameSession,
    getSession,
    appendMessage,
    refreshSessions: fetchSessions,
  };
}
