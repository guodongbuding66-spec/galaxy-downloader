import {
  createDefaultLocalEngineAdvancedOptions,
  resolveLocalEngineAdvancedJobOptions,
  type LocalEngineAdvancedOptions,
} from '@/lib/local-engine'
import type { LocalEngineBatchOptions } from '@/lib/local-engine-bridge'

export interface LocalEngineBatchPlanOptions {
  videoQuality: string
  audioQuality: string
  includeAudio: boolean
  includeSubtitle: boolean
  includeCover: boolean
  skipPreviouslyDownloaded: boolean
}

export function createDefaultLocalEngineBatchPlanOptions(): LocalEngineBatchPlanOptions {
  return {
    videoQuality: 'best',
    audioQuality: 'best',
    includeAudio: true,
    includeSubtitle: false,
    includeCover: false,
    skipPreviouslyDownloaded: false,
  }
}

export function buildLocalEngineBatchOptions(
  plan: LocalEngineBatchPlanOptions,
  advanced: LocalEngineAdvancedOptions = createDefaultLocalEngineAdvancedOptions(),
  aria2Ready = false,
): LocalEngineBatchOptions {
  return {
    videoQuality: plan.videoQuality || 'best',
    audioQuality: plan.audioQuality || 'best',
    includeAudio: plan.includeAudio,
    includeSubtitle: plan.includeSubtitle,
    subtitleLanguage: null,
    includeCover: plan.includeCover,
    skipPreviouslyDownloaded: plan.skipPreviouslyDownloaded,
    ...resolveLocalEngineAdvancedJobOptions(advanced, aria2Ready),
  }
}
