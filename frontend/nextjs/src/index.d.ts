declare module 'rivalens-ui' {
  import React from 'react';

  export interface ResearchEngineProps {
    apiUrl?: string;
    apiKey?: string;
    defaultPrompt?: string;
    onResultsChange?: (results: any) => void;
    theme?: any;
  }

  export const ResearchEngine: React.FC<ResearchEngineProps>;
}