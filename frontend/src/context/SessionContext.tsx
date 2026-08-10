import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { BatchJobAcceptedResponse, BatchMeetingResponse } from "../api/types";

const STORAGE_KEY = "meeting-assistant-session";

export interface UploadDraft {
  mode: "text" | "audio";
  title: string;
  transcript: string;
}

interface SessionState {
  activeWorkflowRunId: string;
  lastBatchResult: BatchMeetingResponse | BatchJobAcceptedResponse | null;
  uploadDraft: UploadDraft;
  searchQuery: string;
  lastQuestion: string;
}

const DEFAULT_UPLOAD_DRAFT: UploadDraft = {
  mode: "text",
  title: "",
  transcript: "",
};

function loadSession(): SessionState {
  const defaults: SessionState = {
    activeWorkflowRunId: "",
    lastBatchResult: null,
    uploadDraft: DEFAULT_UPLOAD_DRAFT,
    searchQuery: "",
    lastQuestion: "",
  };

  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as Partial<SessionState>;
      return {
        activeWorkflowRunId: parsed.activeWorkflowRunId ?? defaults.activeWorkflowRunId,
        lastBatchResult: parsed.lastBatchResult ?? defaults.lastBatchResult,
        uploadDraft: { ...DEFAULT_UPLOAD_DRAFT, ...parsed.uploadDraft },
        searchQuery: parsed.searchQuery ?? defaults.searchQuery,
        lastQuestion: parsed.lastQuestion ?? defaults.lastQuestion,
      };
    }
  } catch {
    // ignore invalid stored session
  }

  return defaults;
}

function persistSession(session: SessionState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

interface SessionContextValue extends SessionState {
  setActiveWorkflowRunId: (workflowRunId: string) => void;
  setLastBatchResult: (result: BatchMeetingResponse | BatchJobAcceptedResponse | null) => void;
  updateUploadDraft: (patch: Partial<UploadDraft>) => void;
  clearUploadDraft: () => void;
  setSearchQuery: (searchQuery: string) => void;
  setLastQuestion: (lastQuestion: string) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState>(loadSession);

  const updateSession = useCallback((patch: Partial<SessionState>) => {
    setSession((current) => {
      const next = { ...current, ...patch };
      persistSession(next);
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({
      ...session,
      setActiveWorkflowRunId: (workflowRunId: string) => {
        updateSession({ activeWorkflowRunId: workflowRunId });
      },
      setLastBatchResult: (result: BatchMeetingResponse | BatchJobAcceptedResponse | null) => {
        updateSession({ lastBatchResult: result });
      },
      updateUploadDraft: (patch: Partial<UploadDraft>) => {
        setSession((current) => {
          const next = {
            ...current,
            uploadDraft: { ...current.uploadDraft, ...patch },
          };
          persistSession(next);
          return next;
        });
      },
      clearUploadDraft: () => {
        updateSession({ uploadDraft: DEFAULT_UPLOAD_DRAFT });
      },
      setSearchQuery: (searchQuery: string) => {
        updateSession({ searchQuery });
      },
      setLastQuestion: (lastQuestion: string) => {
        updateSession({ lastQuestion });
      },
    }),
    [session, updateSession],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used within SessionProvider");
  }
  return context;
}
