export interface BaseData {
  type: string;
}

export interface BasicData extends BaseData {
  type: 'basic';
  content: string;
}

export interface LanggraphButtonData extends BaseData {
  type: 'langgraphButton';
  link: string;
}

export interface DifferencesData extends BaseData {
  type: 'differences';
  content: string;
  output: string;
}

export interface QuestionData extends BaseData {
  type: 'question';
  content: string;
}

export interface ChatData extends BaseData {
  type: 'chat';
  content: string;
  metadata?: any; // For storing search results and other contextual information
}

export type Data = BasicData | LanggraphButtonData | DifferencesData | QuestionData | ChatData;

export interface MCPConfig {
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
}

export interface IndustryCandidate {
  industry_id: string;
  name: string;
  confidence: number;
  signals: string[];
}

export interface AnalysisDirection {
  direction_id: string;
  name: string;
  reason?: string;
  description: string;
  search_focus: string;
  source_hints: string[];
  required: boolean;
  origin: "industry_template" | "user_requested";
}

export interface IndustryDirectionPlan {
  id: string;
  detected_industry?: string;
  industry: IndustryCandidate;
  candidate_industries: IndustryCandidate[];
  suggested_directions?: AnalysisDirection[];
  default_directions: AnalysisDirection[];
  user_added_directions: AnalysisDirection[];
  final_directions: AnalysisDirection[];
  final_analysis_plan: Record<string, any>;
  user_confirmed: boolean;
  created_at: string;
}

export interface ChatBoxSettings {
  report_type: string;
  report_source: string;
  tone: string;
  domains: string[];
  defaultReportType: string;
  layoutType: string;
  mcp_enabled: boolean;
  mcp_configs: MCPConfig[];
  mcp_strategy?: string;
  industry_direction_plan?: IndustryDirectionPlan;
}

export interface Domain {
  value: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: number;
  metadata?: any; // For storing search results and other contextual information
}

export interface ResearchHistoryItem {
  id: string;
  question: string;
  answer: string;
  timestamp: number;
  orderedData: Data[];
  chatMessages?: ChatMessage[];
}
