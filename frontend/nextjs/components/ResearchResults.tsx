import React from 'react';
import Question from './ResearchBlocks/Question';
import Report from './ResearchBlocks/Report';
import Sources from './ResearchBlocks/Sources';
import ImageSection from './ResearchBlocks/ImageSection';
import SubQuestions from './ResearchBlocks/elements/SubQuestions';
import LogsSection from './ResearchBlocks/LogsSection';
import AccessReport from './ResearchBlocks/AccessReport';
import { preprocessOrderedData } from '../utils/dataProcessing';
import { Data, ResearchHistoryItem } from '../types/data';

type HomeAction = {
  label?: string;
  title?: string;
  onClick: () => void;
};

interface ResearchResultsProps {
  orderedData: Data[];
  answer: string;
  allLogs: any[];
  chatBoxSettings: any;
  handleClickSuggestion: (value: string) => void;
  currentResearchId?: string;
  isProcessingChat?: boolean;
  onShareClick?: () => void;
  reportContext?: Partial<ResearchHistoryItem> | Record<string, any> | null;
  homeAction?: HomeAction;
}

type SourceItem = { name: string; url: string };
type GenericRecord = Record<string, any>;

const asArray = (value: unknown): GenericRecord[] =>
  Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : [];

const getContextArray = (context: GenericRecord | null | undefined, key: string) => {
  if (!context) return [];
  const direct = asArray(context[key]);
  if (direct.length) return direct;
  const state = context.state && typeof context.state === 'object' ? context.state : {};
  return asArray(state[key]);
};

const sourceNameFromUrl = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
};

const buildSourcesFromReportContext = (
  context: Partial<ResearchHistoryItem> | Record<string, any> | null | undefined
): SourceItem[] => {
  const record = context as GenericRecord | null | undefined;
  const sources: SourceItem[] = [];
  const addSource = (urlValue: unknown, nameValue?: unknown) => {
    const url = String(urlValue || '').trim();
    if (!url) return;
    sources.push({
      url,
      name: String(nameValue || '').trim() || sourceNameFromUrl(url),
    });
  };

  for (const item of [
    ...getContextArray(record, 'evidence_index'),
    ...getContextArray(record, 'evidence_items'),
  ]) {
    addSource(item.url || item.source_url || item.metadata?.url, item.title);
  }

  const researchInformation =
    record?.research_information && typeof record.research_information === 'object'
      ? record.research_information
      : {};
  const sourceUrls = [
    ...(Array.isArray(researchInformation.source_urls) ? researchInformation.source_urls : []),
    ...(Array.isArray(researchInformation.visited_urls) ? researchInformation.visited_urls : []),
  ];
  for (const url of sourceUrls) {
    addSource(url);
  }

  const seen = new Set<string>();
  return sources.filter((source) => {
    if (seen.has(source.url)) return false;
    seen.add(source.url);
    return true;
  });
};

export const ResearchResults: React.FC<ResearchResultsProps> = ({
  orderedData,
  answer,
  allLogs,
  chatBoxSettings,
  handleClickSuggestion,
  currentResearchId,
  isProcessingChat = false,
  onShareClick,
  reportContext,
  homeAction
}) => {
  const groupedData = preprocessOrderedData(orderedData);
  const pathData = groupedData.find(data => data.type === 'path');
  const initialQuestion = groupedData.find(data => data.type === 'question');
  const reportRecord = reportContext as GenericRecord | null | undefined;
  const storedArtifacts =
    reportRecord?.report_artifacts && typeof reportRecord.report_artifacts === 'object'
      ? reportRecord.report_artifacts
      : reportRecord?.artifacts && typeof reportRecord.artifacts === 'object'
        ? reportRecord.artifacts
        : {};
  const accessData = pathData?.output || storedArtifacts;
  const hasAccessData = Boolean(
    accessData &&
      typeof accessData === 'object' &&
      ['pdf', 'docx', 'html', 'md', 'markdown'].some((key) => accessData[key])
  );

  const chatComponents = groupedData
    .filter(data => {
      if (data.type === 'question' && data === initialQuestion) {
        return false;
      }
      return (data.type === 'question' || data.type === 'chat');
    })
    .map((data, index) => {
      if (data.type === 'question') {
        return <Question key={`question-${index}`} question={data.content} />;
      } else {
        return <Report key={`chat-${index}`} answer={data.content} />;
      }
    });

  const sourceBlocks = groupedData
    .filter(data => data.type === 'sourceBlock')
    .map(data => data.items || [])
    .filter(items => items.length > 0);
  const contextSources = sourceBlocks.length ? [] : buildSourcesFromReportContext(reportContext);
  const sourceComponents = sourceBlocks.length
    ? sourceBlocks.map((sources, index) => (
        <Sources key={`sourceBlock-${index}`} sources={sources}/>
      ))
    : contextSources.length
      ? [<Sources key="sourceBlock-structured-evidence" sources={contextSources}/>]
      : [];

  const imageComponents = groupedData
    .filter(data => data.type === 'imagesBlock')
    .map((data, index) => (
      <ImageSection key={`images-${index}-${data.metadata?.length || 0}`} metadata={data.metadata} />
    ));

  const subqueriesComponent = groupedData.find(data => data.content === 'subqueries');

  return (
    <>
      {initialQuestion && <Question question={initialQuestion.content} homeAction={homeAction} />}
      {orderedData.length > 0 && (
        <LogsSection
          logs={allLogs}
          reportContext={reportContext}
          isResearching={isProcessingChat}
        />
      )}
      {subqueriesComponent && (
        <SubQuestions
          metadata={subqueriesComponent.metadata}
          handleClickSuggestion={handleClickSuggestion}
        />
      )}
      {sourceComponents}
      {imageComponents}
      {hasAccessData && (
        <AccessReport
          accessData={accessData}
          report={answer}
          chatBoxSettings={chatBoxSettings}
          onShareClick={onShareClick}
        />
      )}
      {chatComponents}
    </>
  );
};
